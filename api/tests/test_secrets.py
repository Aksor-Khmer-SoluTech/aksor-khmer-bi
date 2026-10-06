"""Secrets: named credentials managed in the portal (Admin > Secrets) instead
of an environment variable -- create/rotate/revoke/delete, who may do each,
who refers to one (a report's data source/choice list, or a connection's own
authentication), and how a run resolves one. See app/secrets.py."""
from io import BytesIO

import httpx
import pytest
from cryptography.fernet import Fernet
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db, secret_store
from app.main import app
from app.rbac import ROOT_ORG_ID

http = TestClient(app)

TOKEN = "tok_live_9f8e7d6c5b4a"


def _create(who, name="partner-token", value=TOKEN, expect=200, org_id=None, **extra):
    body = {"name": name, "value": value, **extra}
    if org_id:
        body["org_id"] = org_id
    resp = http.post("/api/v1/secrets", json=body, headers=who)
    assert resp.status_code == expect, resp.text
    return resp.json()


def _row(name="partner-token") -> db.Secret:
    with db.SessionLocal() as session:
        return session.scalars(select(db.Secret).where(db.Secret.name == name)).one()


def _audit_events(secret_id: str) -> list[db.AuditEvent]:
    with db.SessionLocal() as session:
        return list(session.scalars(select(db.AuditEvent).where(db.AuditEvent.entity_id == secret_id)))


