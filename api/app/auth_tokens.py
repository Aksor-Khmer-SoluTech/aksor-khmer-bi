"""Access tokens and sign-in sessions -- the standard short-lived-JWT + rotating-refresh-token flow.

How a person stays signed in:

1. `POST /api/v1/auth/login` checks the password (and a 2FA code if the account has one),
   creates a **session** (app/db/auth_sessions.py) and answers with
   * an **access token** -- a signed JWT, valid for ACCESS_TOKEN_TTL_SECONDS (15 minutes by default),
     that the portal keeps in memory and sends as `Authorization: Bearer ...` on every call; and
   * a **refresh token** -- a long random string, set as an `HttpOnly` cookie scoped to the auth
     routes, so JavaScript can't read it and it is never sent to any other endpoint.
2. When the access token is about to expire the portal calls `POST /api/v1/auth/refresh`. The
   server swaps the refresh token for a **new one** (rotation) and mints a new access token.
3. `POST /api/v1/auth/logout` revokes the session; so does a password change, "sign out other
   sessions", or an administrator disabling the account.

What the access token does and doesn't carry: it names the user, organization and *session* --
not their permissions. Every request re-reads the user's roles and permissions from the database
(as the Basic-auth path always did), so a role change applies immediately, and every request checks
that the session is still live, so revoking a session ends it at once, not 15 minutes later.

Refresh-token theft: each refresh token works once. Presenting one that has already been replaced
means two parties hold it, so the whole session is revoked and both must sign in again. A short grace
window (REFRESH_GRACE_SECONDS) forgives the benign case -- two browser tabs refreshing in the same
moment with the same cookie -- by answering the late one with a fresh access token and no rotation.
Only the SHA-256 of a refresh token is stored, so a copy of the database can't be replayed.

Signing key: `JWT_SECRET` (32+ characters) if set -- the choice for several API replicas, which must all
share it -- otherwise a random key generated into data/secrets/jwt.key on first use (0600, gitignored,
never in the image; docker-compose.yml mounts data/secrets). Changing or losing it signs everyone out and
nothing else. HS256 is the only algorithm accepted: the token header's `alg` is never trusted to choose another one.

HTTP Basic (a username and password on every call) is still accepted for scripts -- see
app/auth.py -- unless AUTH_ALLOW_BASIC is turned off.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import db

_log = logging.getLogger("aksor_khmer_bi.auth_tokens")

KEY_ENV = "JWT_SECRET"
# api/app/auth_tokens.py -> parents[2] is the repo root, same as secret_store.
_REPO_ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = _REPO_ROOT / "data" / "secrets" / "jwt.key"

ISSUER = "aksor-khmer-bi"
TOKEN_TYPE = "access"


class TokenError(Exception):
    """The token or session isn't usable. `code` says why, for the log and the tests; what the
    caller is told is always the same plain 401."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- settings --------------------------------------------------------------------------------


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        value = default
    return min(max(value, low), high)


def access_ttl_seconds() -> int:
    """How long an access token lives. Short on purpose: it's the window in which a stolen one is useful."""
    return _int_env("ACCESS_TOKEN_TTL_SECONDS", 900, 60, 3600)


def refresh_ttl(remember: bool) -> timedelta:
    """The absolute lifetime of a session: long when the person asked to stay signed in, otherwise one working day."""
    if remember:
        return timedelta(days=_int_env("REFRESH_TOKEN_TTL_DAYS", 30, 1, 180))
    return timedelta(hours=_int_env("REFRESH_TOKEN_SESSION_HOURS", 12, 1, 72))


def refresh_grace_seconds() -> int:
    return _int_env("REFRESH_GRACE_SECONDS", 10, 0, 60)


def basic_allowed() -> bool:
    """HTTP Basic on API calls (for scripts). On by default; off forces every client through /auth/login."""
    return os.environ.get("AUTH_ALLOW_BASIC", "true").strip().lower() not in ("0", "false", "no", "off")


# --- the signing key -------------------------------------------------------------------------

_key_cache: tuple[tuple[str, str], bytes] | None = None


def _read_key_file() -> bytes | None:
    try:
        key = KEY_FILE.read_bytes().strip()
    except FileNotFoundError:
        return None
    return key or None


