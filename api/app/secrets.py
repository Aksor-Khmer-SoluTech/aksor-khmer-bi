"""Secrets: named credentials -- a bearer token, a basic-auth password, or
anything else a report's data source or a connection used to need an
environment variable for -- created, rotated and revoked from the portal
(Admin > Secrets; routers/secrets.py) instead of the API server's own
environment. A deployment that would rather keep credentials out of the
database entirely can still name an environment variable instead; either way
is per credential, a deployment's own choice, not an all-or-nothing setting.

Why a name, not a value, lives in a report's/connection's own config: that
config is what a `report:manage`/`connection:manage` holder reads and edits
(and what the audit trail diffs) -- a secret's *value* is `secret:manage`-only,
encrypted at rest (app/secret_store.py), and never returned by any endpoint.
Rotating it (a new value, same name) needs no change to whatever refers to
it, the same reason app/connections.py exists at all: one place to update
instead of one per report.

Revoking (`is_active=False`) is deliberately not deleting: whatever still
names a revoked secret keeps existing, but resolve() below then fails with a
readable error -- the same "gone out from under a report" posture
app/connections.py's materialize already has for a deleted connection.
Deleting the row outright is refused while anything still refers to it
(used_by), so a name can't silently start meaning "nothing" underneath a
saved config.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db, report_data, secret_store
from .rbac import ROOT_ORG_ID

_log = logging.getLogger("aksor_khmer_bi.secrets")

# Same slug shape a connection name uses (report_data.CONNECTION_NAME_RE) --
# both are names other config refers to by typing them in, so both read the
# same way in a form and in the audit trail.
NAME_RE = report_data.CONNECTION_NAME_RE
MAX_NAME_LENGTH = report_data.MAX_CONNECTION_NAME_LENGTH
MAX_VALUE_LENGTH = 4096

DataConfigError = report_data.DataConfigError
DataSourceError = report_data.DataSourceError


def validate_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not (2 <= len(cleaned) <= MAX_NAME_LENGTH) or not NAME_RE.match(cleaned):
        raise DataConfigError(
            f"Secret name {cleaned!r} is invalid -- use 2-{MAX_NAME_LENGTH} lowercase letters and digits, "
            "with single hyphens or underscores between them (e.g. partner-api-token)"
        )
    return cleaned


def check_value(value: str) -> str:
    """The credential as it will be stored, or DataConfigError. Printable
    ASCII with no whitespace: a credential is sent as a header value or a
    query value, never intended to carry a line break or be padded/trimmed
    unpredictably -- catching that now beats a run failing on a byte the
    person didn't know was there."""
    if not value:
        raise DataConfigError("Enter the value")
    if not value.isascii() or not value.isprintable() or any(c.isspace() for c in value):
        raise DataConfigError("A credential is one run of letters, digits and symbols -- no spaces or line breaks")
    if len(value) > MAX_VALUE_LENGTH:
        raise DataConfigError(f"That's too long to be a credential (max {MAX_VALUE_LENGTH} characters)")
    return value


def _org(org_id: str | None) -> str:
    return org_id or ROOT_ORG_ID


def active_names_for_org(org_id: str | None) -> set[str]:
    """What a data source's or connection's `token_secret`/`password_secret`
    may name: only *active* secrets -- a revoked one can't be newly assigned,
    though whatever already names it keeps doing so (see this module's
    docstring) until an edit is saved with something else."""
    with db.SessionLocal() as session:
        return set(
            session.scalars(
                select(db.Secret.name).where(db.Secret.org_id == _org(org_id), db.Secret.is_active.is_(True))
            )
        )


def resolve(name: str, org_id: str | None) -> str:
    """The credential's current value, decrypted for this one call --
    connections.materialize is the only caller. Raises DataSourceError (safe
    to show whoever is running the report) if the name is gone, revoked, or
    can no longer be decrypted."""
    with db.SessionLocal() as session:
        row = session.scalar(
            select(db.Secret).where(db.Secret.org_id == _org(org_id), db.Secret.name == name)
        )
    if row is None:
        _log.error("Credential %r no longer exists in organization %r", name, _org(org_id))
        raise DataSourceError(f"The credential {name!r} no longer exists -- ask whoever manages it")
    if not row.is_active:
        _log.warning("Credential %r was resolved while revoked (organization %r)", name, _org(org_id))
        raise DataSourceError(f"The credential {name!r} has been revoked -- ask whoever manages it")
    try:
        return secret_store.decrypt(row.value_encrypted)
    except secret_store.SecretError as exc:
        _log.error("Credential %r: %s", name, exc)
        raise DataSourceError(
            f"The credential {name!r} can't be read by the server -- ask whoever manages it to rotate it"
        ) from exc


# --- who uses a secret -------------------------------------------------------


def _secret_refs(auth: dict | None) -> str | None:
    if not auth:
        return None
    return auth.get("token_secret") or auth.get("password_secret")


def _names_in(parameters: list | None, data_source: dict | None) -> set[str]:
    used: set[str] = set()
    ref = _secret_refs((data_source or {}).get("auth"))
    if ref:
        used.add(ref)
    for parameter in parameters or []:
        ref = _secret_refs((parameter.get("options_source") or {}).get("auth"))
        if ref:
            used.add(ref)
    return used


def used_by(session: Session, org_id: str | None) -> dict[str, list[dict[str, Any]]]:
    """{secret name: [{"kind": "report"|"connection", ...}, ...]} for every
    report or connection of the organization whose data source, choice list,
    or own authentication refers to a secret. Reads reports' and connections'
    JSON config -- fine at the scale of one organization's list, the same
    trade-off app/connections.py's reports_using already makes."""
    org = _org(org_id)
    usage: dict[str, list[dict[str, Any]]] = {}

    report_query = select(
        db.ReportRow.report_id, db.ReportRow.name, db.ReportRow.code, db.ReportRow.parameters, db.ReportRow.data_source
    ).order_by(db.ReportRow.name)
    report_query = (
        report_query.where(db.ReportRow.org_id == org)
        if org != ROOT_ORG_ID
        else report_query.where((db.ReportRow.org_id == org) | (db.ReportRow.org_id.is_(None)))
    )
    for row in session.execute(report_query):
        for name in _names_in(row.parameters, row.data_source):
            usage.setdefault(name, []).append(
                {"kind": "report", "report_id": row.report_id, "name": row.name, "code": row.code}
            )

    for row in session.scalars(select(db.DataConnection).where(db.DataConnection.org_id == org)):
        ref = _secret_refs((row.config or {}).get("auth"))
        if ref:
            usage.setdefault(ref, []).append({"kind": "connection", "connection_id": row.id, "name": row.name})

    return usage
