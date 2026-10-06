"""The signed-ticket check behind POST /reports/{id}/embed-run (app/embed_tickets.py).

A ticket is what lets an anonymous embed ask for a report *by parameters*, so
every way of getting one through that shouldn't work is worth pinning: a wrong
secret, a tampered payload, a different algorithm, an expired or over-long
lifetime, the wrong issuer or audience, an unset secret.

The tickets here are minted by a small independent HS256 implementation
(`mint`), not by the module under test -- the same way partner-api's JJWT does it
from the other side.
"""
import base64
import hashlib
import hmac
import json

import pytest

from app import embed_tickets

SECRET = "test-embed-secret-at-least-32-characters-long"
NOW = 1_800_000_000.0


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint(claims: dict | None = None, *, secret: str = SECRET, header: dict | None = None, now: float = NOW) -> str:
    payload = {
        "iss": "partner-api",
        "aud": "aksor-embed",
        "sub": "tester",
        "iat": int(now),
        "exp": int(now) + 120,
        "report": "revenue-comparison",
        "params": {"period1FromDate": "2026-08-01"},
        **(claims or {}),
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    head = _b64(json.dumps(header or {"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    sig = _b64(hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv(embed_tickets.ENV_VAR, SECRET)


def verify(ticket, **kw):
    return embed_tickets.verify(ticket, now=NOW, **kw)


def rejected(ticket, status=401) -> str:
    with pytest.raises(embed_tickets.TicketError) as exc:
        verify(ticket)
    assert exc.value.status == status
    return str(exc.value)


# --- a good ticket --------------------------------------------------------


def test_a_genuine_ticket_yields_its_claims():
    claims = verify(mint())
    assert claims["report"] == "revenue-comparison"
    assert claims["params"] == {"period1FromDate": "2026-08-01"}
    assert claims["sub"] == "tester"


def test_an_audience_list_containing_ours_is_accepted():
    assert verify(mint({"aud": ["something-else", "aksor-embed"]}))["sub"] == "tester"


def test_a_ticket_a_few_seconds_past_expiry_is_still_accepted_for_clock_drift():
    assert verify(mint({"exp": int(NOW) - 5, "iat": int(NOW) - 125}))["sub"] == "tester"


# --- the server isn't set up ----------------------------------------------


@pytest.mark.parametrize("value", [None, "", "too-short"])
def test_without_a_proper_secret_nothing_is_accepted_and_it_says_why(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(embed_tickets.ENV_VAR)
    else:
        monkeypatch.setenv(embed_tickets.ENV_VAR, value)
    message = rejected(mint(), status=503)  # even a ticket that would otherwise verify
    assert embed_tickets.ENV_VAR in message


# --- forgery ----------------------------------------------------------------


def test_a_ticket_signed_with_another_secret_is_refused():
    rejected(mint(secret="another-secret-that-is-also-32-chars-long!!"))


def test_editing_the_payload_after_signing_is_refused():
    head, body, sig = mint().split(".")
    tampered = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    tampered["params"] = {"period1FromDate": "1999-01-01"}
    forged_body = _b64(json.dumps(tampered).encode())
    rejected(f"{head}.{forged_body}.{sig}")


def test_alg_none_is_refused():
    head = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = mint().split(".")[1]
    rejected(f"{head}.{body}.")  # empty signature
    rejected(f"{head}.{body}.{_b64(b'x')}")


def test_only_hs256_is_accepted_even_with_a_valid_signature_for_the_header_given():
    head = _b64(json.dumps({"alg": "HS512", "typ": "JWT"}).encode())
    body = mint().split(".")[1]
    sig = _b64(hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha512).digest())
    rejected(f"{head}.{body}.{sig}")


@pytest.mark.parametrize(
    "ticket",
    ["", "a", "a.b", "a.b.c", "...", "not.a.jwt", "a.b.c.d", "e30.e30.e30", "🙂.🙂.🙂", "x" * 20_000],
)
def test_garbage_is_refused_not_crashed_on(ticket):
    rejected(ticket)


@pytest.mark.parametrize("ticket", [None, 123, ["a", "b", "c"], {"a": 1}])
def test_a_non_string_ticket_is_refused(ticket):
    rejected(ticket)


# --- what the signature doesn't cover: its meaning --------------------------


def test_an_expired_ticket_is_refused_and_says_so():
    assert "expired" in rejected(mint({"exp": int(NOW) - 3600, "iat": int(NOW) - 3720}))


@pytest.mark.parametrize("claims", [{"iss": "someone-else"}, {"iss": None}, {"aud": "another-service"}, {"aud": None}])
def test_the_wrong_issuer_or_audience_is_refused(claims):
    rejected(mint(claims))


@pytest.mark.parametrize("exp", [None, "soon", True, [1]])
def test_a_missing_or_non_numeric_expiry_is_refused(exp):
    rejected(mint({"exp": exp}))


def test_a_ticket_signed_to_live_too_long_is_refused_even_though_its_signature_is_good():
    rejected(mint({"iat": int(NOW), "exp": int(NOW) + 24 * 3600}))


def test_a_ticket_issued_in_the_future_is_refused():
    rejected(mint({"iat": int(NOW) + 3600, "exp": int(NOW) + 3720}))


@pytest.mark.parametrize(
    "claims",
    [
        {"report": None},
        {"report": 7},
        {"sub": None},
        {"params": None},
        {"params": ["period1FromDate"]},
        {"params": {"period1FromDate": 20260801}},  # a value that isn't a string
    ],
)
def test_claims_of_the_wrong_shape_are_refused(claims):
    rejected(mint(claims))


def test_a_ticket_with_no_params_object_at_all_is_refused():
    rejected(mint({"params": None}))


def test_empty_params_is_a_valid_ticket_for_a_report_without_filters():
    assert verify(mint({"params": {}}))["params"] == {}
