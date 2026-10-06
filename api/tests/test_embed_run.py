"""POST /reports/{id}/embed-run: an anonymous embed asking for a report by
parameters, authorized by a signed ticket (app/embed_tickets.py).

The property everything here protects: the report's data source is only ever
called for a request that carries a genuine, current ticket, issued for *this*
report and *exactly these* parameters -- and never on the strength of anything
the embed's visitor typed. So most tests assert two things: the answer, and
that the data source was (or wasn't) called.

Nothing here sends an Authorization header: an embed has no account.
"""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from io import BytesIO

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clients, db, embed_tickets, report_data
from app.routers.reports import _report_headers
from app.main import app

client = TestClient(app)

SECRET = "test-embed-secret-at-least-32-characters-long"
TOKEN_ENV = "ERP_TEST_TOKEN"
PARAMS = {"p_from": "2026-08-01", "p_to": "2026-08-31", "p_signed": "Sok Sophea"}

DEFINITIONS = [
    {"name": "p_from", "label": "From", "type": "date", "required": True},
    {"name": "p_to", "label": "To", "type": "date", "required": True},
    {"name": "p_signed", "label": "Signed by", "type": "text", "required": False},
]
DATA_SOURCE = {
    "url": "https://erp.example.test/api/sales?from={{ p_from }}&to={{ p_to }}",
    "method": "GET",
    "headers": {"X-Client-Id": "aksor-khmer-bi"},
    "auth": {"type": "bearer", "token_env": TOKEN_ENV},
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def ticket(params=None, *, report="sales", sub="tester", secret=SECRET, exp_in=120, **extra) -> str:
    now = int(time.time())
    payload = {
        "iss": "partner-api", "aud": "aksor-embed", "sub": sub, "iat": now, "exp": now + exp_in,
        "report": report, "params": PARAMS if params is None else params, **extra,
    }
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    return f"{head}.{body}.{_b64(hmac.new(secret.encode(), f'{head}.{body}'.encode(), hashlib.sha256).digest())}"


@dataclass
class FakeErp:
    """The report's REST data source: records every request the server makes."""

    calls: list = field(default_factory=list)
    status: int = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "boom"})
        return httpx.Response(200, json={"total": "1200", "office": "Phnom Penh"})


@pytest.fixture
def erp(monkeypatch) -> FakeErp:
    fake = FakeErp()
    monkeypatch.setattr(
        report_data, "_make_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler), follow_redirects=False)
    )
    monkeypatch.setenv(TOKEN_ENV, "erp-secret-token")
    return fake


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv(embed_tickets.ENV_VAR, SECRET)


@pytest.fixture
def report(auth_headers) -> str:
    """A .docx report with code `sales`, three filters and a data source."""
    doc = Document()
    doc.add_paragraph("Sales {{ p_from }} to {{ p_to }}: {{ total }} at {{ office }}, signed {{ p_signed }}")
    buf = BytesIO()
    doc.save(buf)
    resp = client.post(
        "/api/v1/reports",
        files={"file": ("t.docx", buf.getvalue(), "application/octet-stream")},
        data={"name": "Sales", "code": "sales"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    report_id = resp.json()["report_id"]
    cfg = client.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": DEFINITIONS, "data_source": DATA_SOURCE},
        headers=auth_headers,
    )
    assert cfg.status_code == 200, cfg.text
    return report_id


def _text(content: bytes) -> str:
    # The renderer inserts zero-width word-break marks for Khmer line breaking; drop them.
    return "\n".join(p.text for p in Document(BytesIO(content)).paragraphs).replace("\u200b", "")


def embed_run(ref, body, **kw):
    return client.post(f"/api/v1/reports/{ref}/embed-run", json=body, **kw)


def _denials() -> list:
    with db.SessionLocal() as session:
        return list(session.scalars(select(db.AccessDeniedEvent)))


# --- the happy path ---------------------------------------------------------


def test_a_ticketed_run_fetches_the_data_server_side_and_renders(report, erp):
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket(), "format": "docx"})
    assert resp.status_code == 200, resp.text
    assert _text(resp.content) == "Sales 2026-08-01 to 2026-08-31: 1200 at Phnom Penh, signed Sok Sophea"

    # The data came from the source, called with the report's own credentials...
    assert len(erp.calls) == 1
    call = erp.calls[0]
    assert str(call.url) == "https://erp.example.test/api/sales?from=2026-08-01&to=2026-08-31"
    assert call.headers["Authorization"] == "Bearer erp-secret-token"
    assert call.headers["X-Client-Id"] == "aksor-khmer-bi"