def _docx() -> bytes:
    doc = Document()
    doc.add_paragraph("placeholder")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _register(headers) -> str:
    resp = http.post(
        "/api/v1/reports", files={"file": ("t.docx", _docx(), "application/octet-stream")}, data={"name": "Sales"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


def _use_in_report(headers, report_id, name):
    resp = http.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": [], "data_source": {"url": "http://x.test/a", "auth": {"type": "bearer", "token_secret": name}}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


# --- create / list / get ------------------------------------------------------


def test_create_a_secret(auth_headers):
    created = _create(auth_headers, description="PARTNER API token")
    assert created["name"] == "partner-token"
    assert created["description"] == "PARTNER API token"
    assert created["is_active"] is True
    assert created["used_by"] == []
    assert "value" not in created and TOKEN not in str(created)


def test_the_value_is_never_returned_by_any_endpoint(auth_headers):
    created = _create(auth_headers)
    everything = (
        http.get(f"/api/v1/secrets/{created['id']}", headers=auth_headers).text
        + http.get("/api/v1/secrets", headers=auth_headers).text
    )
    assert TOKEN not in everything


def test_the_database_holds_only_ciphertext(auth_headers):
    _create(auth_headers)
    row = _row()
    assert TOKEN not in row.value_encrypted
    assert secret_store.decrypt(row.value_encrypted) == TOKEN


def test_list_hides_org_filter_from_a_non_superuser(auth_headers, make_local_user):
    _create(auth_headers, name="root-one")
    _, headers = make_local_user("connmgr", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    listed = http.get("/api/v1/secrets", headers=headers).json()
    assert [s["name"] for s in listed] == ["root-one"]


def test_names_must_look_like_connection_names(auth_headers):
    for bad in ("AB", "has space", "a"):
        assert _create(auth_headers, name=bad, expect=400)
    # Longer than the field's own max_length is a 422 (schema-level), not a DataConfigError 400.
    assert _create(auth_headers, name="x" * 65, expect=422)


def test_duplicate_name_in_the_same_org_is_refused(auth_headers):
    _create(auth_headers)
    assert _create(auth_headers, expect=409)


def test_same_name_allowed_in_different_orgs(auth_headers):
    http.post("/api/v1/organizations", json={"id": "org2", "name": "Org2"}, headers=auth_headers)
    _create(auth_headers, org_id=ROOT_ORG_ID)
    assert _create(auth_headers, org_id="org2")["org_id"] == "org2"


@pytest.mark.parametrize(
    "value, why",
    [("", "Enter"), ("has space", "no spaces"), ("line\nbreak", "no spaces"), ("ខ្មែរ", "letters, digits"), ("x" * 5000, "too long")],
)
def test_value_shape_is_enforced(auth_headers, value, why):
    resp = _create(auth_headers, value=value, expect=400)
    assert why in resp["detail"]


# --- rotate --------------------------------------------------------------------


def test_rotate_replaces_the_value_without_changing_the_name(auth_headers):
    created = _create(auth_headers)
    rotated = http.post(f"/api/v1/secrets/{created['id']}/rotate", json={"value": "tok_new_999"}, headers=auth_headers)
    assert rotated.status_code == 200
    assert rotated.json()["name"] == created["name"]
    assert secret_store.decrypt(_row().value_encrypted) == "tok_new_999"
    assert "tok_new_999" not in rotated.text


def test_rotate_is_audited_without_the_value(auth_headers):
    created = _create(auth_headers)
    http.post(f"/api/v1/secrets/{created['id']}/rotate", json={"value": "tok_new_999"}, headers=auth_headers)
    events = [e for e in _audit_events(created["id"]) if e.action == "secret.rotate"]
    assert len(events) == 1
    text = repr(vars(events[0]))
    assert TOKEN not in text and "tok_new_999" not in text


def test_rotate_enforces_the_same_value_shape(auth_headers):
    created = _create(auth_headers)
    resp = http.post(f"/api/v1/secrets/{created['id']}/rotate", json={"value": "bad value"}, headers=auth_headers)
    assert resp.status_code == 400


# --- revoke / reactivate --------------------------------------------------------


def test_revoke_deactivates_without_deleting(auth_headers):
    created = _create(auth_headers)
    revoked = http.patch(f"/api/v1/secrets/{created['id']}", json={"is_active": False}, headers=auth_headers)
    assert revoked.status_code == 200 and revoked.json()["is_active"] is False
    assert http.get(f"/api/v1/secrets/{created['id']}", headers=auth_headers).status_code == 200


def test_revoke_then_reactivate_is_audited_both_ways(auth_headers):
    created = _create(auth_headers)
    http.patch(f"/api/v1/secrets/{created['id']}", json={"is_active": False}, headers=auth_headers)
    http.patch(f"/api/v1/secrets/{created['id']}", json={"is_active": True}, headers=auth_headers)
    actions = [e.action for e in _audit_events(created["id"])]
    assert actions == ["secret.create", "secret.revoke", "secret.reactivate"]


def test_editing_description_alone_is_not_a_revoke_event(auth_headers):
    created = _create(auth_headers)
    http.patch(f"/api/v1/secrets/{created['id']}", json={"description": "renamed"}, headers=auth_headers)
    actions = [e.action for e in _audit_events(created["id"])]
    assert "secret.revoke" not in actions and "secret.reactivate" not in actions


# --- used_by / delete -----------------------------------------------------------


def test_used_by_reports_a_reference_from_a_reports_own_data_source(auth_headers):
    created = _create(auth_headers)
    report_id = _register(auth_headers)
    _use_in_report(auth_headers, report_id, created["name"])
    detail = http.get(f"/api/v1/secrets/{created['id']}", headers=auth_headers).json()
    assert detail["used_by_count"] == 1
    assert detail["used_by"][0] == {"kind": "report", "name": "Sales", "report_id": report_id, "code": None, "connection_id": None}


def test_used_by_reports_a_reference_from_a_connections_own_auth(auth_headers):
    created = _create(auth_headers)
    conn = http.post(
        "/api/v1/connections",
        json={"name": "partner-api", "config": {"base_url": "http://x.test", "auth": {"type": "bearer", "token_secret": created["name"]}}},
        headers=auth_headers,
    )
    assert conn.status_code == 200, conn.text
    detail = http.get(f"/api/v1/secrets/{created['id']}", headers=auth_headers).json()
    assert detail["used_by"] == [{"kind": "connection", "name": "partner-api", "report_id": None, "code": None, "connection_id": conn.json()["id"]}]


def test_delete_refused_while_used(auth_headers):
    created = _create(auth_headers)
    report_id = _register(auth_headers)
    _use_in_report(auth_headers, report_id, created["name"])
    resp = http.delete(f"/api/v1/secrets/{created['id']}", headers=auth_headers)
    assert resp.status_code == 409 and "Sales" in resp.json()["detail"]


def test_delete_succeeds_once_unused(auth_headers):
    created = _create(auth_headers)
    assert http.delete(f"/api/v1/secrets/{created['id']}", headers=auth_headers).status_code == 204
    assert http.get(f"/api/v1/secrets/{created['id']}", headers=auth_headers).status_code == 404


def test_delete_is_audited(auth_headers):
    created = _create(auth_headers)
    http.delete(f"/api/v1/secrets/{created['id']}", headers=auth_headers)
    with db.SessionLocal() as session:
        events = list(session.scalars(select(db.AuditEvent).where(db.AuditEvent.entity_id == created["id"], db.AuditEvent.action == "secret.delete")))
    assert len(events) == 1 and events[0].entity_label == "partner-token"


# --- referencing a secret from a report or connection ---------------------------


def test_a_report_can_name_a_secret_directly_with_no_connection(auth_headers, monkeypatch):
    created = _create(auth_headers)
    report_id = _register(auth_headers)
    _use_in_report(auth_headers, report_id, created["name"])

    calls = []

    def factory():
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={})
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    import app.report_data as report_data
    monkeypatch.setattr(report_data, "_make_client", factory)
    resp = http.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {}, "format": "docx"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert calls[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_an_unknown_secret_name_is_refused_at_save_time(auth_headers):
    report_id = _register(auth_headers)
    resp = http.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": [], "data_source": {"url": "http://x.test/a", "auth": {"type": "bearer", "token_secret": "nope"}}},
        headers=auth_headers,
    )
    assert resp.status_code == 400 and "nope" in resp.json()["detail"]


def test_a_revoked_secret_cannot_be_newly_assigned(auth_headers):
    created = _create(auth_headers)
    http.patch(f"/api/v1/secrets/{created['id']}", json={"is_active": False}, headers=auth_headers)
    report_id = _register(auth_headers)
    resp = http.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": [], "data_source": {"url": "http://x.test/a", "auth": {"type": "bearer", "token_secret": created["name"]}}},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_a_revoked_secret_already_referenced_fails_loudly_at_run_time(auth_headers):
    created = _create(auth_headers)
    report_id = _register(auth_headers)
    _use_in_report(auth_headers, report_id, created["name"])
    http.patch(f"/api/v1/secrets/{created['id']}", json={"is_active": False}, headers=auth_headers)

    resp = http.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {}, "format": "docx"}, headers=auth_headers)
    assert resp.status_code == 502
    assert "revoked" in resp.json()["detail"]


