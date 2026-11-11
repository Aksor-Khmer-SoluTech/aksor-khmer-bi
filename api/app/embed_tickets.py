"""Embed tickets: what lets a host's *server* hand its browser a way to run one report without the browser
ever seeing an API client's secret (specs: dltms embedded-filter design, option B).

1. The host's server -- after deciding the signed-in user may run the report -- calls
   `POST /reports/{id}/embed-ticket` with the API client's id + secret and the **presets** it wants forced
   (for example `signedBy`, taken from the user's own account, not from anything the user typed).
2. The browser gets only the ticket and passes it to the embed frame, which uses it for `embed-form` and
   `embed-run` instead of client credentials.

A ticket names one client, one report (by `report_id`, never a code), the presets and an expiry (15 minutes by
default, 30 at most). It is signed with the same key as access tokens (app/auth_tokens.py) but carries its own
`typ`, so neither can stand in for the other. The client is looked up again on every use: disabling it, or
removing the report's grant, ends every ticket at once. Presets always win over values the frame submits.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

from . import auth_tokens
from .auth_tokens import TokenError, _b64u, _b64u_decode, _signing_key

TICKET_TYPE = "embed-ticket"
DEFAULT_TTL_SECONDS = 15 * 60
MAX_TTL_SECONDS = 30 * 60
MIN_TTL_SECONDS = 30


def issue(*, client_pk: str, report_id: str, presets: dict[str, str], subject: str | None, ttl: int | None) -> tuple[str, int]:
    """(ticket, seconds until it expires)."""
    seconds = min(max(ttl or DEFAULT_TTL_SECONDS, MIN_TTL_SECONDS), MAX_TTL_SECONDS)
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "iss": auth_tokens.ISSUER,
        "typ": TICKET_TYPE,
        "cid": client_pk,
        "rid": report_id,
        "pre": presets,
        "sub": subject or "",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + seconds,
    }
    signing_input = f"{_b64u(json.dumps(header, separators=(',', ':')).encode())}.{_b64u(json.dumps(claims, separators=(',', ':')).encode())}"
    signature = hmac.new(_signing_key(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64u(signature)}", seconds


def verify(ticket: str) -> dict:
    """The verified claims, or TokenError. Same checks as an access token's, plus the ticket's own type."""
    parts = ticket.split(".")
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
    if claims.get("iss") != auth_tokens.ISSUER or claims.get("typ") != TICKET_TYPE:
        raise TokenError("wrong_token")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp <= time.time():
        raise TokenError("expired")
    presets = claims.get("pre")
    if (
        not isinstance(claims.get("cid"), str)
        or not isinstance(claims.get("rid"), str)
        or not isinstance(presets, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in presets.items())
    ):
        raise TokenError("malformed")
    return claims
