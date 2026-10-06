"""Encryption at rest for the credentials people type into the portal -- today a
connection's bearer token or basic-auth password (app/connections.py).

Why the portal holds them at all: the alternative was an environment-variable
*name* on the connection, which meant someone with access to the server had to
set a variable and restart the API every time a token was issued or rotated.
A token that's managed in the portal changes in one form and applies to the
next run.

What that costs, and what the design does about it:

* The value is encrypted (Fernet: AES-128-CBC + HMAC-SHA256) before it is
  written to the database, so a copy of the database -- a backup, a dump, a
  read-only SQL foothold -- doesn't hand out the upstream API's credentials.
  The key is *not* in the database.
* It is write-only. No endpoint returns it, not even to whoever entered it;
  the portal shows "saved" and lets you replace or remove it. It never appears
  in the audit trail (which records only that it was set, replaced or removed)
  or in logs.
* What this doesn't defend against: anyone who can read both the database and
  the key (i.e. root on the API host). That is the same trust boundary an
  environment variable has, so nothing is lost relative to it.

The key: `SECRETS_ENCRYPTION_KEY` (a Fernet key) if set -- the choice for a
deployment that manages its own secrets -- otherwise a random key generated on
first use into data/secrets/master.key (0600, gitignored, never in the image).
Every service that needs to decrypt must see the same one; docker-compose.yml
mounts data/secrets into `api`. Losing the key means the stored credentials
can't be read any more (a run says so and an admin enters them again); it
doesn't lose anything else.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_log = logging.getLogger("aksor_khmer_bi.secret_store")

KEY_ENV = "SECRETS_ENCRYPTION_KEY"

# api/app/secret_store.py -> parents[2] is the repo root, same as report_store.
_REPO_ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = _REPO_ROOT / "data" / "secrets" / "master.key"

# Versions the stored format, so a later change of cipher or a key-rotation
# scheme can tell old values from new ones.
_PREFIX = "v1:"


class SecretError(Exception):
    """The key is unusable, or a stored value can't be decrypted with it. The
    message is safe to log; it never contains a key or a secret."""


_cache: tuple[tuple[str, str], Fernet] | None = None


def _read_key_file() -> bytes | None:
    try:
        key = KEY_FILE.read_bytes().strip()
    except FileNotFoundError:
        return None
    return key or None


def _create_key_file() -> bytes:
    """Create KEY_FILE holding a fresh key -- unless another process (the API and a
    worker can start together) got there first, in which case use theirs. Written to
    a temp file and hard-linked into place, so a reader never sees a half-written
    key and two creators can't each keep a different one."""
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(KEY_FILE.parent, 0o700)
    except OSError:
        pass  # a bind mount we don't own; the file's own 0600 is what matters
    key = Fernet.generate_key()
    fd, tmp = tempfile.mkstemp(dir=KEY_FILE.parent, prefix=".master.key.")
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
        "Created the encryption key for stored credentials at %s -- back it up with the database, "
        "or set %s instead (losing it means stored credentials must be entered again)",
        KEY_FILE, KEY_ENV,
    )
    return key


def _fernet() -> Fernet:
    global _cache
    from_env = os.environ.get(KEY_ENV, "").strip()
    signature = (from_env, str(KEY_FILE))
    if _cache is not None and _cache[0] == signature:
        return _cache[1]
    key = from_env.encode() if from_env else (_read_key_file() or _create_key_file())
    try:
        fernet = Fernet(key)
    except (ValueError, TypeError) as exc:
        source = f"the {KEY_ENV} environment variable" if from_env else str(KEY_FILE)
        raise SecretError(f"The encryption key in {source} isn't a valid Fernet key") from exc
    _cache = (signature, fernet)
    return fernet


def encrypt(plaintext: str) -> str:
    return _PREFIX + _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(stored: str) -> str:
    if not stored.startswith(_PREFIX):
        raise SecretError("A stored credential is in a format this version doesn't recognise")
    try:
        return _fernet().decrypt(stored[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretError(
            "A stored credential can't be decrypted -- the encryption key has changed since it was saved"
        ) from exc