def test_by_report_id_as_well_as_by_code(report, erp):
    assert embed_run(report, {"parameters": PARAMS, "ticket": ticket()}).status_code == 200  # ref in the URL: an id
    assert embed_run("sales", {"parameters": PARAMS, "ticket": ticket(report=report)}).status_code == 200  # claim: an id


def test_defaults_to_pdf_and_honours_part(report, erp):
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket(), "part": 1})
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
    assert embed_run("sales", {"parameters": PARAMS, "ticket": ticket(), "part": 9}).status_code == 400


# --- no ticket, no data ------------------------------------------------------


def test_a_run_with_neither_a_ticket_nor_client_credentials_is_refused(report, erp):
    resp = embed_run("sales", {"parameters": PARAMS})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "This report can only be run with a signed ticket or API client credentials"
    assert erp.calls == []
    assert _denials() == []  # anyone can send these: logged, not written to the security feed


@pytest.mark.parametrize("bad", ["", "garbage", "a.b.c", "x" * 9000])
def test_a_ticket_that_isnt_one_is_refused_without_touching_the_data_source(report, erp, bad):
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": bad})
    assert resp.status_code in (401, 422)
    assert erp.calls == []


def test_a_ticket_signed_with_another_secret_is_refused(report, erp):
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket(secret="another-secret-that-is-also-32-chars-long!!")})
    assert resp.status_code == 401 and resp.json()["detail"] == "Invalid ticket"
    assert erp.calls == []


def test_an_expired_ticket_is_refused_and_says_so(report, erp):
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket(exp_in=-3600)})
    assert resp.status_code == 401 and "expired" in resp.json()["detail"]
    assert erp.calls == []


def test_a_server_with_no_secret_refuses_everything_rather_than_trusting_anything(report, erp, monkeypatch):
    monkeypatch.delenv(embed_tickets.ENV_VAR)
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket()})
    assert resp.status_code == 503 and embed_tickets.ENV_VAR in resp.json()["detail"]
    assert erp.calls == []


def test_rejections_of_anonymous_callers_are_logged_not_written_to_the_security_feed(report, erp):
    # Anyone can send a bad ticket; a database row per attempt would let them grow the table.
    for _ in range(3):
        embed_run("sales", {"parameters": PARAMS, "ticket": "garbage"})
    assert _denials() == []


def test_an_unknown_report_is_a_404_before_anything_else(erp):
    assert embed_run("nope", {"parameters": PARAMS, "ticket": ticket()}).status_code == 404
    assert erp.calls == []


# --- a genuine ticket can't be bent to another request -----------------------


def test_the_parameters_must_be_exactly_those_the_ticket_was_issued_for(report, erp):
    tampered = {**PARAMS, "p_from": "1999-01-01"}
    resp = embed_run("sales", {"parameters": tampered, "ticket": ticket()})
    assert resp.status_code == 403
    assert erp.calls == []


@pytest.mark.parametrize(
    "body_params",
    [
        {k: v for k, v in PARAMS.items() if k != "p_signed"},  # one fewer
        {**PARAMS, "p_extra": "x"},  # one more
    ],
)
def test_dropping_or_adding_a_parameter_is_not_the_same_request(report, erp, body_params):
    assert embed_run("sales", {"parameters": body_params, "ticket": ticket()}).status_code == 403
    assert erp.calls == []


def test_a_ticket_for_one_report_does_not_run_another(report, erp):
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket(report="payroll")})
    assert resp.status_code == 403 and "different report" in resp.json()["detail"]
    assert erp.calls == []


def test_a_genuine_ticket_used_wrongly_is_recorded_in_the_security_feed(report, erp):
    embed_run("sales", {"parameters": {**PARAMS, "p_from": "1999-01-01"}, "ticket": ticket(sub="sok.sophea")})
    embed_run("sales", {"parameters": PARAMS, "ticket": ticket(report="payroll", sub="sok.sophea")})
    events = _denials()
    assert [e.permission_code for e in events] == ["report:embed-run", "report:embed-run"]
    assert {e.username for e in events} == {"ticket:sok.sophea"}
    assert {e.resource for e in events} == {report}


