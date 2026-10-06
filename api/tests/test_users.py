from fastapi.testclient import TestClient

from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def _create_org(auth_headers, org_id, name):
    resp = client.post("/api/v1/organizations", json={"id": org_id, "name": name}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_local_user_requires_password(auth_headers):
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "alice", "auth_source": "local"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_create_ldap_user_rejects_password(auth_headers):
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "bob", "auth_source": "ldap", "password": "shouldnt-be-here"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_create_local_user(auth_headers):
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "carol", "email": "carol@example.com", "auth_source": "local", "password": "sekrit123"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "carol"
    assert body["org_id"] == ROOT_ORG_ID
    assert "password" not in body and "password_hash" not in body


def test_create_local_user_can_then_authenticate(auth_headers):
    client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "dave", "auth_source": "local", "password": "sekrit123"},
        headers=auth_headers,
    )
    import base64

    token = base64.b64encode(b"dave:sekrit123").decode()
    resp = client.get("/api/v1/auth/verify", headers={"Authorization": f"Basic {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "dave"


def test_duplicate_username_in_same_org_rejected(auth_headers):
    client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "erin", "auth_source": "local", "password": "sekrit123"},
        headers=auth_headers,
    )
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "erin", "auth_source": "local", "password": "different123"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


def test_same_username_allowed_in_different_orgs(auth_headers):
    _create_org(auth_headers, "orgx", "Org X")
    r1 = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "shared", "auth_source": "local", "password": "sekrit123"},
        headers=auth_headers,
    )
    r2 = client.post(
        "/api/v1/users",
        params={"org_id": "orgx"},
        json={"username": "shared", "auth_source": "local", "password": "sekrit123"},
        headers=auth_headers,
    )
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_create_user_requires_permission(make_local_user):
    _, headers = make_local_user("noperm", "pw12345", role_names=())
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "shouldfail", "auth_source": "local", "password": "sekrit123"},
        headers=headers,
    )
    assert resp.status_code == 403


def test_org_admin_can_manage_users_in_own_org(make_local_user):
    _, headers = make_local_user("orgadmin1", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "created_by_orgadmin", "auth_source": "local", "password": "sekrit123"},
        headers=headers,
    )
    assert resp.status_code == 200


def test_org_admin_cannot_manage_users_in_other_org(auth_headers, make_local_user):
    _create_org(auth_headers, "orgy", "Org Y")
    _, headers = make_local_user("orgadmin2", "pw12345", role_names=("ROLE_ORG_ADMIN",), org_id=ROOT_ORG_ID)
    resp = client.post(
        "/api/v1/users",
        params={"org_id": "orgy"},
        json={"username": "should_be_blocked", "auth_source": "local", "password": "sekrit123"},
        headers=headers,
    )
    assert resp.status_code == 404  # not 403 -- org existence isn't confirmed/denied either way


def test_get_user_permissions_endpoint(auth_headers, make_local_user):
    user_id, _headers = make_local_user("viewer1", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    resp = client.get(f"/api/v1/users/{user_id}/permissions", headers=auth_headers)
    assert resp.status_code == 200
    assert set(resp.json()["permissions"]) == {"report:view", "report:render"}


def test_update_user_deactivate(auth_headers):
    created = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "frank", "auth_source": "local", "password": "sekrit123"},
        headers=auth_headers,
    ).json()
    resp = client.patch(f"/api/v1/users/{created['id']}", json={"is_active": False}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# --- self-service /users/me -------------------------------------------------


def test_get_my_profile_requires_no_special_permission(make_local_user):
    user_id, headers = make_local_user("selfie1", "pw12345", role_names=())
    resp = client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == user_id
    assert resp.json()["username"] == "selfie1"


def test_get_my_profile_404s_for_break_glass(auth_headers):
    resp = client.get("/api/v1/users/me", headers=auth_headers)
    assert resp.status_code == 404


def test_update_my_profile_email_and_display_name(make_local_user):
    _, headers = make_local_user("selfie2", "pw12345", role_names=())
    resp = client.patch(
        "/api/v1/users/me", json={"email": "selfie2@example.com", "display_name": "Selfie Two"}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "selfie2@example.com"
    assert body["display_name"] == "Selfie Two"


def test_change_own_password_requires_current_password(make_local_user):
    # 400, not 401 -- a missing/wrong current_password isn't an auth
    # failure (Basic Auth already re-proved the session's own credential
    # to reach this endpoint), and the frontend treats any 401 globally
    # as "sign out" -- see routers/users.py's update_my_profile.
    _, headers = make_local_user("selfie3", "pw12345", role_names=())
    resp = client.patch("/api/v1/users/me", json={"new_password": "newpw12345"}, headers=headers)
    assert resp.status_code == 400


def test_change_own_password_rejects_wrong_current_password(make_local_user):
    _, headers = make_local_user("selfie4", "pw12345", role_names=())
    resp = client.patch(
        "/api/v1/users/me",
        json={"new_password": "newpw12345", "current_password": "wrongpw"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_change_own_password_then_authenticate_with_new_one(make_local_user):
    import base64

    _, headers = make_local_user("selfie5", "pw12345", role_names=())
    resp = client.patch(
        "/api/v1/users/me",
        json={"new_password": "newpw12345", "current_password": "pw12345"},
        headers=headers,
    )
    assert resp.status_code == 200

    token = base64.b64encode(b"selfie5:newpw12345").decode()
    verify = client.get("/api/v1/auth/verify", headers={"Authorization": f"Basic {token}"})
    assert verify.status_code == 200
    assert verify.json()["username"] == "selfie5"
