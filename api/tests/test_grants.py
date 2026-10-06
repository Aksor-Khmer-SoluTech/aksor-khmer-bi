from datetime import datetime, timedelta, timezone
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def _future(days=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past(days=1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _role_id(name: str, org_id: str = ROOT_ORG_ID) -> str:
    with db.SessionLocal() as session:
        return session.execute(select(db.Role.id).where(db.Role.org_id == org_id, db.Role.name == name)).scalar_one()


def _register_report(auth_headers, name="Grant Test Report") -> str:
    doc = Document()
    doc.add_paragraph("Hello {{ name }}")
    buf = BytesIO()
    doc.save(buf)
    resp = client.post(
        "/api/v1/reports",
        files={"file": ("t.docx", buf.getvalue(), "application/octet-stream")},
        data={"name": name},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


# --- role grants ---------------------------------------------------------


def test_grant_role_then_user_gains_permission(auth_headers, make_local_user):
    user_id, headers = make_local_user("granted_user", "pw12345", role_names=())
    resp = client.post(
        "/api/v1/grants/roles",
        json={"user_id": user_id, "role_id": _role_id("ROLE_REPORT_VIEWER")},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    perms = client.get(f"/api/v1/users/{user_id}/permissions", headers=auth_headers).json()["permissions"]
    assert "report:view" in perms


def test_expired_role_grant_does_not_grant_permission(auth_headers, make_local_user):
    user_id, _headers = make_local_user("expired_grant_user", "pw12345", role_names=())
    client.post(
        "/api/v1/grants/roles",
        json={"user_id": user_id, "role_id": _role_id("ROLE_REPORT_VIEWER"), "expires_at": _past()},
        headers=auth_headers,
    )
    perms = client.get(f"/api/v1/users/{user_id}/permissions", headers=auth_headers).json()["permissions"]
    assert perms == []


def test_unexpired_role_grant_still_grants_permission(auth_headers, make_local_user):
    user_id, _headers = make_local_user("future_expiry_user", "pw12345", role_names=())
    client.post(
        "/api/v1/grants/roles",
        json={"user_id": user_id, "role_id": _role_id("ROLE_REPORT_VIEWER"), "expires_at": _future()},
        headers=auth_headers,
    )
    perms = client.get(f"/api/v1/users/{user_id}/permissions", headers=auth_headers).json()["permissions"]
    assert "report:view" in perms


def test_revoke_role_grant_removes_permission(auth_headers, make_local_user):
    user_id, _headers = make_local_user("revoke_user", "pw12345", role_names=())
    grant = client.post(
        "/api/v1/grants/roles",
        json={"user_id": user_id, "role_id": _role_id("ROLE_REPORT_VIEWER")},
        headers=auth_headers,
    ).json()

    resp = client.delete(f"/api/v1/grants/roles/{grant['id']}", headers=auth_headers)
    assert resp.status_code == 204

    perms = client.get(f"/api/v1/users/{user_id}/permissions", headers=auth_headers).json()["permissions"]
    assert perms == []


def test_only_superuser_can_grant_system_admin_role(auth_headers, make_local_user):
    from app.rbac import SYSTEM_ADMIN_ROLE_NAME

    _grantor_id, grantor_headers = make_local_user("org_admin_grantor", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    target_id, _ = make_local_user("target_user", "pw12345", role_names=())

    with db.SessionLocal() as session:
        admin_role_id = session.execute(
            select(db.Role.id).where(db.Role.org_id.is_(None), db.Role.name == SYSTEM_ADMIN_ROLE_NAME)
        ).scalar_one()

    resp = client.post(
        "/api/v1/grants/roles",
        json={"user_id": target_id, "role_id": admin_role_id},
        headers=grantor_headers,  # ROLE_ORG_ADMIN, not a superuser
    )
    assert resp.status_code == 403


# --- direct permission grants --------------------------------------------


def test_grant_permission_directly(auth_headers, make_local_user):
    user_id, _headers = make_local_user("direct_grant_user", "pw12345", role_names=())
    resp = client.post(
        "/api/v1/grants/permissions",
        json={"user_id": user_id, "permission_code": "job:trigger"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    perms = client.get(f"/api/v1/users/{user_id}/permissions", headers=auth_headers).json()["permissions"]
    assert perms == ["job:trigger"]


def test_grant_permission_rejects_unknown_code(auth_headers, make_local_user):
    user_id, _headers = make_local_user("bad_perm_user", "pw12345", role_names=())
    resp = client.post(
        "/api/v1/grants/permissions",
        json={"user_id": user_id, "permission_code": "not:real"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


# --- report-specific access grants, wired into actual authorization ------


def test_report_manage_grant_lets_user_update_one_report_only(auth_headers, make_local_user):
    report_id = _register_report(auth_headers)
    other_report_id = _register_report(auth_headers, name="Other Report")
    user_id, headers = make_local_user("report_grantee", "pw12345", role_names=())

    grant_resp = client.post(
        "/api/v1/grants/reports",
        json={"subject_type": "user", "subject_id": user_id, "report_id": report_id, "permission_level": "manage"},
        headers=auth_headers,
    )
    assert grant_resp.status_code == 200

    # Can update the granted report...
    resp = client.patch(f"/api/v1/reports/{report_id}", json={"name": "Renamed"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"

    # ...but not a different one.
    resp2 = client.patch(f"/api/v1/reports/{other_report_id}", json={"name": "Nope"}, headers=headers)
    assert resp2.status_code == 403


def test_report_view_grant_does_not_allow_manage(auth_headers, make_local_user):
    report_id = _register_report(auth_headers)
    user_id, headers = make_local_user("view_only_grantee", "pw12345", role_names=())
    client.post(
        "/api/v1/grants/reports",
        json={"subject_type": "user", "subject_id": user_id, "report_id": report_id, "permission_level": "view"},
        headers=auth_headers,
    )
    resp = client.patch(f"/api/v1/reports/{report_id}", json={"name": "Nope"}, headers=headers)
    assert resp.status_code == 403


def test_expired_report_grant_no_longer_authorizes(auth_headers, make_local_user):
    report_id = _register_report(auth_headers)
    user_id, headers = make_local_user("expired_report_grantee", "pw12345", role_names=())
    client.post(
        "/api/v1/grants/reports",
        json={
            "subject_type": "user",
            "subject_id": user_id,
            "report_id": report_id,
            "permission_level": "manage",
            "expires_at": _past(),
        },
        headers=auth_headers,
    )
    resp = client.patch(f"/api/v1/reports/{report_id}", json={"name": "Nope"}, headers=headers)
    assert resp.status_code == 403


def test_revoke_report_grant(auth_headers, make_local_user):
    report_id = _register_report(auth_headers)
    user_id, headers = make_local_user("revocable_grantee", "pw12345", role_names=())
    grant = client.post(
        "/api/v1/grants/reports",
        json={"subject_type": "user", "subject_id": user_id, "report_id": report_id, "permission_level": "manage"},
        headers=auth_headers,
    ).json()

    assert client.patch(f"/api/v1/reports/{report_id}", json={"name": "Still works"}, headers=headers).status_code == 200

    revoke = client.delete(f"/api/v1/grants/reports/{grant['id']}", headers=auth_headers)
    assert revoke.status_code == 204

    resp = client.patch(f"/api/v1/reports/{report_id}", json={"name": "Nope now"}, headers=headers)
    assert resp.status_code == 403


def test_report_access_granted_to_a_role_covers_every_member(auth_headers, make_local_user):
    report_id = _register_report(auth_headers)
    role_id = _role_id("ROLE_REPORT_VIEWER")
    user_id, headers = make_local_user("role_grantee", "pw12345", role_names=("ROLE_REPORT_VIEWER",))

    client.post(
        "/api/v1/grants/reports",
        json={"subject_type": "role", "subject_id": role_id, "report_id": report_id, "permission_level": "manage"},
        headers=auth_headers,
    )

    resp = client.patch(f"/api/v1/reports/{report_id}", json={"name": "Via role grant"}, headers=headers)
    assert resp.status_code == 200