# --- what the ticket doesn't excuse ------------------------------------------


def test_the_parameters_are_still_validated_against_the_reports_definitions(report, erp):
    bad = {**PARAMS, "p_from": "not-a-date"}
    resp = embed_run("sales", {"parameters": bad, "ticket": ticket(bad)})  # signed, but not a valid date
    assert resp.status_code == 400
    assert erp.calls == []

    unknown = {**PARAMS, "p_extra": "x"}
    resp = embed_run("sales", {"parameters": unknown, "ticket": ticket(unknown)})
    assert resp.status_code == 400 and "p_extra" in resp.json()["detail"]
    assert erp.calls == []


def test_a_format_the_template_cant_produce_is_refused(report, erp):
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket(), "format": "xlsx"})
    assert resp.status_code == 400
    assert erp.calls == []


def test_a_failing_data_source_is_a_readable_502_not_a_crash(report, erp):
    erp.status = 500
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket()})
    assert resp.status_code == 502 and "data source" in resp.json()["detail"]


def test_the_data_source_credentials_are_never_in_the_response(report, erp):
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket(), "format": "docx"})
    assert b"erp-secret-token" not in resp.content
    assert "erp-secret-token" not in json.dumps(dict(resp.headers))


def test_run_and_render_are_unchanged_by_the_shared_helper(report, erp, auth_headers):
    run = client.post(f"/api/v1/reports/{report}/run", json={"parameters": PARAMS, "format": "docx"}, headers=auth_headers)
    assert run.status_code == 200 and "Phnom Penh" in _text(run.content)
    assert client.post(f"/api/v1/reports/{report}/render?format=docx", json={"total": "1", "office": "X", **PARAMS}).status_code == 200


# --- a run describes what it rendered ---------------------------------------


def test_a_run_says_which_report_and_template_type_it_rendered(report, erp, auth_headers):
    # So the embed page can start from parameters alone, with no lookup of the report first.
    secret, _ = make_client(auth_headers, [report])
    for body in (
        {"parameters": PARAMS, "ticket": ticket(), "format": "docx"},
        {"parameters": PARAMS, "format": "docx", **creds(secret)},
    ):
        resp = embed_run("sales", body)
        assert resp.status_code == 200
        assert resp.headers["X-Report-Name"] == "Sales" and resp.headers["X-Report-Ext"] == "docx"


def test_a_khmer_report_name_travels_percent_encoded():
    from urllib.parse import unquote

    headers = _report_headers({"name": "ប្រៀបធៀបចំណូល", "template_ext": "docx"})
    headers["X-Report-Name"].encode("ascii")  # a header value must be plain ASCII
    assert unquote(headers["X-Report-Name"]) == "ប្រៀបធៀបចំណូល"
    assert headers["X-Report-Ext"] == "docx"


# --- API clients: client id + secret (app/clients.py) -----------------------


@pytest.fixture(autouse=True)
def fresh_client_limiter(monkeypatch):
    monkeypatch.delenv(clients.ENV_LIMIT, raising=False)
    clients.limiter.reset()
    yield
    clients.limiter.reset()