def test_cannot_choose_both_an_env_var_and_a_secret(auth_headers):
    created = _create(auth_headers)
    report_id = _register(auth_headers)
    resp = http.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={
            "parameters": [],
            "data_source": {"url": "http://x.test/a", "auth": {"type": "bearer", "token_env": "X", "token_secret": created["name"]}},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400 and "not both" in resp.json()["detail"]


def test_bearer_auth_needs_a_credential_of_some_kind(auth_headers):
    report_id = _register(auth_headers)
    resp = http.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": [], "data_source": {"url": "http://x.test/a", "auth": {"type": "bearer"}}},
        headers=auth_headers,
    )
    assert resp.status_code == 400 and "credential" in resp.json()["detail"]


def test_a_connection_whose_credential_gets_revoked_fails_at_run_time_too(auth_headers):
    """Same failure mode as a bare data source's (test_a_revoked_secret_already_referenced_...),
    reached through a connection instead -- the resolution path is shared (app/connections.py's
    materialize calls the same app/secrets.resolve either way)."""
    created = _create(auth_headers)
    http.post(
        "/api/v1/connections",
        json={"name": "partner-api", "config": {"base_url": "http://x.test", "auth": {"type": "bearer", "token_secret": created["name"]}}},
        headers=auth_headers,
    )
    report_id = _register(auth_headers)
    http.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": [], "data_source": {"connection": "partner-api", "url": "/x"}},
        headers=auth_headers,
    )
    http.patch(f"/api/v1/secrets/{created['id']}", json={"is_active": False}, headers=auth_headers)

    resp = http.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {}, "format": "docx"}, headers=auth_headers)
    assert resp.status_code == 502 and "revoked" in resp.json()["detail"]