def _create_key_file() -> bytes:
    """Create KEY_FILE with a fresh key -- unless another process (api and a worker can start together)
    got there first, in which case use theirs. Written to a temp file and hard-linked into place so a reader
    never sees a half-written key and two creators can't each keep a different one."""
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(KEY_FILE.parent, 0o700)
    except OSError:
        pass  # a bind mount we don't own; the file's own 0600 is what matters
    key = secrets.token_urlsafe(48).encode("ascii")
    fd, tmp = tempfile.mkstemp(dir=KEY_FILE.parent, prefix=".jwt.key.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(key + b"\n")
        os.chmod(tmp, 0o600)
        try:
            os.link(tmp, KEY_FILE)
        except FileExistsError:
            return _read_key_file() or key
    finally:
        os.unlink(tmp)
    _log.warning(
        "Created the signing key for access tokens at %s -- keep it with the other files in data/secrets, "
        "or set %s instead (losing it only signs everyone out)",
        KEY_FILE, KEY_ENV,
    )
    return key


def _signing_key() -> bytes:
    global _key_cache
    from_env = os.environ.get(KEY_ENV, "").strip()
    signature = (from_env, str(KEY_FILE))
    if _key_cache is not None and _key_cache[0] == signature:
        return _key_cache[1]
    if from_env:
        if len(from_env) < 32:
            raise RuntimeError(f"{KEY_ENV} must be at least 32 characters")
        key = from_env.encode("utf-8")
    else:
        key = _read_key_file() or _create_key_file()
    _key_cache = (signature, key)
    return key


# --- JWT (HS256 only) -------------------------------------------------------------------------


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise TokenError("malformed") from exc


def encode_access_token(*, session_id: str, username: str, user_id: str | None, org_id: str | None) -> tuple[str, int]:
    """(token, seconds until it expires)."""
    ttl = access_ttl_seconds()
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "iss": ISSUER,
        "typ": TOKEN_TYPE,
        "sub": user_id or "breakglass",
        "usr": username,
        "org": org_id,
        "sid": session_id,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + ttl,
    }
    signing_input = f"{_b64u(json.dumps(header, separators=(',', ':')).encode())}.{_b64u(json.dumps(claims, separators=(',', ':')).encode())}"
    signature = hmac.new(_signing_key(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64u(signature)}", ttl


def decode_access_token(token: str) -> dict:
    """The verified claims, or TokenError. Checks, in this order: shape, the header's algorithm is
    exactly HS256 (never trusted to pick one -- so `none` and key-confusion tricks can't get through),
    the signature, the issuer and type, and expiry."""
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise TokenError("malformed")
    header_part, payload_part, signature_part = parts
    try:
        header = json.loads(_b64u_decode(header_part))
        claims = json.loads(_b64u_decode(payload_part))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenError("malformed") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict) or header.get("alg") != "HS256":
        raise TokenError("bad_alg")
    expected = hmac.new(_signing_key(), f"{header_part}.{payload_part}".encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64u_decode(signature_part)):
        raise TokenError("bad_signature")
    if claims.get("iss") != ISSUER or claims.get("typ") != TOKEN_TYPE:
        raise TokenError("wrong_token")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp <= time.time():
        raise TokenError("expired")
    if not isinstance(claims.get("sid"), str) or not isinstance(claims.get("usr"), str):
        raise TokenError("malformed")
    return claims


# --- sessions and refresh tokens ----------------------------------------------------------------


def hash_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def create_session(
    session: Session,
    *,
    user: db.User | None,
    username: str,
    ip_address: str | None,
    user_agent: str | None,
    remember: bool,
) -> tuple[db.AuthSession, str]:
    """Open a session and return it with its first refresh token (the only time the plain value exists)."""
    purge_old(session)
    now = _now()
    plain = _new_refresh_token()
    row = db.AuthSession(
        user_id=user.id if user is not None else None,
        username=username,
        refresh_hash=hash_token(plain),
        remember=remember,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:400] or None,
        created_at=now.isoformat(),
        last_used_at=now.isoformat(),
        expires_at=(now + refresh_ttl(remember)).isoformat(),
    )
    session.add(row)
    session.commit()
    return row, plain


@dataclass
class Rotation:
    session: db.AuthSession
    # The new refresh token to set as the cookie; None when this was a grace-window replay (the cookie is left as it is).
    refresh_token: str | None