def make_client(auth_headers, report_ids=(), client_id="partner-web", **extra) -> tuple[str, dict]:
    """A client through the real management API. Returns (secret, its ClientOut)."""
    resp = client.post(
        "/api/v1/clients",
        json={"client_id": client_id, "name": "Partner web", "report_ids": list(report_ids), **extra},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["secret"], resp.json()["client"]


def creds(secret, client_id="partner-web") -> dict:
    return {"client_id": client_id, "client_secret": secret}


def test_a_granted_client_runs_the_report_from_parameters_alone(report, erp, auth_headers):
    secret, out = make_client(auth_headers, [report])
    resp = embed_run("sales", {"parameters": PARAMS, "format": "docx", **creds(secret)})
    assert resp.status_code == 200, resp.text
    assert _text(resp.content) == "Sales 2026-08-01 to 2026-08-31: 1200 at Phnom Penh, signed Sok Sophea"

    # The server called the source, with the report's own credentials -- never the client's.
    assert len(erp.calls) == 1
    assert erp.calls[0].headers["Authorization"] == "Bearer erp-secret-token"
    assert secret not in str(erp.calls[0].url) and secret not in str(erp.calls[0].headers)

    # ...and the use is visible to the admin who manages the client.
    assert client.get(f"/api/v1/clients/{out['id']}", headers=auth_headers).json()["last_used_at"]


def test_granting_a_client_is_all_it_takes_no_restart_no_setting(report, erp, auth_headers):
    assert embed_run("sales", {"parameters": PARAMS}).status_code == 401
    secret, _ = make_client(auth_headers, [report])
    assert embed_run("sales", {"parameters": PARAMS, **creds(secret)}).status_code == 200


def test_the_report_can_be_named_by_id_or_by_code(report, erp, auth_headers):
    secret, _ = make_client(auth_headers, [report])
    assert embed_run(report, {"parameters": PARAMS, **creds(secret)}).status_code == 200
    assert embed_run("sales", {"parameters": PARAMS, **creds(secret)}).status_code == 200


@pytest.mark.parametrize("who", ["wrong-secret", "unknown-client", "disabled-client"])
def test_bad_credentials_are_refused_with_one_message_and_nothing_is_fetched(report, erp, auth_headers, who):
    secret, out = make_client(auth_headers, [report])
    body = {
        "wrong-secret": creds(secret + "x"),
        "unknown-client": creds(secret, client_id="nobody-here"),
        "disabled-client": creds(secret),
    }[who]
    if who == "disabled-client":
        client.patch(f"/api/v1/clients/{out['id']}", json={"is_active": False}, headers=auth_headers)

    resp = embed_run("sales", {"parameters": PARAMS, **body})
    assert resp.status_code == 401 and resp.json()["detail"] == "Invalid client credentials"
    assert erp.calls == []


def test_a_client_can_only_run_the_reports_it_was_granted(report, erp, auth_headers):
    secret, _ = make_client(auth_headers, [])
    resp = embed_run("sales", {"parameters": PARAMS, **creds(secret)})
    assert resp.status_code == 403 and resp.json()["detail"] == "This client may not run this report"
    assert erp.calls == []
    # A genuine client asking for what it wasn't given is something the security feed shows.
    assert [(d.username, d.resource) for d in _denials()] == [("client:partner-web", report)]


def test_revoking_the_grant_takes_effect_on_the_next_run(report, erp, auth_headers):
    secret, out = make_client(auth_headers, [report])
    assert embed_run("sales", {"parameters": PARAMS, **creds(secret)}).status_code == 200
    client.put(f"/api/v1/clients/{out['id']}/reports", json={"report_ids": []}, headers=auth_headers)
    assert embed_run("sales", {"parameters": PARAMS, **creds(secret)}).status_code == 403


def test_a_rotated_secret_replaces_the_old_one_immediately(report, erp, auth_headers):
    secret, out = make_client(auth_headers, [report])
    new = client.post(f"/api/v1/clients/{out['id']}/rotate-secret", headers=auth_headers).json()["secret"]
    assert embed_run("sales", {"parameters": PARAMS, **creds(secret)}).status_code == 401
    assert embed_run("sales", {"parameters": PARAMS, **creds(new)}).status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        {**PARAMS, "extra": "1"},  # undeclared parameter
        {"p_from": "2026-08-01"},  # a required one is missing
        {**PARAMS, "p_from": "not-a-date"},  # wrong shape for a date
        {**PARAMS, "p_signed": "x" * 500},  # over the length cap
    ],
)
def test_a_clients_run_still_validates_its_parameters(report, erp, auth_headers, params):
    secret, _ = make_client(auth_headers, [report])
    assert embed_run("sales", {"parameters": params, **creds(secret)}).status_code == 400
    assert erp.calls == []


def test_a_caller_cannot_steer_the_data_source_with_a_parameter_value(report, erp, auth_headers):
    secret, _ = make_client(auth_headers, [report])
    tricky = {**PARAMS, "p_signed": "a&from=1999-01-01#x"}
    assert embed_run("sales", {"parameters": tricky, **creds(secret)}).status_code == 200
    # p_signed isn't in the URL, and the values that are can only be dates -- the host is fixed by the config.
    assert erp.calls[0].url.host == "erp.example.test"
    assert erp.calls[0].url.query == b"from=2026-08-01&to=2026-08-31"


