from sqlalchemy import select
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.rbac import ROOT_ORG_ID, SYSTEM_ADMIN_ROLE_NAME

client = TestClient(app)


def test_list_permissions_catalog(auth_headers):
    resp = client.get("/api/v1/permissions", headers=auth_headers)
    assert resp.status_code == 200
    codes = {p["code"] for p in resp.json()}
    assert "report:manage" in codes
    assert "job:trigger" in codes


def test_list_permissions_requires_auth():
    resp = client.get("/api/v1/permissions")
    assert resp.status_code == 401


def test_list_roles_default_scoped_to_root_org(auth_headers):
    resp = client.get("/api/v1/roles", params={"org_id": ROOT_ORG_ID}, headers=auth_headers)
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()}
    assert names == {"ROLE_ORG_ADMIN", "ROLE_REPORT_ADMIN", "ROLE_REPORT_VIEWER", "ROLE_JOB_OPERATOR", "ROLE_USER"}


def test_get_role_includes_permissions(auth_headers):
    roles = client.get("/api/v1/roles", params={"org_id": ROOT_ORG_ID}, headers=auth_headers).json()
    report_admin = next(r for r in roles if r["name"] == "ROLE_REPORT_ADMIN")
    resp = client.get(f"/api/v1/roles/{report_admin['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert set(resp.json()["permissions"]) == {
        "report:manage",
        "report:render",
        "report:view",
        "folder:manage",
        "protected_terms:manage",
    }


def test_set_role_permissions_replaces_the_set(auth_headers):
    roles = client.get("/api/v1/roles", params={"org_id": ROOT_ORG_ID}, headers=auth_headers).json()
    job_operator = next(r for r in roles if r["name"] == "ROLE_JOB_OPERATOR")
    resp = client.put(
        f"/api/v1/roles/{job_operator['id']}/permissions",
        json={"permissions": ["job:view"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["permissions"] == ["job:view"]


def test_set_role_permissions_rejects_unknown_code(auth_headers):
    roles = client.get("/api/v1/roles", params={"org_id": ROOT_ORG_ID}, headers=auth_headers).json()
    role = roles[0]
    resp = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json={"permissions": ["not:a:real:permission"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_set_role_permissions_requires_role_manage(make_local_user):
    _, headers = make_local_user("noroleperm", "pw12345", role_names=())
    resp = client.put(
        "/api/v1/roles/does-not-matter/permissions", json={"permissions": []}, headers=headers
    )
    assert resp.status_code == 403


def test_root_org_role_list_excludes_the_system_wide_admin_role(auth_headers):
    # ROLE_ADMINISTRATOR has org_id=None (cross-org), so an org-scoped
    # role list should never include it.
    names = {r["name"] for r in client.get("/api/v1/roles", params={"org_id": ROOT_ORG_ID}, headers=auth_headers).json()}
    assert "ROLE_ADMINISTRATOR" not in names


def test_cannot_edit_system_admin_role_permissions(auth_headers):
    with db.SessionLocal() as session:
        admin_role = session.execute(
            select(db.Role).where(db.Role.org_id.is_(None), db.Role.name == SYSTEM_ADMIN_ROLE_NAME)
        ).scalar_one()
        admin_role_id = admin_role.id

    resp = client.put(f"/api/v1/roles/{admin_role_id}/permissions", json={"permissions": []}, headers=auth_headers)
    assert resp.status_code == 400


def test_create_role(auth_headers):
    resp = client.post(
        "/api/v1/roles",
        json={"org_id": ROOT_ORG_ID, "name": "ROLE_CUSTOM_AUDITOR", "description": "Read-only audit access"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "ROLE_CUSTOM_AUDITOR"
    assert body["org_id"] == ROOT_ORG_ID
    assert body["is_system"] is False
    assert body["permissions"] == []


def test_create_role_rejects_duplicate_name_in_same_org(auth_headers):
    resp = client.post(
        "/api/v1/roles", json={"org_id": ROOT_ORG_ID, "name": "ROLE_ORG_ADMIN"}, headers=auth_headers
    )
    assert resp.status_code == 409


def test_create_role_requires_role_manage(make_local_user):
    _, headers = make_local_user("norolecreate", "pw12345", role_names=())
    resp = client.post("/api/v1/roles", json={"org_id": ROOT_ORG_ID, "name": "ROLE_X"}, headers=headers)
    assert resp.status_code == 403


def test_delete_custom_role(auth_headers):
    created = client.post(
        "/api/v1/roles", json={"org_id": ROOT_ORG_ID, "name": "ROLE_TO_DELETE"}, headers=auth_headers
    ).json()
    resp = client.delete(f"/api/v1/roles/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get(f"/api/v1/roles/{created['id']}", headers=auth_headers).status_code == 404


def test_cannot_delete_system_role(auth_headers):
    roles = client.get("/api/v1/roles", params={"org_id": ROOT_ORG_ID}, headers=auth_headers).json()
    role = next(r for r in roles if r["name"] == "ROLE_USER")
    resp = client.delete(f"/api/v1/roles/{role['id']}", headers=auth_headers)
    assert resp.status_code == 400


def test_cannot_delete_role_with_active_assignments(auth_headers, make_local_user):
    created = client.post(
        "/api/v1/roles", json={"org_id": ROOT_ORG_ID, "name": "ROLE_IN_USE"}, headers=auth_headers
    ).json()
    user_id, _ = make_local_user("roleassignee", "pw12345", role_names=())
    with db.SessionLocal() as session:
        session.add(
            db.UserRoleAssignment(user_id=user_id, role_id=created["id"], granted_at="now", is_active=True)
        )
        session.commit()

    resp = client.delete(f"/api/v1/roles/{created['id']}", headers=auth_headers)
    assert resp.status_code == 400