def test_connections_list_shows_the_secret_name_to_a_connection_manager(auth_headers):
    created = _create(auth_headers)
    http.post(
        "/api/v1/connections",
        json={"name": "partner-api", "config": {"base_url": "http://x.test", "auth": {"type": "bearer", "token_secret": created["name"]}}},
        headers=auth_headers,
    )
    listed = {c["name"]: c for c in http.get("/api/v1/connections", headers=auth_headers).json()}
    assert listed["partner-api"]["credential"] == "secret"
    assert listed["partner-api"]["secret_name"] == created["name"]


# --- permissions -----------------------------------------------------------------


def test_creating_a_secret_needs_secret_manage(auth_headers, make_local_user):
    _, headers = make_local_user("connmgr", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    # ROLE_ORG_ADMIN holds secret:manage too -- prove a narrower role does not.
    _, narrow = make_local_user("reportmgr", "pw12345", role_names=("ROLE_REPORT_ADMIN",))
    assert _create(headers, name="by-org-admin")
    assert http.post("/api/v1/secrets", json={"name": "x", "value": TOKEN}, headers=narrow).status_code == 403


def test_report_and_connection_managers_may_list_but_not_read_or_write(auth_headers, make_local_user):
    _create(auth_headers)
    _, report_mgr = make_local_user("reportmgr", "pw12345", role_names=("ROLE_REPORT_ADMIN",))
    assert http.get("/api/v1/secrets", headers=report_mgr).status_code == 200
    secret_id = _row().id
    assert http.get(f"/api/v1/secrets/{secret_id}", headers=report_mgr).status_code == 403
    assert http.post(f"/api/v1/secrets/{secret_id}/rotate", json={"value": "x"}, headers=report_mgr).status_code == 403


def test_someone_with_neither_permission_cannot_even_list(auth_headers, make_local_user):
    _create(auth_headers)
    _, headers = make_local_user("plain", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    assert http.get("/api/v1/secrets", headers=headers).status_code == 403


def test_org_admin_cannot_touch_another_orgs_secret(auth_headers, make_local_user):
    http.post("/api/v1/organizations", json={"id": "orgy", "name": "Org Y"}, headers=auth_headers)
    other = _create(auth_headers, org_id="orgy")
    _, headers = make_local_user("orgadmin", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    assert http.get(f"/api/v1/secrets/{other['id']}", headers=headers).status_code == 404


# --- decrypt failure at resolve time ---------------------------------------------


def test_a_credential_that_can_no_longer_be_decrypted_is_a_readable_502(auth_headers, monkeypatch):
    created = _create(auth_headers)
    report_id = _register(auth_headers)
    _use_in_report(auth_headers, report_id, created["name"])

    monkeypatch.setenv(secret_store.KEY_ENV, Fernet.generate_key().decode())
    resp = http.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {}, "format": "docx"}, headers=auth_headers)
    assert resp.status_code == 502
    assert "rotate it" in resp.json()["detail"]
    assert TOKEN not in resp.text
