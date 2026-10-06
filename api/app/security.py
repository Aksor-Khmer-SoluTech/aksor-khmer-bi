"""Password hashing for `local`-auth users (see app/db.py's User model).

`ldap`-auth users have no local password_hash at all -- their credential
is verified against the directory at login time (app/auth_ldap.py,
Phase 2), not checked here.

Uses the `bcrypt` package directly rather than `passlib` -- passlib is
effectively unmaintained (no release since 2020) and its bcrypt backend
is broken against bcrypt>=4.1 (a known upstream incompatibility: passlib
depends on a `bcrypt.__about__` attribute bcrypt 4.1+ removed, and its
internal self-test then crashes on `hashpw` itself). bcrypt's own API is
tiny and stable enough not to need a wrapper library.
"""
from __future__ import annotations

import secrets

import bcrypt

# bcrypt silently truncates at 72 bytes; refusing longer input outright
# (rather than a silent truncation quirk from an old passlib version)
# means a caller finds out immediately, not "sometimes some long
# passwords collide."
_MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8

# No 0/O, 1/l/I: a temporary password an admin reads out or a user retypes
# from a message shouldn't hinge on telling those apart.
_GENERATED_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_GENERATED_LENGTH = 16


def check_password_policy(password: str) -> str:
    """Returns `password` unchanged, or raises ValueError with a message
    fit to show a user. Applied on every path that *sets* a password
    (create, admin reset, self-service change) -- never on login, so an
    account whose password predates this policy can still sign in.

    Printable ASCII only, and that isn't stylistic: a script may still send the
    credentials as an HTTP Basic header, which FastAPI decodes as ASCII --
    a password with a Khmer or accented character would be accepted here and
    then never be able to be used that way (and clients disagree about how to
    encode it).
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if not all(0x20 <= ord(ch) <= 0x7E for ch in password):
        raise ValueError("Password may only use standard keyboard characters (letters, digits, symbols, no accents or non-Latin scripts)")
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {_MAX_PASSWORD_BYTES} characters")
    return password


def generate_password() -> str:
    """A random temporary password that always satisfies check_password_policy
    and has at least one lower-case, upper-case and digit (so it also passes
    the usual "mixed" rules other systems bolt on). ~91 bits of entropy."""
    while True:
        candidate = "".join(secrets.choice(_GENERATED_ALPHABET) for _ in range(_GENERATED_LENGTH))
        if (
            any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)
            and any(c.isdigit() for c in candidate)
        ):
            return candidate


def hash_password(plain_password: str) -> str:
    encoded = plain_password.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {_MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        # Malformed/foreign hash format -- treat as "doesn't match" rather
        # than raising, same as a wrong password would behave.
        return False
