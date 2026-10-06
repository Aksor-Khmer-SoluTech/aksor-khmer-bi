"""TOTP (RFC 6238) second factor.

**What it guards**: signing in. routers/auth.py's `/auth/login` demands a current code once an account
has 2FA enabled, and only then opens a session (app/auth_tokens.py). A code rotates every 30 seconds, so
it can't be checked on every request -- the session's short-lived access token stands in for it after
sign-in, the same trade-off any token-based sign-in makes.

**And it can't be walked around**: an account with 2FA enabled is refused HTTP Basic on every other route
(app/auth.py's context_from_basic), so knowing the password alone gets an attacker nowhere -- the only way
to a session is through `/auth/login` and its code. A script that needs access should use its own service
account (a local user without 2FA, holding only the permissions the script needs) -- or, to run reports, an API
client (Admin > API Clients). (`/auth/verify`, the older password-check endpoint for scripts, is the
one narrow exception: it only asks for the code when called with `login=true`, and opens no session.)

Replay protection: `verify_totp_code` takes the account's
`last_used_step` (see db/rbac.py's User.totp_last_used_step) and refuses
to accept a step at or before it, so a single observed/leaked code can't
be replayed within its ~90s validity window across enroll/confirm,
login, and disable -- all three call sites share the same counter.
"""
from __future__ import annotations

import base64
import hmac
import io
import os
import time

import logging

import pyotp
import qrcode
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db, secret_store

_log = logging.getLogger("aksor_khmer_bi.totp")

_STEP_SECONDS = 30
_WINDOW_STEPS = 1  # +/- one 30s step of clock drift tolerated, same as most authenticator apps assume

# The label an authenticator app shows next to the account entry --
# overridable per self-hosted deployment the same way portal/public/
# config.js's PORTAL_BRAND_NAME white-labels the frontend (this is the
# backend-side equivalent; the two aren't unified since the backend has
# no access to that runtime frontend config).
ISSUER = os.environ.get("TOTP_ISSUER", "Aksor Khmer BI")


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def qr_code_data_url(otpauth_uri: str) -> str:
    """A `data:image/png;base64,...` URI the frontend can drop straight
    into an <img src> -- no separate image endpoint/round-trip needed."""
    img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


# --- the secret at rest ---------------------------------------------------------------------------
#
# An authenticator-app secret has to be readable to check a code, so it can't be hashed -- but it can be
# encrypted, the same way saved credentials are (app/secret_store.py: Fernet, key outside the database). A copy
# of the database then doesn't hand out everyone's second factor. The stored value carries that module's
# `v1:` prefix; a secret saved before this existed is plain base32 (which can never start with `v1:`), still
# accepted and encrypted in place at the next start (encrypt_legacy_secrets) or sign-in.


def seal(secret: str) -> str:
    """What to store in User.totp_secret."""
    return secret_store.encrypt(secret)


def unseal(stored: str) -> str:
    """The base32 secret behind a stored value -- encrypted, or a legacy plaintext one."""
    return secret_store.decrypt(stored) if stored.startswith("v1:") else stored


def encrypt_legacy_secrets(session: Session) -> int:
    """Encrypt any secret still stored as plain text (from before secrets were encrypted). Idempotent; returns
    how many it changed. Run at API start."""
    rows = session.execute(select(db.User).where(db.User.totp_secret.is_not(None))).scalars().all()
    changed = 0
    for row in rows:
        if row.totp_secret and not row.totp_secret.startswith("v1:"):
            row.totp_secret = seal(row.totp_secret)
            changed += 1
    if changed:
        session.commit()
        _log.info("Encrypted %d stored two-factor secret(s)", changed)
    return changed


def verify_totp_code(secret: str, code: str, last_used_step: int | None) -> int | None:
    """Returns the matched step (persist as the account's new
    last_used_step) if `code` is currently valid and not a replay of an
    already-used step, else None. `secret` is the stored value (see seal/unseal);
    one that can't be decrypted -- the encryption key changed -- never matches, so
    the account can't sign in until an administrator clears its 2FA.
    """
    code = code.strip()
    if not code:
        return None
    try:
        secret = unseal(secret)
    except secret_store.SecretError as exc:
        _log.error("A stored two-factor secret can't be read (%s) -- an administrator must reset that account's 2FA", exc)
        return None
    totp = pyotp.TOTP(secret)
    current_step = int(time.time()) // _STEP_SECONDS
    for step in range(current_step - _WINDOW_STEPS, current_step + _WINDOW_STEPS + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(totp.at(step * _STEP_SECONDS), code):
            return step
    return None
