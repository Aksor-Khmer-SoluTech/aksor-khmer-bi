"""API clients: a client id + secret that may run specific reports (specs/api_clients_design.md).

The secret is 256 random bits, so unlike a password it can't be guessed and a
fast hash is the right one: SHA-256 of the secret is stored, and a presented
secret is hashed and compared in constant time. (bcrypt would only add ~100 ms
to every embedded run.) The secret itself exists only in the response that
creates or rotates it.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import db
from .rate_limit import RateLimiter
from .rbac import ROOT_ORG_ID

SECRET_PREFIX = "aksor_cs_"
# How much of a secret is kept to tell two of them apart in a list: the fixed
# prefix plus a few characters of the random part.
_DISPLAY_LENGTH = len(SECRET_PREFIX) + 4

_log = logging.getLogger("aksor_khmer_bi.clients")

CLIENT_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
CLIENT_ID_RE = re.compile(CLIENT_ID_PATTERN)

ENV_LIMIT = "CLIENT_RUN_LIMIT_PER_MINUTE"
DEFAULT_LIMIT_PER_MINUTE = 120

# last_used_at is a hint for admins, not an audit trail: write it at most this often.
_TOUCH_EVERY = timedelta(minutes=1)


def _client_limit() -> int:
    try:
        value = int(os.environ.get(ENV_LIMIT, DEFAULT_LIMIT_PER_MINUTE))
    except ValueError:
        return DEFAULT_LIMIT_PER_MINUTE
    return value if value >= 1 else DEFAULT_LIMIT_PER_MINUTE


# Keyed by client, not by address: a whole department's browsers can sit behind
# one proxy address, and it's the client that is being accounted for.
limiter = RateLimiter(limit=_client_limit)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_secret() -> tuple[str, str, str]:
    """(secret, display prefix, hash) for a freshly generated secret."""
    secret = SECRET_PREFIX + secrets.token_urlsafe(32)
    return secret, secret[:_DISPLAY_LENGTH], hash_secret(secret)


# What a lookup by an unknown client id is compared against, so that "no such
# client" costs the same as "wrong secret".
_DUMMY_HASH = hash_secret(SECRET_PREFIX + "0" * 43)


@dataclass(frozen=True)
class ClientIdentity:
    pk: str
    client_id: str
    org_id: str
    name: str


def authenticate(client_id: str, secret: str) -> ClientIdentity | None:
    """The client, if `client_id` names an active client and `secret` is its secret."""
    with db.SessionLocal() as session:
        row = session.execute(select(db.ApiClient).where(db.ApiClient.client_id == client_id)).scalar_one_or_none()
        expected = row.secret_hash if row is not None else _DUMMY_HASH
        matches = hmac.compare_digest(hash_secret(secret), expected)
        if row is None or not matches or not row.is_active:
            return None
        return ClientIdentity(pk=row.id, client_id=row.client_id, org_id=row.org_id, name=row.name)


def may_run(identity: ClientIdentity, report: dict) -> bool:
    """Whether the client holds a grant for this report, and the report is in the client's organization."""
    if (report.get("org_id") or ROOT_ORG_ID) != identity.org_id:
        return False
    with db.SessionLocal() as session:
        grant = session.execute(
            select(db.ApiClientReport.id).where(
                db.ApiClientReport.client_pk == identity.pk,
                db.ApiClientReport.report_id == report["report_id"],
            )
        ).first()
        return grant is not None


def touch(identity: ClientIdentity) -> None:
    """Record that the client was just used. Best effort -- never fails a run."""
    now = datetime.now(timezone.utc)
    try:
        with db.SessionLocal() as session:
            row = session.get(db.ApiClient, identity.pk)
            if row is None:
                return
            if row.last_used_at and now - datetime.fromisoformat(row.last_used_at) < _TOUCH_EVERY:
                return
            row.last_used_at = now.isoformat()
            session.commit()
    except Exception:  # noqa: BLE001 -- a bookkeeping hint must not break the run it describes
        _log.warning("Couldn't record last use of client %r", identity.client_id, exc_info=True)