@pytest.mark.parametrize(
    "extra",
    [
        {"client_id": "partner-web"},  # id without a secret
        {"client_secret": "aksor_cs_x"},  # secret without an id
    ],
)
def test_the_client_id_and_secret_go_together(report, extra):
    assert embed_run("sales", {"parameters": PARAMS, **extra}).status_code == 422


def test_a_ticket_and_client_credentials_are_not_accepted_together(report, erp, auth_headers):
    secret, _ = make_client(auth_headers, [report])
    resp = embed_run("sales", {"parameters": PARAMS, "ticket": ticket(), **creds(secret)})
    assert resp.status_code == 422
    assert erp.calls == []


def test_a_client_of_another_organization_cannot_run_the_report(report, erp, auth_headers):
    with db.SessionLocal() as session:
        org = db.Organization(id="acme", name="Acme", is_active=True, created_at="2026-01-01T00:00:00+00:00")
        session.add(org)
        session.commit()
    secret, out = make_client(auth_headers, [], client_id="acme-web", org_id="acme")
    # Even a grant row planted directly can't cross organizations.
    with db.SessionLocal() as session:
        session.add(db.ApiClientReport(client_pk=out["id"], report_id=report, granted_at="2026-01-01T00:00:00+00:00"))
        session.commit()
    assert embed_run("sales", {"parameters": PARAMS, **creds(secret, "acme-web")}).status_code == 403
    assert erp.calls == []


def test_client_runs_are_rate_limited_per_client_not_per_address(report, erp, auth_headers, monkeypatch):
    monkeypatch.setenv(clients.ENV_LIMIT, "2")
    secret, _ = make_client(auth_headers, [report])
    other_secret, _ = make_client(auth_headers, [report], client_id="second-client")

    body = {"parameters": PARAMS, **creds(secret)}
    assert [embed_run("sales", body).status_code for _ in range(3)] == [200, 200, 429]
    assert embed_run("sales", body).headers["Retry-After"]
    # Another client, from the same address, is unaffected.
    assert embed_run("sales", {"parameters": PARAMS, **creds(other_secret, "second-client")}).status_code == 200


def test_the_secret_is_not_echoed_in_any_response(report, erp, auth_headers):
    secret, _ = make_client(auth_headers, [report])
    ok = embed_run("sales", {"parameters": PARAMS, **creds(secret)})
    bad = embed_run("sales", {"parameters": PARAMS, **creds(secret + "x")})
    forbidden = embed_run("sales", {"parameters": {"p_from": "x"}, **creds(secret + "y")})
    for resp in (ok, bad, forbidden):
        assert secret.encode() not in resp.content and secret.encode() not in str(resp.headers).encode()


# --- parameter defaults -------------------------------------------------------


def test_a_parameter_the_embed_leaves_out_takes_its_default(report, erp, auth_headers):
    """The ticket pins exactly the parameters the embedder sent; a filter it didn't send is
    filled from the report's own default, after the ticket has been checked."""
    definitions = [dict(d) for d in DEFINITIONS]
    definitions[2]["default_value"] = "H.E"
    cfg = client.put(
        f"/api/v1/reports/{report}/data-config", json={"parameters": definitions, "data_source": DATA_SOURCE}, headers=auth_headers
    )
    assert cfg.status_code == 200, cfg.text

    params = {"p_from": "2026-08-01", "p_to": "2026-08-31"}
    resp = embed_run("sales", {"parameters": params, "ticket": ticket(params), "format": "docx"})
    assert resp.status_code == 200, resp.text
    assert _text(resp.content) == "Sales 2026-08-01 to 2026-08-31: 1200 at Phnom Penh, signed H.E"

    # Sent as an empty string it stays empty -- the embedder said "none".
    blank = {**params, "p_signed": ""}
    resp = embed_run("sales", {"parameters": blank, "ticket": ticket(blank), "format": "docx"})
    assert _text(resp.content) == "Sales 2026-08-01 to 2026-08-31: 1200 at Phnom Penh, signed "
