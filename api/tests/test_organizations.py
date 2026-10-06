from fastapi.testclient import TestClient

from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def test_root_org_exists_by_default(auth_headers):
    resp = client.get("/api/v1/organizations", headers=auth_headers)
    assert resp.status_code == 200
    ids = [o["id"] for o in resp.json()]
    assert ROOT_ORG_ID in ids


def test_list_organizations_requires_auth():
    resp = client.get("/api/v1/organizations")
    assert resp.status_code == 401


def test_create_organization_requires_auth():
    resp = client.post("/api/v1/organizations", json={"id": "acme", "name": "Acme"})
    assert resp.status_code == 401


def test_create_organization_with_break_glass(auth_headers):
    resp = client.post("/api/v1/organizations", json={"id": "acme", "name": "Acme Corp"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "acme"
    assert body["name"] == "Acme Corp"


def test_create_organization_seeds_standard_roles(auth_headers):
    client.post("/api/v1/organizations", json={"id": "acme2", "name": "Acme2"}, headers=auth_headers)
    resp = client.get("/api/v1/roles", params={"org_id": "acme2"}, headers=auth_headers)
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()}
    assert "ROLE_ORG_ADMIN" in names
    assert "ROLE_REPORT_VIEWER" in names


def test_create_organization_duplicate_id_rejected(auth_headers):
    client.post("/api/v1/organizations", json={"id": "dupe", "name": "First"}, headers=auth_headers)
    resp = client.post("/api/v1/organizations", json={"id": "dupe", "name": "Second"}, headers=auth_headers)
    assert resp.status_code == 409


def test_get_organization_not_found(auth_headers):
    resp = client.get("/api/v1/organizations/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404
