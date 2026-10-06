"""API clients: management endpoints (routers/clients.py) and the helpers behind them (app/clients.py)."""
import json
from datetime import datetime, timezone
from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clients as client_auth
from app import db, report_store
from app.main import app
from app.rbac import ROOT_ORG_ID, seed_org_roles

http = TestClient(app)


def _docx() -> bytes:
    buf = BytesIO()
    doc = Document()
    doc.add_paragraph("{{ total }}")
    doc.save(buf)
    return buf.getvalue()


def _report(auth_headers, name="Sales", code=None) -> str:
    resp = http.post(
        "/api/v1/reports",
        files={"file": ("t.docx", _docx(), "application/octet-stream")},
        data={"name": name, **({"code": code} if code else {})},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


def _client(auth_headers, client_id="partner-web", report_ids=(), **extra) -> dict:
    resp = http.post(
        "/api/v1/clients",
        json={"client_id": client_id, "name": "Partner web", "report_ids": list(report_ids), **extra},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _other_org(org_id="acme") -> str:
    with db.SessionLocal() as session:
        org = db.Organization(id=org_id, name=org_id.title(), is_active=True, created_at=datetime.now(timezone.utc).isoformat())
        session.add(org)
        session.flush()
        seed_org_roles(session, org)
        session.commit()
    return org_id


def _audit_actions() -> list[str]:
    with db.SessionLocal() as session:
        return [row.action for row in session.scalars(select(db.AuditEvent).order_by(db.AuditEvent.id))]


def test_creating_a_client_returns_the_secret_once_and_stores_only_its_hash(auth_headers):
    report_id = _report(auth_headers)
    created = _client(auth_headers, report_ids=[report_id])

    secret = created["secret"]
    assert secret.startswith("aksor_cs_") and len(secret) > 40
    out = created["client"]
    assert out["client_id"] == "partner-web" and out["is_active"] is True
    assert out["secret_prefix"] == secret[: len("aksor_cs_") + 4]
    assert [r["report_id"] for r in out["reports"]] == [report_id]

    # Nothing afterwards -- list, get -- can show it again, or the hash.
    for body in (
        http.get("/api/v1/clients", headers=auth_headers).text,
        http.get(f"/api/v1/clients/{out['id']}", headers=auth_headers).text,
    ):
        assert secret not in body and "secret_hash" not in body

    with db.SessionLocal() as session:
        row = session.get(db.ApiClient, out["id"])
        assert row.secret_hash != secret and secret not in row.secret_hash
        assert row.secret_hash == client_auth.hash_secret(secret)


def test_the_secret_is_never_written_to_the_audit_trail(auth_headers):
    created = _client(auth_headers)
    http.post(f"/api/v1/clients/{created['client']['id']}/rotate-secret", headers=auth_headers)
    with db.SessionLocal() as session:
        everything = json.dumps([(r.summary, r.details, r.changes) for r in session.scalars(select(db.AuditEvent))], default=str)
    assert created["secret"] not in everything and "aksor_cs_" not in everything


@pytest.mark.parametrize("bad", ["Upper", "has space", "-lead", "trail-", "a--b", "ab", "x" * 65])
def test_a_client_id_must_be_a_lowercase_slug(auth_headers, bad):
    resp = http.post("/api/v1/clients", json={"client_id": bad, "name": "X"}, headers=auth_headers)
    assert resp.status_code == 422


def test_a_client_id_is_unique_across_organizations(auth_headers):
    _client(auth_headers, "partner-web")
    acme = _other_org()
    resp = http.post("/api/v1/clients", json={"client_id": "partner-web", "name": "Other", "org_id": acme}, headers=auth_headers)
    assert resp.status_code == 409


def test_only_reports_that_exist_in_the_clients_organization_can_be_granted(auth_headers):
    resp = http.post("/api/v1/clients", json={"client_id": "c-one", "name": "X", "report_ids": ["nope"]}, headers=auth_headers)
    assert resp.status_code == 400 and "Unknown report" in resp.json()["detail"]

    root_report = _report(auth_headers)
    acme = _other_org()
    resp = http.post("/api/v1/clients", json={"client_id": "c-two", "name": "X", "org_id": acme, "report_ids": [root_report]}, headers=auth_headers)
    assert resp.status_code == 400 and "another organization" in resp.json()["detail"]
    assert http.get("/api/v1/clients", headers=auth_headers).json() == []  # nothing half-created


def test_managing_clients_needs_the_client_manage_permission(auth_headers, make_local_user):
    _, viewer = make_local_user("report.admin", "pw-report-admin-1", ("ROLE_REPORT_ADMIN",))
    assert http.get("/api/v1/clients", headers=viewer).status_code == 403
    assert http.post("/api/v1/clients", json={"client_id": "abc", "name": "X"}, headers=viewer).status_code == 403

    _, org_admin = make_local_user("org.admin", "pw-org-admin-1", ("ROLE_ORG_ADMIN",))
    assert http.get("/api/v1/clients", headers=org_admin).status_code == 200

    assert http.get("/api/v1/clients").status_code == 401


def test_an_org_admin_only_sees_and_touches_their_own_organizations_clients(auth_headers, make_local_user):
    mine = _client(auth_headers, "root-client")["client"]
    acme = _other_org()
    theirs = _client(auth_headers, "acme-client", org_id=acme)["client"]
    _, acme_admin = make_local_user("acme.admin", "pw-acme-admin-1", ("ROLE_ORG_ADMIN",), org_id=acme)

    listed = http.get("/api/v1/clients", headers=acme_admin).json()
    assert [c["client_id"] for c in listed] == ["acme-client"]
    for method, path in (("get", ""), ("patch", ""), ("post", "/rotate-secret"), ("delete", "")):
        resp = getattr(http, method)(f"/api/v1/clients/{mine['id']}{path}", headers=acme_admin, **({"json": {}} if method == "patch" else {}))
        assert resp.status_code == 404, (method, path)
    assert http.get(f"/api/v1/clients/{theirs['id']}", headers=acme_admin).status_code == 200


def test_rename_disable_and_enable(auth_headers):
    out = _client(auth_headers)["client"]
    path = f"/api/v1/clients/{out['id']}"

    renamed = http.patch(path, json={"name": "New name", "description": "for the web"}, headers=auth_headers).json()
    assert renamed["name"] == "New name" and renamed["description"] == "for the web"

    assert http.patch(path, json={"is_active": False}, headers=auth_headers).json()["is_active"] is False
    assert http.patch(path, json={"is_active": True}, headers=auth_headers).json()["is_active"] is True
    # An unchanged value is not a change (and not an audit row).
    http.patch(path, json={"is_active": True}, headers=auth_headers)
    assert _audit_actions().count("client.enable") == 1
    assert {"client.create", "client.update", "client.disable", "client.enable"} <= set(_audit_actions())


def test_replacing_the_granted_reports(auth_headers):
    a, b = _report(auth_headers, "A"), _report(auth_headers, "B")
    out = _client(auth_headers, report_ids=[a])["client"]
    path = f"/api/v1/clients/{out['id']}/reports"

    both = http.put(path, json={"report_ids": [a, b, b]}, headers=auth_headers).json()
    assert sorted(r["report_id"] for r in both["reports"]) == sorted([a, b])

    only_b = http.put(path, json={"report_ids": [b]}, headers=auth_headers).json()
    assert [r["report_id"] for r in only_b["reports"]] == [b]
    assert http.put(path, json={"report_ids": []}, headers=auth_headers).json()["reports"] == []
    assert http.put(path, json={"report_ids": ["nope"]}, headers=auth_headers).status_code == 400
    assert "client.reports_update" in _audit_actions()


def test_rotating_the_secret_kills_the_old_one_at_once(auth_headers):
    created = _client(auth_headers)
    old = created["secret"]
    assert client_auth.authenticate("partner-web", old) is not None

    rotated = http.post(f"/api/v1/clients/{created['client']['id']}/rotate-secret", headers=auth_headers).json()
    assert rotated["secret"] != old and rotated["client"]["secret_rotated_at"]
    assert client_auth.authenticate("partner-web", old) is None
    assert client_auth.authenticate("partner-web", rotated["secret"]) is not None


def test_authenticate_refuses_unknown_wrong_and_disabled(auth_headers):
    created = _client(auth_headers)
    secret = created["secret"]
    assert client_auth.authenticate("partner-web", secret).client_id == "partner-web"
    assert client_auth.authenticate("nobody", secret) is None
    assert client_auth.authenticate("partner-web", secret + "x") is None
    assert client_auth.authenticate("partner-web", "") is None

    http.patch(f"/api/v1/clients/{created['client']['id']}", json={"is_active": False}, headers=auth_headers)
    assert client_auth.authenticate("partner-web", secret) is None


def test_deleting_a_client_removes_it_and_its_grants(auth_headers):
    report_id = _report(auth_headers)
    out = _client(auth_headers, report_ids=[report_id])["client"]
    assert http.delete(f"/api/v1/clients/{out['id']}", headers=auth_headers).status_code == 204
    assert http.get(f"/api/v1/clients/{out['id']}", headers=auth_headers).status_code == 404
    with db.SessionLocal() as session:
        assert session.scalars(select(db.ApiClientReport)).all() == []
    assert "client.delete" in _audit_actions()


def test_deleting_a_report_drops_the_grants_that_named_it(auth_headers):
    report_id = _report(auth_headers)
    out = _client(auth_headers, report_ids=[report_id])["client"]
    report_store.delete_report(report_id)
    assert http.get(f"/api/v1/clients/{out['id']}", headers=auth_headers).json()["reports"] == []
    with db.SessionLocal() as session:
        assert session.scalars(select(db.ApiClientReport)).all() == []


def test_the_permission_is_in_the_catalog_and_the_admin_roles(auth_headers):
    codes = {p["code"] for p in http.get("/api/v1/permissions", headers=auth_headers).json()}
    assert "client:manage" in codes
    roles = {r["name"]: r for r in http.get("/api/v1/roles", params={"org_id": ROOT_ORG_ID}, headers=auth_headers).json()}
    assert "client:manage" in roles["ROLE_ORG_ADMIN"]["permissions"]
    # Managing templates must not include handing out access to their data.
    assert "client:manage" not in roles["ROLE_REPORT_ADMIN"]["permissions"]
