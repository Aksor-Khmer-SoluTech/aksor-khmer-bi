"""LDAP group -> role sync, with the directory bind stubbed out.

test_ldap_configs.py runs the same flow against a real OpenLDAP, but skips itself where none is running -- which hid
that the sync wrote "ldap-sync" into granted_by, a foreign key to users.id, so any database that checks foreign keys
refused the sign-in. These run everywhere, with foreign keys on (conftest.py).
"""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth_ldap, db
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)

GROUP = "cn=report-admins,ou=groups,dc=example,dc=test"


@pytest.fixture
def directory(monkeypatch):
    """The groups the stub directory says the signing-in user is in; any password binds."""
    groups: list[str] = []
    monkeypatch.setattr(
        auth_ldap, "authenticate",
        lambda config, username, password: auth_ldap.LdapBindResult(dn=f"uid={username},ou=people,dc=example,dc=test", groups=list(groups)),
    )
    return groups


@pytest.fixture
def ldap_user(auth_headers):
    config = client.post(
        "/api/v1/ldap-configs", params={"org_id": ROOT_ORG_ID}, headers=auth_headers,
        json={"server_uri": "ldap://directory.invalid", "bind_method": "direct_bind", "base_dn": "dc=example,dc=test",
              "direct_bind_dn_template": "uid={username},ou=people,{base_dn}", "group_search_base": "ou=groups,dc=example,dc=test"},
    ).json()
    roles = client.get("/api/v1/roles", params={"org_id": ROOT_ORG_ID}, headers=auth_headers).json()
    role_id = next(r["id"] for r in roles if r["name"] == "ROLE_REPORT_ADMIN")
    mapped = client.post(f"/api/v1/ldap-configs/{config['id']}/group-mappings", json={"group_dn": GROUP, "role_id": role_id}, headers=auth_headers)
    assert mapped.status_code == 200, mapped.text
    user = client.post("/api/v1/users", params={"org_id": ROOT_ORG_ID}, json={"username": "jdoe", "auth_source": "ldap"}, headers=auth_headers)
    assert user.status_code == 200, user.text
    return user.json()["id"], role_id


def _sign_in():
    token = base64.b64encode(b"jdoe:whatever-the-directory-accepts").decode()
    return client.get("/api/v1/auth/verify", headers={"Authorization": f"Basic {token}"})


def _synced(user_id, role_id):
    with db.SessionLocal() as session:
        return session.execute(
            select(db.UserRoleAssignment).where(db.UserRoleAssignment.user_id == user_id, db.UserRoleAssignment.role_id == role_id)
        ).scalars().all()


def test_group_member_signs_in_with_the_mapped_role(directory, ldap_user):
    user_id, role_id = ldap_user
    directory.append(GROUP)
    resp = _sign_in()
    assert resp.status_code == 200, resp.text
    assert "report:manage" in resp.json()["permissions"]
    [grant] = _synced(user_id, role_id)
    assert grant.source == "ldap" and grant.granted_by is None and grant.is_active


def test_leaving_the_group_revokes_only_the_synced_grant(auth_headers, directory, ldap_user):
    user_id, role_id = ldap_user
    directory.append(GROUP)
    assert _sign_in().status_code == 200
    directory.clear()
    resp = _sign_in()
    assert resp.status_code == 200, resp.text
    assert "report:manage" not in resp.json()["permissions"]
    assert [g.is_active for g in _synced(user_id, role_id)] == [False]
    # Back in the group: the same row comes back rather than a second one.
    directory.append(GROUP)
    assert "report:manage" in _sign_in().json()["permissions"]
    assert [g.is_active for g in _synced(user_id, role_id)] == [True]
