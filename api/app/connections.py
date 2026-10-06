"""Connections: named, reusable places a report's data comes from.

A report's data source (and each REST-backed choice list) can name a
connection instead of spelling out a full URL, headers and credentials:

    data_source = {"connection": "partner-api", "url": "/api/external/reports/x?from={{ fromDate }}", ...}

At run time `materialize` swaps the reference for the connection's current
base URL, headers and authentication, and hands the fetch code an ordinary,
complete source -- so an API that moves (or a dev/production switch) is one
edit on the connection, not one per report, and the fetch/validation code in
app/report_data.py never learned that connections exist.

Security shape, unchanged from a report spelling its own URL: what a caller
of a run supplies is only parameter *values*, which land after the host and
are percent-encoded; where the server connects and which credential it sends
come from configuration only a `connection:manage` holder (or a report
manager, for a report's own URL) can write. A connection's credential is
never a value in its `config`: either the *name* of an environment variable
on the server, or the *name* of a Secret (app/secrets.py) -- a credential
created, rotated and revoked in the portal -- resolved by `materialize` for
the one call that needs it, same as a report's own data source.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from . import db, jdbc, jdbc_drivers, report_data
from . import secrets as secrets_mod
from .rbac import ROOT_ORG_ID

_log = logging.getLogger("aksor_khmer_bi.connections")

# The kind is stored with each connection and says how to read its `config`:
# "rest" -- {"base_url", "headers", "auth"}; "jdbc" -- a database (app/jdbc.py).
KINDS = ("rest", "jdbc")
NAME_RE = report_data.CONNECTION_NAME_RE
MAX_NAME_LENGTH = report_data.MAX_CONNECTION_NAME_LENGTH
MAX_BASE_URL_LENGTH = 500

DataConfigError = report_data.DataConfigError
DataSourceError = report_data.DataSourceError


def validate_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not (2 <= len(cleaned) <= MAX_NAME_LENGTH) or not NAME_RE.match(cleaned):
        raise DataConfigError(
            f"Connection name {cleaned!r} is invalid -- use 2-{MAX_NAME_LENGTH} lowercase letters and digits, "
            "with single hyphens or underscores between them (e.g. partner-api)"
        )
    return cleaned


def validate_config(
    kind: str, config: dict, secret_names: set[str] | None = None, drivers: dict[str, dict] | None = None
) -> dict:
    """Strict validation + normalization of a connection's config. Raises
    DataConfigError with a message the person filling in the form can act on.
    `drivers` is the organization's uploaded JDBC drivers (JDBC kind only)."""
    if kind not in KINDS:
        raise DataConfigError(f"Connection kind {kind!r} isn't supported -- only {', '.join(KINDS)} for now")
    if kind == "jdbc":
        return jdbc.validate_config(config, secret_names, drivers)
    if "base_url" not in config:
        raise DataConfigError("This is a REST connection -- it needs a base URL")
    base_url = _validate_base_url(config.get("base_url"))
    headers, auth = report_data._validate_headers_and_auth(config, "connection", secret_names)
    return {"base_url": base_url, "headers": headers, "auth": auth}


def _validate_base_url(raw: Any) -> str:
    """http(s) scheme + host, optionally a path prefix (`https://erp.example/api`)
    -- and nothing that changes per request: no `{{ }}`, no query, no fragment."""
    url = (raw or "").strip() if isinstance(raw, str) else ""
    if not url:
        raise DataConfigError("The connection needs a base URL, e.g. https://erp.example.com")
    if len(url) > MAX_BASE_URL_LENGTH:
        raise DataConfigError(f"The base URL is too long (max {MAX_BASE_URL_LENGTH} characters)")
    if "{" in url or "}" in url:
        raise DataConfigError("The base URL is fixed text -- put {{ filters }} in the report's own path instead")
    url = report_data._validate_url(url, "connection base")
    parts = urlsplit(url)
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise DataConfigError("The base URL can't have a query string or #fragment -- those belong to each report's own path")
    if parts.username or parts.password:
        raise DataConfigError("Don't put a username or password in the URL -- use the authentication settings")
    return url.rstrip("/")


# --- looking connections up -----------------------------------------------


def _org(org_id: str | None) -> str:
    return org_id or ROOT_ORG_ID


def names_for_org(org_id: str | None) -> set[str]:
    with db.SessionLocal() as session:
        return set(session.scalars(select(db.DataConnection.name).where(db.DataConnection.org_id == _org(org_id))))


def kinds_for_org(org_id: str | None) -> dict[str, str]:
    """{connection name: kind} -- what a report's data source is checked against, so
    a JDBC query can't name a REST connection or the other way round."""
    with db.SessionLocal() as session:
        rows = session.execute(
            select(db.DataConnection.name, db.DataConnection.kind).where(db.DataConnection.org_id == _org(org_id))
        )
        return {row.name: row.kind for row in rows}


def resolve_jdbc(config: dict, org_id: str | None, *, where: str) -> dict:
    """A JDBC connection's config ready to connect: the credential decrypted for
    this one call, and the uploaded driver (if any) described for the worker.
    The result holds a password -- it goes to jdbc.run_query and nowhere else."""
    creds = _resolve_auth(config.get("auth"), org_id, where=where)
    assert creds is not None
    return {
        **{key: config.get(key) for key in ("engine", "host", "port", "database", "service_type", "ssl_mode", "jdbc_url")},
        "username": creds["username"],
        "password": creds["password"],
        "driver": jdbc_drivers.describe(config["driver_id"], org_id) if config.get("driver_id") else None,
    }


