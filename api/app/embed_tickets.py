"""Signed run tickets -- how an embedder proves it may ask for a report *by
parameters*.

The public embed page (`#/embed/<report>`, ../../portal/src/components/EmbedPage.tsx)
has always been anonymous, and that was safe because everything it could ask
for was data the *caller* supplied: POST /reports/{id}/render draws nothing
from anywhere. A report with a server-side data source is different. "Run
this report for period1FromDate=...", answered by Aksor calling the data
source with the report's stored credentials, would hand anyone who can reach
this API (and guess a report code) the data behind that source, with no login.

So the embedder's own backend decides who may do that, and says so with a
short-lived ticket: partner-api checks its signed-in user's permission, then
signs "this report, with exactly these parameters, until <a few minutes from
now" with a secret only it and this server hold. POST /reports/{id}/embed-run
takes the parameters *and* the ticket, verifies the signature, that the
ticket is for this report, and that the parameters are the ones it was
issued for -- and only then fetches the data. A ticket can't be turned into
any other report or any other parameter values; without a valid one, nothing
is fetched.

The ticket is a standard HS256 JWT (so any JWT library can mint one, partner-api
uses JJWT). HS256 is the *only* algorithm accepted -- the header's `alg` is
never trusted to pick a different one, so neither `none` nor an RSA/HMAC
confusion can get a forged ticket through.

Configured by one environment variable, EMBED_TICKET_SECRET (32+ characters),
set to the same value here and in partner-api (AKSOR_EMBED_SECRET). Unset, embed
runs answer 503 rather than trusting anything: it fails closed.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time

ISSUER = "partner-api"
AUDIENCE = "aksor-embed"
ENV_VAR = "EMBED_TICKET_SECRET"
MIN_SECRET_LENGTH = 32

# Clock drift between the two servers.
LEEWAY_SECONDS = 10
# A ticket is meant to live minutes (partner-api defaults to 10 -- long enough for the
# viewer to still export another format, or open another file of a split report,
# with it); refuse one signed to live much longer even though its signature is
# good, so a leaked one can't stay useful.
MAX_LIFETIME_SECONDS = 900
MAX_TICKET_LENGTH = 8192

_INVALID = "Invalid ticket"


class TicketError(Exception):
    """Carries the HTTP status to answer with and a message that is safe to show."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _secret() -> bytes:
    value = os.environ.get(ENV_VAR, "")
    if len(value) < MIN_SECRET_LENGTH:
        # Not "invalid ticket": nothing is wrong with the caller's request, the
        # server just hasn't been set up to accept tickets.
        raise TicketError(503, f"Embedded report runs aren't configured on this server ({ENV_VAR} is not set)")
    return value.encode("utf-8")


def _b64url_decode(part: str) -> bytes:
    # validate=True: a stray character is an error, not something to skip past.
    return base64.b64decode(part.replace("-", "+").replace("_", "/") + "=" * (-len(part) % 4), validate=True)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def verify(ticket: object, *, now: float | None = None) -> dict:
    """Check `ticket`'s signature, issuer, audience and lifetime; return its claims.

    The claims carry `report` (a report code or id), `params` (the {name: value}
    the ticket was issued for) and `sub` (who it was issued to). Whether they
    match the request at hand is the caller's to check -- this only says the
    ticket is genuine, current, and meant for this service. Raises TicketError.
    """
    secret = _secret()
    if not isinstance(ticket, str) or len(ticket) > MAX_TICKET_LENGTH:
        raise TicketError(401, _INVALID)
    parts = ticket.split(".")
    if len(parts) != 3 or not all(parts):
        raise TicketError(401, _INVALID)
    header_part, payload_part, signature_part = parts

    try:
        header = json.loads(_b64url_decode(header_part))
        payload = json.loads(_b64url_decode(payload_part))
        signature = _b64url_decode(signature_part)
    except (ValueError, binascii.Error):
        raise TicketError(401, _INVALID) from None
    if not isinstance(header, dict) or not isinstance(payload, dict) or header.get("alg") != "HS256":
        raise TicketError(401, _INVALID)

    expected = hmac.new(secret, f"{header_part}.{payload_part}".encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, signature):
        raise TicketError(401, _INVALID)

    # From here on the payload is genuine -- these checks are about meaning.
    if payload.get("iss") != ISSUER:
        raise TicketError(401, _INVALID)
    audience = payload.get("aud")
    if AUDIENCE not in (audience if isinstance(audience, list) else [audience]):
        raise TicketError(401, _INVALID)

    now = time.time() if now is None else now
    expires = payload.get("exp")
    if not _is_number(expires):
        raise TicketError(401, _INVALID)
    if now > expires + LEEWAY_SECONDS:
        raise TicketError(401, "This ticket has expired")
    issued = payload.get("iat")
    if _is_number(issued) and (issued > now + LEEWAY_SECONDS or expires - issued > MAX_LIFETIME_SECONDS):
        raise TicketError(401, _INVALID)

    params = payload.get("params")
    if (
        not isinstance(payload.get("report"), str)
        or not isinstance(payload.get("sub"), str)
        or not isinstance(params, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in params.items())
    ):
        raise TicketError(401, _INVALID)
    return payload