def _live(row: db.AuthSession) -> bool:
    return row.revoked_at is None and _parse(row.expires_at) > _now()


def rotate(session: Session, refresh_token: str, *, ip_address: str | None, user_agent: str | None) -> Rotation:
    """Exchange a refresh token for the next one. Raises TokenError when it's unknown, expired or revoked --
    and, for one that was already used up (outside the grace window), revokes the whole session first."""
    digest = hash_token(refresh_token)
    row = session.execute(select(db.AuthSession).where(db.AuthSession.refresh_hash == digest).with_for_update()).scalar_one_or_none()
    now = _now()
    if row is not None:
        if not _live(row):
            raise TokenError("session_ended")
        plain = _new_refresh_token()
        row.previous_hash = row.refresh_hash
        row.refresh_hash = hash_token(plain)
        row.rotated_at = now.isoformat()
        row.last_used_at = now.isoformat()
        row.ip_address = ip_address or row.ip_address
        row.user_agent = ((user_agent or "")[:400] or row.user_agent)
        session.commit()
        return Rotation(row, plain)

    row = session.execute(select(db.AuthSession).where(db.AuthSession.previous_hash == digest).with_for_update()).scalar_one_or_none()
    if row is None:
        raise TokenError("unknown_token")
    if not _live(row):
        raise TokenError("session_ended")
    if row.rotated_at and (now - _parse(row.rotated_at)).total_seconds() <= refresh_grace_seconds():
        row.last_used_at = now.isoformat()
        session.commit()
        return Rotation(row, None)
    row.revoked_at = now.isoformat()
    row.revoked_reason = "reuse_detected"
    session.commit()
    _log.warning("Refresh token replayed for session %s (user %r): the session was revoked", row.id, row.username)
    raise TokenError("reuse_detected")


def find_by_refresh(session: Session, refresh_token: str) -> db.AuthSession | None:
    """The session a refresh token belongs to (current or just-replaced), whether or not it's still live."""
    digest = hash_token(refresh_token)
    return session.execute(
        select(db.AuthSession).where((db.AuthSession.refresh_hash == digest) | (db.AuthSession.previous_hash == digest))
    ).scalars().first()


def get_live_session(session: Session, session_id: str) -> db.AuthSession | None:
    row = session.get(db.AuthSession, session_id)
    return row if row is not None and _live(row) else None


def revoke_session(session: Session, session_id: str, reason: str) -> bool:
    row = session.get(db.AuthSession, session_id)
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = _now().isoformat()
    row.revoked_reason = reason
    session.commit()
    return True


def revoke_user_sessions(session: Session, user_id: str, reason: str, *, except_session_id: str | None = None) -> int:
    """End every live session of a user (a password change, an admin disabling the account...). Returns how many."""
    rows = session.execute(
        select(db.AuthSession).where(db.AuthSession.user_id == user_id, db.AuthSession.revoked_at.is_(None))
    ).scalars().all()
    count = 0
    stamp = _now().isoformat()
    for row in rows:
        if row.id == except_session_id:
            continue
        row.revoked_at = stamp
        row.revoked_reason = reason
        count += 1
    session.commit()
    return count


def live_sessions(session: Session, *, user_id: str | None, username: str | None = None) -> list[db.AuthSession]:
    """A person's sessions that are still usable, newest activity first. A break-glass session (no user row) is found by name."""
    query = select(db.AuthSession).where(db.AuthSession.revoked_at.is_(None))
    query = query.where(db.AuthSession.user_id == user_id) if user_id else query.where(
        db.AuthSession.user_id.is_(None), db.AuthSession.username == username
    )
    rows = session.execute(query.order_by(db.AuthSession.last_used_at.desc())).scalars().all()
    return [row for row in rows if _live(row)]


def purge_old(session: Session, keep_days: int = 7) -> None:
    """Forget sessions that ended (expired or revoked) more than `keep_days` ago -- done at sign-in, so there's no job to run."""
    cutoff = (_now() - timedelta(days=keep_days)).isoformat()
    session.execute(
        delete(db.AuthSession).where(
            (db.AuthSession.expires_at < cutoff) | (db.AuthSession.revoked_at.is_not(None) & (db.AuthSession.revoked_at < cutoff))
        )
    )
    session.commit()
