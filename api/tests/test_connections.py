"""Connections: a named base URL (+ headers + authentication) that reports fetch
their data and choice lists through -- so an API that moves is one edit, not
one per report. Management routes (routers/connections.py), the resolution a
run does (app/connections.py), and the JSONPath-mapped choice list that uses
one (app/report_data.py)."""
from dataclasses import dataclass, field
from io import BytesIO

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import connections, db, report_data, report_store
from app.main import app
from app.rbac import ROOT_ORG_ID, create_organization

http = TestClient(app)

BASE = "http://partner.test:8188"


# --- helpers ----------------------------------------------------------------


def _create(who, name="partner-api", base_url=BASE, expect=200, org_id=None, **config):
    """`who` is the caller's auth header; `config` is the connection's own settings (headers, auth)."""
    body = {"name": name, "config": {"base_url": base_url, **config}}
    if org_id:
        body["org_id"] = org_id
    resp = http.post("/api/v1/connections", json=body, headers=who)
    assert resp.status_code == expect, resp.text
    return resp.json()


def _put(who, connection_id, expect=200, description=None, **config):
    resp = http.put(
        f"/api/v1/connections/{connection_id}",
        json={"description": description, "config": {"base_url": BASE, **config}},
        headers=who,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _docx(text="{{ total }} {{ branch_name }}") -> bytes:
    doc = Document()
    doc.add_paragraph(text)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _docx_text(content: bytes) -> str:
    return "\n".join(p.text for p in Document(BytesIO(content)).paragraphs).replace("​", "")


def _register(headers, name="Sales") -> str:
    resp = http.post(
        "/api/v1/reports",
        files={"file": ("t.docx", _docx(), "application/octet-stream")},
        data={"name": name},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


def _configure(headers, report_id, parameters, data_source, expect=200):
    resp = http.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": parameters, "data_source": data_source},
        headers=headers,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _run(headers, report_id, parameters):
    return http.post(f"/api/v1/reports/{report_id}/run", json={"parameters": parameters, "format": "docx"}, headers=headers)


def _audit_actions() -> list[str]:
    with db.SessionLocal() as session:
        return [row.action for row in session.scalars(select(db.AuditEvent).order_by(db.AuditEvent.id))]


@dataclass
class FakeUpstream:
    """Stands in for every remote API: records the requests the server makes."""

    calls: list = field(default_factory=list)
    respond: object = None

    def __post_init__(self):
        self.respond = lambda request: httpx.Response(200, json={"branch_name": "Phnom Penh", "total": "42"})


@pytest.fixture
def upstream(monkeypatch) -> FakeUpstream:
    fake = FakeUpstream()

    def factory():
        def handler(request):
            fake.calls.append(request)
            return fake.respond(request)

        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(report_data, "_make_client", factory)
    return fake


# --- managing connections -----------------------------------------------------


def test_create_list_and_get_a_connection(auth_headers):
    created = _create(
        auth_headers,
        headers={"X-Client-Id": "aksor"},
        auth={"type": "bearer", "token_env": "PARTNER_API_KEY"},
    )
    assert created["name"] == "partner-api" and created["kind"] == "rest" and created["org_id"] == ROOT_ORG_ID
    assert created["config"] == {
        "base_url": BASE,
        "headers": {"X-Client-Id": "aksor"},
        "auth": {
            "type": "bearer",
            "username": None,
            "password_env": None,
            "token_env": "PARTNER_API_KEY",
            "password_secret": None,
            "token_secret": None,
        },
    }
    assert created["reports"] == []

    listed = http.get("/api/v1/connections", headers=auth_headers).json()
    assert [(c["name"], c["base_url"], c["auth_type"], c["report_count"]) for c in listed] == [("partner-api", BASE, "bearer", 0)]
    # The list is what report authors see: header *names* only, never values.
    assert listed[0]["header_names"] == ["X-Client-Id"]
    assert "aksor" not in http.get("/api/v1/connections", headers=auth_headers).text

    assert http.get(f"/api/v1/connections/{created['id']}", headers=auth_headers).json()["config"]["headers"] == {"X-Client-Id": "aksor"}


def test_a_trailing_slash_and_stray_spaces_are_tidied(auth_headers):
    created = _create(auth_headers, base_url=f"  {BASE}/api/  ")
    assert created["config"]["base_url"] == f"{BASE}/api"


@pytest.mark.parametrize(
    "name, base_url, message",
    [
        ("PARTNER", BASE, "invalid"),
        ("a", BASE, "invalid"),
        ("has space", BASE, "invalid"),
        ("partner-api", "", "base URL"),
        ("partner-api", "partner.test:8188", "http:// or https://"),
        ("partner-api", "ftp://partner.test", "http:// or https://"),
        ("partner-api", f"{BASE}/api?x=1", "query string"),
        ("partner-api", f"{BASE}/api#top", "query string"),
        ("partner-api", "http://{{ host }}/api", "fixed text"),
        ("partner-api", "http://user:secret@partner.test", "username or password"),
    ],
)
def test_invalid_connections_are_a_readable_400(auth_headers, name, base_url, message):
    detail = _create(auth_headers, name=name, base_url=base_url, expect=400)["detail"]
    assert message in detail


def test_connection_headers_and_auth_follow_the_same_rules_as_a_data_source(auth_headers):
    assert "Host" in _create(auth_headers, headers={"Host": "evil.test"}, expect=400)["detail"]
    assert "environment variable" in _create(auth_headers, auth={"type": "bearer", "token_env": "not valid"}, expect=400)["detail"]
    assert "Authorization" in _create(
        auth_headers, headers={"Authorization": "x"}, auth={"type": "bearer", "token_env": "K"}, expect=400
    )["detail"]


def test_names_are_unique_within_an_organization(auth_headers):
    _create(auth_headers)
    assert "already exists" in _create(auth_headers, expect=409)["detail"]


def test_update_replaces_the_settings_but_not_the_name(auth_headers):
    created = _create(auth_headers, headers={"X-A": "1"})
    updated = _put(auth_headers, created["id"], description="Tax system", base_url="http://prod.test", headers={"X-B": "2"})
    assert updated["name"] == "partner-api" and updated["description"] == "Tax system"
    assert updated["config"]["base_url"] == "http://prod.test" and updated["config"]["headers"] == {"X-B": "2"}
    assert {"connection.create", "connection.update"} <= set(_audit_actions())
    assert _put(auth_headers, created["id"], base_url="nonsense", expect=400)


def test_an_unchanged_update_is_not_an_audit_row(auth_headers):
    created = _create(auth_headers)
    _put(auth_headers, created["id"])
    assert _audit_actions().count("connection.update") == 0


def test_permissions_report_authors_may_list_but_only_connection_managers_write(auth_headers, make_local_user):
    created = _create(auth_headers)
    _, author = make_local_user("author", "pw12345", role_names=("ROLE_REPORT_ADMIN",))
    _, plain = make_local_user("plain", "pw12345", role_names=("ROLE_USER",))
    _, org_admin = make_local_user("orgadmin", "pw12345", role_names=("ROLE_ORG_ADMIN",))

    assert http.get("/api/v1/connections", headers=author).status_code == 200
    assert http.get("/api/v1/connections", headers=plain).status_code == 403
    assert http.get("/api/v1/connections").status_code == 401

    for method, path, kwargs in (
        ("post", "/api/v1/connections", {"json": {"name": "x-api", "config": {"base_url": BASE}}}),
        ("get", f"/api/v1/connections/{created['id']}", {}),
        ("put", f"/api/v1/connections/{created['id']}", {"json": {"config": {"base_url": BASE}}}),
        ("delete", f"/api/v1/connections/{created['id']}", {}),
    ):
        assert getattr(http, method)(path, headers=author, **kwargs).status_code == 403, (method, path)

    assert http.post("/api/v1/connections", json={"name": "erp", "config": {"base_url": BASE}}, headers=org_admin).status_code == 200


def test_connections_are_invisible_across_organizations(auth_headers, make_local_user):
    with db.SessionLocal() as session:
        create_organization(session, "acme", "Acme")
        session.commit()
    mine = _create(auth_headers)
    _, acme_admin = make_local_user("acme_admin", "pw12345", role_names=("ROLE_ORG_ADMIN",), org_id="acme")

    assert http.get("/api/v1/connections", headers=acme_admin).json() == []
    assert http.get(f"/api/v1/connections/{mine['id']}", headers=acme_admin).status_code == 404
    assert http.delete(f"/api/v1/connections/{mine['id']}", headers=acme_admin).status_code == 404
    assert http.post(
        "/api/v1/connections", json={"org_id": ROOT_ORG_ID, "name": "sneaky", "config": {"base_url": BASE}}, headers=acme_admin
    ).status_code == 404

    # ...and the same name in another organization is a different connection.
    own = http.post("/api/v1/connections", json={"name": "partner-api", "config": {"base_url": "http://acme.test"}}, headers=acme_admin)
    assert own.status_code == 200 and own.json()["org_id"] == "acme"


# --- pointing reports at a connection -----------------------------------------


def test_a_data_source_can_name_a_connection_and_give_just_a_path(auth_headers):
    _create(auth_headers)
    report_id = _register(auth_headers)
    saved = _configure(
        auth_headers, report_id, [{"name": "q"}],
        {"connection": "partner-api", "url": "/api/external/x?q={{ q }}", "headers": {"X-Extra": "1"}},
    )
    assert saved["data_source"]["connection"] == "partner-api"
    assert saved["data_source"]["url"] == "/api/external/x?q={{ q }}"
    assert saved["data_source"]["type"] == "rest"


@pytest.mark.parametrize(
    "source, message",
    [
        ({"connection": "nope", "url": "/x"}, "doesn't exist"),
        ({"connection": "partner-api", "url": "x/y"}, "must start with /"),
        ({"connection": "partner-api", "url": "http://evil.test/x"}, "must start with /"),
        ({"connection": "partner-api", "url": "/x", "auth": {"type": "bearer", "token_env": "K"}}, "comes from the connection"),
        ({"connection": "partner-api", "url": "/x?q={{ typo }}"}, "{{ typo }}"),
        ({"connection": "Bad Name", "url": "/x"}, "isn't a valid connection name"),
    ],
)
def test_a_data_source_with_a_connection_is_validated(auth_headers, source, message):
    _create(auth_headers)
    report_id = _register(auth_headers)
    assert message in _configure(auth_headers, report_id, [{"name": "q"}], source, expect=400)["detail"]


def test_unknown_source_types_are_refused(auth_headers):
    report_id = _register(auth_headers)
    resp = http.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": [], "data_source": {"type": "soap", "url": "http://x/y"}},
        headers=auth_headers,
    )
    assert resp.status_code == 422 and "rest" in resp.text


def test_a_source_with_no_connection_still_needs_a_full_url(auth_headers):
    report_id = _register(auth_headers)
    assert "http:// or https://" in _configure(auth_headers, report_id, [], {"url": "/api/x"}, expect=400)["detail"]
    saved = _configure(auth_headers, report_id, [], {"url": "http://raw.test/x"})
    assert saved["data_source"]["connection"] is None


def test_a_report_cannot_use_another_organizations_connection(auth_headers, make_local_user):
    with db.SessionLocal() as session:
        create_organization(session, "acme", "Acme")
        session.commit()
    _create(auth_headers)  # root's "partner-api"
    foreign = report_store.create_report(name="Foreign", content=_docx(), template_ext="docx", org_id="acme")["report_id"]
    assert "doesn't exist" in _configure(auth_headers, foreign, [], {"connection": "partner-api", "url": "/x"}, expect=400)["detail"]


# --- running through a connection -------------------------------------------


def test_a_run_goes_to_the_connections_base_url_with_its_headers_and_credentials(auth_headers, upstream, monkeypatch):
    monkeypatch.setenv("PARTNER_API_KEY", "s3cret")
    _create(auth_headers, headers={"X-Client-Id": "aksor", "X-Region": "kh"}, auth={"type": "bearer", "token_env": "PARTNER_API_KEY"})
    report_id = _register(auth_headers)
    _configure(
        auth_headers, report_id, [{"name": "q"}],
        # A report's own header wins over the connection's, whatever the letter case.
        {"connection": "partner-api", "url": "/api/external/x?q={{ q }}", "headers": {"x-region": "sg", "X-Trace": "on"}},
    )

    resp = _run(auth_headers, report_id, {"q": "a b&c"})
    assert resp.status_code == 200, resp.text
    (call,) = upstream.calls
    assert str(call.url) == f"{BASE}/api/external/x?q=a%20b%26c"
    assert call.headers["x-client-id"] == "aksor"
    assert call.headers["x-region"] == "sg"
    assert call.headers["x-trace"] == "on"
    assert call.headers["authorization"] == "Bearer s3cret"
    assert "Phnom Penh" in _docx_text(resp.content)


def test_basic_auth_comes_from_the_connection_too(auth_headers, upstream, monkeypatch):
    monkeypatch.setenv("ERP_PW", "pw")
    _create(auth_headers, auth={"type": "basic", "username": "svc", "password_env": "ERP_PW"})
    report_id = _register(auth_headers)
    _configure(auth_headers, report_id, [], {"connection": "partner-api", "url": "/x"})
    assert _run(auth_headers, report_id, {}).status_code == 200
    assert upstream.calls[0].headers["authorization"].startswith("Basic ")


def test_a_path_may_be_empty_or_just_a_query(auth_headers, upstream):
    _create(auth_headers, base_url=f"{BASE}/api")
    root = _register(auth_headers, "Root")
    _configure(auth_headers, root, [], {"connection": "partner-api", "url": ""})
    querying = _register(auth_headers, "Query")
    _configure(auth_headers, querying, [], {"connection": "partner-api", "url": "?all=1"})
    assert _run(auth_headers, root, {}).status_code == 200 and _run(auth_headers, querying, {}).status_code == 200
    assert [str(c.url) for c in upstream.calls] == [f"{BASE}/api", f"{BASE}/api?all=1"]


def test_changing_the_connection_moves_every_report_that_uses_it(auth_headers, upstream):
    created = _create(auth_headers)
    reports = [_register(auth_headers, f"R{i}") for i in range(3)]
    for report_id in reports:
        _configure(auth_headers, report_id, [], {"connection": "partner-api", "url": f"/api/{report_id}"})
    assert http.get("/api/v1/connections", headers=auth_headers).json()[0]["report_count"] == 3

    _put(auth_headers, created["id"], base_url="https://prod.example.gov.kh")
    for report_id in reports:
        assert _run(auth_headers, report_id, {}).status_code == 200
    assert [str(c.url) for c in upstream.calls] == [f"https://prod.example.gov.kh/api/{r}" for r in reports]


def test_a_connection_deleted_out_from_under_a_report_is_a_readable_502(auth_headers, upstream):
    created = _create(auth_headers)
    report_id = _register(auth_headers)
    _configure(auth_headers, report_id, [], {"connection": "partner-api", "url": "/x"})
    with db.SessionLocal() as session:  # bypasses the in-use guard, as a manual DB edit would
        session.delete(session.get(db.DataConnection, created["id"]))
        session.commit()
    resp = _run(auth_headers, report_id, {})
    assert resp.status_code == 502 and "no longer exists" in resp.json()["detail"]
    assert upstream.calls == []


def test_a_missing_credential_is_still_a_502_that_does_not_name_the_variable(auth_headers, upstream, monkeypatch):
    monkeypatch.delenv("PARTNER_API_KEY", raising=False)
    _create(auth_headers, auth={"type": "bearer", "token_env": "PARTNER_API_KEY"})
    report_id = _register(auth_headers)
    _configure(auth_headers, report_id, [], {"connection": "partner-api", "url": "/x"})
    resp = _run(auth_headers, report_id, {})
    assert resp.status_code == 502 and "PARTNER_API_KEY" not in resp.text


# --- who uses a connection / deleting it -----------------------------------------


def test_a_connection_in_use_cannot_be_deleted_until_nothing_uses_it(auth_headers):
    created = _create(auth_headers)
    with_source = _register(auth_headers, "Uses it for data")
    with_choices = _register(auth_headers, "Uses it for choices")
    _configure(auth_headers, with_source, [], {"connection": "partner-api", "url": "/x"})
    _configure(
        auth_headers, with_choices,
        [{"name": "branch", "options_source": {"connection": "partner-api", "url": "/branches", "value_field": "code"}}],
        None,
    )

    detail = http.get(f"/api/v1/connections/{created['id']}", headers=auth_headers).json()
    assert sorted(r["name"] for r in detail["reports"]) == ["Uses it for choices", "Uses it for data"]

    resp = http.delete(f"/api/v1/connections/{created['id']}", headers=auth_headers)
    assert resp.status_code == 409 and "2 reports" in resp.json()["detail"] and "Uses it for data" in resp.json()["detail"]

    _configure(auth_headers, with_source, [], None)
    _configure(auth_headers, with_choices, [], None)
    assert http.delete(f"/api/v1/connections/{created['id']}", headers=auth_headers).status_code == 204
    assert http.get("/api/v1/connections", headers=auth_headers).json() == []
    assert "connection.delete" in _audit_actions()


# --- choice lists: a connection + JSONPath ------------------------------------------

ENVELOPE = {
    "code": 200,
    "data": [
        {"code": "PP01", "nameEn": "Phnom Penh", "nameKh": "ភ្នំពេញ", "region": {"id": 1}},
        {"code": "SR01", "nameEn": "Siem Reap", "nameKh": "សៀមរាប", "region": {"id": 2}},
    ],
}


def _choice_report(headers, **source):
    report_id = _register(headers)
    _configure(headers, report_id, [{"name": "branch", "options_source": {"connection": "partner-api", "url": "/branches", **source}}], None)
    return report_id


def _form(headers, report_id):
    return http.get(f"/api/v1/reports/{report_id}/run-form", headers=headers)


def test_a_choice_list_reads_its_items_out_of_an_enveloped_response(auth_headers, upstream):
    _create(auth_headers, headers={"X-Client-Id": "aksor"})
    upstream.respond = lambda request: httpx.Response(200, json=ENVELOPE)
    report_id = _choice_report(auth_headers, items_path="$.data[*]", value_field="code", label_field="nameEn")

    form = _form(auth_headers, report_id).json()
    assert form["parameters"][0]["options"] == [{"value": "PP01", "label": "Phnom Penh"}, {"value": "SR01", "label": "Siem Reap"}]
    assert str(upstream.calls[0].url) == f"{BASE}/branches" and upstream.calls[0].headers["x-client-id"] == "aksor"


def test_the_items_path_may_name_the_array_itself(auth_headers, upstream):
    _create(auth_headers)
    upstream.respond = lambda request: httpx.Response(200, json=ENVELOPE)
    report_id = _choice_report(auth_headers, items_path="data", value_field="code")
    assert [o["value"] for o in _form(auth_headers, report_id).json()["parameters"][0]["options"]] == ["PP01", "SR01"]


def test_values_and_labels_may_be_nested_paths_or_templates(auth_headers, upstream):
    _create(auth_headers)
    upstream.respond = lambda request: httpx.Response(200, json=ENVELOPE)
    report_id = _choice_report(auth_headers, items_path="$.data", value_field="region.id", label_field="${code} - ${nameEn} / ${nameKh}")
    options = _form(auth_headers, report_id).json()["parameters"][0]["options"]
    assert options == [
        {"value": "1", "label": "PP01 - Phnom Penh / ភ្នំពេញ"},
        {"value": "2", "label": "SR01 - Siem Reap / សៀមរាប"},
    ]


def test_a_label_that_is_missing_on_an_item_falls_back_to_its_value(auth_headers, upstream):
    _create(auth_headers)
    upstream.respond = lambda request: httpx.Response(200, json=[{"code": "A", "n": "Alpha"}, {"code": "B"}])
    report_id = _choice_report(auth_headers, value_field="code", label_field="n")
    assert _form(auth_headers, report_id).json()["parameters"][0]["options"] == [
        {"value": "A", "label": "Alpha"},
        {"value": "B", "label": None},
    ]


@pytest.mark.parametrize(
    "respond, source",
    [
        (lambda r: httpx.Response(200, json=ENVELOPE), {"value_field": "code"}),  # an object, and no items path
        (lambda r: httpx.Response(200, json=ENVELOPE), {"items_path": "$.data", "value_field": "missing"}),
        (lambda r: httpx.Response(200, json=ENVELOPE), {"items_path": "$.data", "value_field": "region"}),  # an object, not a value
    ],
    ids=["no-items-path", "value-missing-on-items", "value-is-an-object"],
)
def test_a_response_that_does_not_fit_the_paths_is_a_502_naming_the_parameter(auth_headers, upstream, respond, source):
    _create(auth_headers)
    upstream.respond = respond
    report_id = _choice_report(auth_headers, **source)
    resp = _form(auth_headers, report_id)
    assert resp.status_code == 502 and "branch" in resp.json()["detail"]


@pytest.mark.parametrize(
    "source, message",
    [
        ({"items_path": "$..data", "value_field": "code"}, "search everywhere"),
        ({"items_path": "$.data[?(@.a)]", "value_field": "code"}, "Filters"),
        ({"value_field": "code[*]"}, "matches many values"),
        ({"value_field": "code", "label_field": "${nameEn"}, "Unclosed"),
        ({"value_field": ""}, "needs a value"),
    ],
)
def test_bad_paths_are_refused_when_saved(auth_headers, source, message):
    _create(auth_headers)
    report_id = _register(auth_headers)
    detail = _configure(
        auth_headers, report_id,
        [{"name": "branch", "options_source": {"connection": "partner-api", "url": "/branches", **source}}], None, expect=400,
    )["detail"]
    assert message in detail and "branch" in detail


def test_a_choice_list_that_predates_jsonpath_keeps_working(auth_headers, upstream):
    """value_field/label_field used to be plain keys of a top-level array."""
    report_id = _register(auth_headers)
    _configure(
        auth_headers, report_id,
        [{"name": "b", "options_source": {"url": "http://branches.test/x", "value_field": "code", "label_field": "name"}}], None,
    )
    upstream.respond = lambda request: httpx.Response(200, json=[{"code": "PP01", "name": "Phnom Penh"}])
    assert _form(auth_headers, report_id).json()["parameters"][0]["options"] == [{"value": "PP01", "label": "Phnom Penh"}]


# --- previewing a choice list before saving it ------------------------------------------


def _preview(headers, report_id, source):
    return http.post(f"/api/v1/reports/{report_id}/data-config/preview-options", json={"options_source": source}, headers=headers)


def test_preview_shows_the_mapped_choices_of_an_unsaved_source(auth_headers, upstream):
    _create(auth_headers)
    report_id = _register(auth_headers)
    many = {"data": [{"code": f"B{i:02d}", "nameEn": f"Branch {i}"} for i in range(30)]}
    upstream.respond = lambda request: httpx.Response(200, json=many)

    resp = _preview(
        auth_headers, report_id,
        {"connection": "partner-api", "url": "/branches", "items_path": "$.data[*]", "value_field": "code", "label_field": "nameEn"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 30 and len(body["options"]) == 20
    assert body["options"][0] == {"value": "B00", "label": "Branch 0"}
    # Trying it out saves nothing.
    assert http.get(f"/api/v1/reports/{report_id}/data-config", headers=auth_headers).json()["parameters"] == []


def test_preview_reports_problems_the_way_saving_would(auth_headers, upstream):
    _create(auth_headers)
    report_id = _register(auth_headers)
    bad_path = _preview(auth_headers, report_id, {"connection": "partner-api", "url": "/b", "value_field": "a[*]"})
    assert bad_path.status_code == 400 and "matches many values" in bad_path.json()["detail"]
    unknown = _preview(auth_headers, report_id, {"connection": "nope", "url": "/b", "value_field": "a"})
    assert unknown.status_code == 400 and "doesn't exist" in unknown.json()["detail"]

    upstream.respond = lambda request: httpx.Response(500, text="boom")
    failing = _preview(auth_headers, report_id, {"connection": "partner-api", "url": "/b", "value_field": "a"})
    assert failing.status_code == 502 and "HTTP 500" in failing.json()["detail"] and "boom" not in failing.text


def test_preview_needs_manage_and_stays_inside_the_callers_organization(auth_headers, make_local_user, upstream):
    with db.SessionLocal() as session:
        create_organization(session, "acme", "Acme")
        session.commit()
    _create(auth_headers)
    upstream.respond = lambda request: httpx.Response(200, json=[{"code": "A"}])
    mine = _register(auth_headers)
    source = {"connection": "partner-api", "url": "/b", "value_field": "code"}

    _, viewer = make_local_user("viewer", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    assert _preview(viewer, mine, source).status_code == 403

    # A manager of another organization can't borrow this one's connection.
    _, acme_manager = make_local_user("acme_mgr", "pw12345", role_names=("ROLE_REPORT_ADMIN",), org_id="acme")
    assert _preview(acme_manager, mine, source).status_code == 404
    assert upstream.calls == []

    assert _preview(auth_headers, mine, source).status_code == 200


# --- the pieces --------------------------------------------------------------------------


def test_materialize_leaves_a_source_without_a_connection_alone():
    """No connection to fold in, and no auth to resolve -- everything else passes through untouched."""
    source = {"url": "http://x.test/a", "method": "GET", "headers": {"A": "1"}, "auth": None}
    assert connections.materialize(source, ROOT_ORG_ID) == source


def test_materialize_resolves_a_bare_sources_own_credential(monkeypatch):
    """A source with no connection can still name a credential -- an environment
    variable, resolved to a literal the same way a connection's own would be."""
    monkeypatch.setenv("STANDALONE_TOKEN", "abc123")
    source = {"url": "http://x.test/a", "auth": {"type": "bearer", "token_env": "STANDALONE_TOKEN"}}
    assert connections.materialize(source, ROOT_ORG_ID)["auth"] == {"type": "bearer", "token": "abc123"}


def test_names_for_org_lists_only_that_organizations_connections(auth_headers):
    _create(auth_headers, name="one")
    _create(auth_headers, name="two")
    assert connections.names_for_org(ROOT_ORG_ID) == {"one", "two"}
    assert connections.names_for_org(None) == {"one", "two"}  # a report with no org lives in root
    assert connections.names_for_org("elsewhere") == set()
