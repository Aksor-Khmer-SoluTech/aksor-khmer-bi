"""Forced password change + admin password reset: the must_change_password
gate (app/auth.py), POST /users/{id}/reset-password, and the password
policy every set-a-password path shares (app/security.py)."""
import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db
from app.main import app
from app.rbac import ROOT_ORG_ID
from app.security import check_password_policy, generate_password

client = TestClient(app)


def _basic(username: str, password: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()}


def _create_user(auth_headers, username="newhire", password="temp-pass-1", **extra) -> dict:
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": username, "auth_source": "local", "password": password, **extra},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _grant_role(user_id: str, role_name: str) -> None:
    with db.SessionLocal() as session:
        role = session.execute(
            select(db.Role).where(db.Role.name == role_name, db.Role.org_id == ROOT_ORG_ID)
        ).scalar_one()
        session.add(db.UserRoleAssignment(user_id=user_id, role_id=role.id, granted_at="2026-01-01T00:00:00+00:00", is_active=True))
        session.commit()


def _audit_actions(user_id: str) -> list[db.AuditEvent]:
    with db.SessionLocal() as session:
        return list(session.execute(select(db.AuditEvent).where(db.AuditEvent.entity_id == user_id)).scalars())


# ---- the gate ---------------------------------------------------------------


def test_admin_created_user_must_change_password_by_default(auth_headers):
    assert _create_user(auth_headers)["must_change_password"] is True


def test_admin_can_opt_out_of_forced_change(auth_headers):
    user = _create_user(auth_headers, username="svc", must_change_password=False)
    assert user["must_change_password"] is False
    assert client.get("/api/v1/reports/accessible", headers=_basic("svc", "temp-pass-1")).status_code == 200


def test_ldap_user_is_never_flagged(auth_headers):
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "dirguy", "auth_source": "ldap", "must_change_password": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is False