def _resolve_auth(auth: dict | None, org_id: str | None, *, where: str) -> dict | None:
    """`auth` (a data source's own, or a connection's) with its credential name
    (`token_env`/`token_secret`, `password_env`/`password_secret`) turned into
    a literal `token`/`password` -- the shape report_data._apply_auth expects.
    Called for every source materialize() hands back, connection or not, so
    a report's own auth gets exactly the same treatment a connection's does.
    Raises DataSourceError -- safe to show whoever is running the report --
    if an environment variable isn't set or a Secret can't be resolved."""
    if not auth:
        return None
    if auth["type"] == "bearer":
        if "token_env" in auth:
            token = os.environ.get(auth["token_env"])
            if not token:
                _log.error("%s auth: environment variable %r is not set", where, auth["token_env"])
                raise DataSourceError("The credential for this request isn't configured on the server")
        else:
            token = secrets_mod.resolve(auth["token_secret"], org_id)
        return {"type": "bearer", "token": token}

    if "password_env" in auth:
        password = os.environ.get(auth["password_env"])
        if password is None:
            _log.error("%s auth: environment variable %r is not set", where, auth["password_env"])
            raise DataSourceError("The credential for this request isn't configured on the server")
    else:
        password = secrets_mod.resolve(auth["password_secret"], org_id)
    return {"type": "basic", "username": auth["username"], "password": password}


def materialize(source: dict, org_id: str | None) -> dict:
    """`source` (a data source or options source dict) ready to fetch: its
    connection, if any, folded in (base URL in front of the path, its headers
    under the source's own, its authentication as the source's), and either
    way its `auth` resolved to a literal credential for this one call. Raises
    DataSourceError -- safe to show a person running the report -- when the
    connection is gone, or a credential can't be resolved."""
    name = source.get("connection")
    if not name:
        return {**source, "auth": _resolve_auth(source.get("auth"), org_id, where="Data source")}
    with db.SessionLocal() as session:
        row = session.scalar(
            select(db.DataConnection).where(db.DataConnection.org_id == _org(org_id), db.DataConnection.name == name)
        )
        connection = None if row is None else {"kind": row.kind, "config": row.config}
    if connection is None:
        _log.error("Report source names connection %r, which doesn't exist in organization %r", name, _org(org_id))
        raise DataSourceError(f"This report's connection {name!r} no longer exists -- ask whoever manages this report")
    if source.get("type") == "jdbc":
        if connection["kind"] != "jdbc":
            raise DataSourceError(f"This report's connection {name!r} isn't a database connection -- ask whoever manages this report")
        return {**source, "jdbc": resolve_jdbc(connection["config"], org_id, where=f"Connection {name!r}")}
    if connection["kind"] != "rest":
        raise DataSourceError(f"This report's connection {name!r} can't be used here")

    config = connection["config"]
    # Case-insensitive, the report's own header winning: HTTP header names are.
    merged: dict[str, tuple[str, str]] = {}
    for headers in (config.get("headers") or {}, source.get("headers") or {}):
        for header, value in headers.items():
            merged[header.lower()] = (header, value)
    return {
        **source,
        "url": config["base_url"] + source.get("url", ""),
        "headers": {header: value for header, value in merged.values()} or None,
        "auth": _resolve_auth(config.get("auth"), org_id, where=f"Connection {name!r}"),
    }


# --- who uses a connection ------------------------------------------------


def _names_in(parameters: list | None, data_source: dict | None) -> set[str]:
    used: set[str] = set()
    if data_source and data_source.get("connection"):
        used.add(data_source["connection"])
    for parameter in parameters or []:
        source = parameter.get("options_source") or {}
        if source.get("connection"):
            used.add(source["connection"])
    return used


def reports_using(session, org_id: str | None) -> dict[str, list[dict]]:
    """{connection name: [{"report_id", "name", "code"}, ...]} for every report
    of the organization that fetches through a connection. Reads the reports'
    JSON config -- fine at the scale of one organization's report list."""
    org = _org(org_id)
    query = select(
        db.ReportRow.report_id, db.ReportRow.name, db.ReportRow.code, db.ReportRow.parameters, db.ReportRow.data_source
    ).order_by(db.ReportRow.name)
    query = query.where(db.ReportRow.org_id == org) if org != ROOT_ORG_ID else query.where(
        (db.ReportRow.org_id == org) | (db.ReportRow.org_id.is_(None))
    )
    usage: dict[str, list[dict]] = {}
    for row in session.execute(query):
        for name in _names_in(row.parameters, row.data_source):
            usage.setdefault(name, []).append({"report_id": row.report_id, "name": row.name, "code": row.code})
    return usage


def secret_names_in_use(auth: dict | None) -> str | None:
    """The Secret name a (validated) auth refers to, if any -- used to build the
    `credential` hint on a connection summary without importing app/secrets.py
    just for that."""
    if not auth:
        return None
    return auth.get("token_secret") or auth.get("password_secret")