def test_flagged_user_is_refused_everywhere_but_the_way_out(auth_headers):
    user = _create_user(auth_headers)
    _grant_role(user["id"], "ROLE_ORG_ADMIN")
    headers = _basic("newhire", "temp-pass-1")

    blocked = client.get("/api/v1/users", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "PASSWORD_CHANGE_REQUIRED"
    assert client.get("/api/v1/reports/accessible", headers=headers).json()["detail"] == "PASSWORD_CHANGE_REQUIRED"
    assert client.get("/api/v1/users/me/settings", headers=headers).status_code == 403

    # /auth/verify still answers (that's how the portal finds out) and says why.
    verify = client.get("/api/v1/auth/verify", headers=headers)
    assert verify.status_code == 200
    assert verify.json()["must_change_password"] is True

    me = client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True


def test_wrong_password_is_still_a_plain_401_not_the_gate(auth_headers):
    _create_user(auth_headers)
    resp = client.get("/api/v1/users", headers=_basic("newhire", "not-the-password"))
    assert resp.status_code == 401


def test_changing_the_password_lifts_the_gate(auth_headers):
    user = _create_user(auth_headers)
    _grant_role(user["id"], "ROLE_ORG_ADMIN")

    resp = client.patch(
        "/api/v1/users/me",
        json={"current_password": "temp-pass-1", "new_password": "my-own-secret-9"},
        headers=_basic("newhire", "temp-pass-1"),
    )
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is False

    # Old password is dead, new one works and nothing is gated any more.
    assert client.get("/api/v1/users", headers=_basic("newhire", "temp-pass-1")).status_code == 401
    assert client.get("/api/v1/users", headers=_basic("newhire", "my-own-secret-9")).status_code == 200
    assert client.get("/api/v1/auth/verify", headers=_basic("newhire", "my-own-secret-9")).json()["must_change_password"] is False


def test_forced_change_cannot_reuse_the_temporary_password(auth_headers):
    _create_user(auth_headers)
    headers = _basic("newhire", "temp-pass-1")
    resp = client.patch(
        "/api/v1/users/me", json={"current_password": "temp-pass-1", "new_password": "temp-pass-1"}, headers=headers
    )
    assert resp.status_code == 400
    assert "different" in resp.json()["detail"]
    assert client.get("/api/v1/users/me", headers=headers).json()["must_change_password"] is True


def test_a_failed_change_leaves_the_gate_up(auth_headers):
    _create_user(auth_headers)
    headers = _basic("newhire", "temp-pass-1")
    wrong_current = client.patch(
        "/api/v1/users/me", json={"current_password": "guess", "new_password": "my-own-secret-9"}, headers=headers
    )
    assert wrong_current.status_code == 400
    assert client.get("/api/v1/users/me", headers=headers).json()["must_change_password"] is True


def test_editing_a_profile_does_not_lift_the_gate(auth_headers):
    _create_user(auth_headers)
    headers = _basic("newhire", "temp-pass-1")
    resp = client.patch("/api/v1/users/me", json={"display_name": "New Hire"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is True


def test_break_glass_is_never_gated(auth_headers):
    assert client.get("/api/v1/auth/verify", headers=auth_headers).json()["must_change_password"] is False
    assert client.get("/api/v1/users", headers=auth_headers).status_code == 200


def test_existing_user_without_the_flag_is_untouched(make_local_user):
    _, headers = make_local_user("veteran", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    assert client.get("/api/v1/users", headers=headers).status_code == 200


# ---- admin: flag toggle -----------------------------------------------------


def test_admin_can_flag_and_unflag_a_user(auth_headers, make_local_user):
    user_id, headers = make_local_user("veteran", "pw12345", role_names=("ROLE_ORG_ADMIN",))

    flagged = client.patch(f"/api/v1/users/{user_id}", json={"must_change_password": True}, headers=auth_headers)
    assert flagged.status_code == 200
    assert flagged.json()["must_change_password"] is True
    # Takes effect on the very next request -- no session to expire.
    assert client.get("/api/v1/users", headers=headers).status_code == 403

    cleared = client.patch(f"/api/v1/users/{user_id}", json={"must_change_password": False}, headers=auth_headers)
    assert cleared.json()["must_change_password"] is False
    assert client.get("/api/v1/users", headers=headers).status_code == 200

    summaries = [e.summary for e in _audit_actions(user_id) if e.action == "user.update"]
    assert any("Required a password change" in s for s in summaries)
    assert any("Stopped requiring" in s for s in summaries)


def test_cannot_flag_an_ldap_user(auth_headers):
    created = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "dirguy", "auth_source": "ldap"},
        headers=auth_headers,
    ).json()
    resp = client.patch(f"/api/v1/users/{created['id']}", json={"must_change_password": True}, headers=auth_headers)
    assert resp.status_code == 400


# ---- admin: reset password --------------------------------------------------


def test_reset_generates_a_password_and_flags_the_user(auth_headers):
    user = _create_user(auth_headers, must_change_password=False)

    resp = client.post(f"/api/v1/users/{user['id']}/reset-password", json={}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert resp.headers["cache-control"] == "no-store"
    assert body["user"]["must_change_password"] is True
    generated = body["generated_password"]
    check_password_policy(generated)

    # The old password is dead; the generated one signs in but is gated.
    assert client.get("/api/v1/auth/verify", headers=_basic("newhire", "temp-pass-1")).status_code == 401
    assert client.get("/api/v1/auth/verify", headers=_basic("newhire", generated)).json()["must_change_password"] is True
    assert client.get("/api/v1/reports/accessible", headers=_basic("newhire", generated)).status_code == 403


def test_reset_with_an_admin_chosen_password_does_not_echo_it(auth_headers):
    user = _create_user(auth_headers)
    resp = client.post(
        f"/api/v1/users/{user['id']}/reset-password",
        json={"password": "chosen-by-admin-7", "require_change": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["generated_password"] is None
    assert resp.json()["user"]["must_change_password"] is False
    assert client.get("/api/v1/reports/accessible", headers=_basic("newhire", "chosen-by-admin-7")).status_code == 200


def test_reset_is_audited_without_the_password(auth_headers):
    user = _create_user(auth_headers)
    generated = client.post(f"/api/v1/users/{user['id']}/reset-password", json={}, headers=auth_headers).json()[
        "generated_password"
    ]
    events = [e for e in _audit_actions(user["id"]) if e.action == "user.password_reset"]
    assert len(events) == 1
    assert events[0].actor_username == "testadmin"
    assert generated not in repr([vars(e) for e in _audit_actions(user["id"])])


def test_reset_rejects_ldap_users(auth_headers):
    created = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "dirguy", "auth_source": "ldap"},
        headers=auth_headers,
    ).json()
    assert client.post(f"/api/v1/users/{created['id']}/reset-password", json={}, headers=auth_headers).status_code == 400


def test_reset_unknown_user_404s(auth_headers):
    assert client.post("/api/v1/users/nope/reset-password", json={}, headers=auth_headers).status_code == 404


def test_reset_needs_user_manage(auth_headers, make_local_user):
    target = _create_user(auth_headers)
    _, headers = make_local_user("plain", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    assert client.post(f"/api/v1/users/{target['id']}/reset-password", json={}, headers=headers).status_code == 403


def test_org_admin_cannot_reset_a_user_in_another_org(auth_headers, make_local_user):
    client.post("/api/v1/organizations", json={"id": "other", "name": "Other"}, headers=auth_headers)
    outsider = client.post(
        "/api/v1/users",
        params={"org_id": "other"},
        json={"username": "outsider", "auth_source": "local", "password": "temp-pass-1"},
        headers=auth_headers,
    ).json()
    _, headers = make_local_user("orgadmin", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    assert client.post(f"/api/v1/users/{outsider['id']}/reset-password", json={}, headers=headers).status_code == 404


def test_org_admin_can_reset_a_user_in_their_org(auth_headers, make_local_user):
    target = _create_user(auth_headers)
    _, headers = make_local_user("orgadmin", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    assert client.post(f"/api/v1/users/{target['id']}/reset-password", json={}, headers=headers).status_code == 200


# ---- password policy --------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    ["short1", "អក្សរខ្មែរ-password", "pässword-with-accent", "x" * 73],
    ids=["too-short", "khmer", "accented", "over-72"],
)
def test_every_set_password_path_enforces_the_policy(auth_headers, password):
    user = _create_user(auth_headers)
    headers = _basic("newhire", "temp-pass-1")

    assert client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "another", "auth_source": "local", "password": password},
        headers=auth_headers,
    ).status_code == 422
    assert client.patch(f"/api/v1/users/{user['id']}", json={"password": password}, headers=auth_headers).status_code == 422
    assert client.post(
        f"/api/v1/users/{user['id']}/reset-password", json={"password": password}, headers=auth_headers
    ).status_code == 422
    assert client.patch(
        "/api/v1/users/me", json={"current_password": "temp-pass-1", "new_password": password}, headers=headers
    ).status_code == 422


def test_generated_passwords_meet_the_policy_and_differ():
    seen = {generate_password() for _ in range(50)}
    assert len(seen) == 50
    for pw in seen:
        check_password_policy(pw)
        assert any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw)
