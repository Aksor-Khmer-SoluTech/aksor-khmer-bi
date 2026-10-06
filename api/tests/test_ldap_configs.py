"""API-level tests for /api/v1/ldap-configs (CRUD, org-scoping, the
/test connection endpoint) and the full login flow for an `ldap`-auth
user. The connection-dependent tests reuse test_auth_ldap.py's live
OpenLDAP skip guard -- see that module's docstring for how to stand one
up locally.
"""
from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from ldap3 import MODIFY_ADD, MODIFY_DELETE, Connection, Server

from app.main import app
from app.rbac import ROOT_ORG_ID
from tests.test_auth_ldap import (  # noqa: F401 -- reuse the skip guard + constants
    LDAP_ADMIN_DN,
    LDAP_ADMIN_PASSWORD_ENV,
    LDAP_BASE_DN,
    LDAP_GROUP_SEARCH_BASE,
    LDAP_TEST_URI,
    pytestmark,
)

client = TestClient(app)

_ADMIN_PASSWORD = "adminpass123"  # matches api/tests/fixtures/ldap-seed.ldif's LDAP_ADMIN_PASSWORD


_PLACEHOLDER_MEMBER_DN = "cn=placeholder,ou=people,dc=aksor,dc=test"


def _remove_from_group(user_dn: str, group_dn: str) -> None:
    """Directly edit the live directory -- used to test the *actual*
    supported reconciliation path (a user's real group membership
    changes between logins), as opposed to deleting the internal mapping
    row, which app/auth_ldap.py's _sync_group_roles does not retroactively
    apply to grants it already synced (a mapping it can no longer see
    isn't reconsidered) -- a real gap, not something to paper over by
    testing the wrong scenario.

    `groupOfNames` requires at least one `member` (confirmed the hard
    way: OpenLDAP rejects the plain delete with "objectClassViolation"
    when it's the last one), so a placeholder member -- one that doesn't
    need to resolve to a real entry, just be syntactically a DN -- is
    added first to keep the group schema-valid with `user_dn` gone.
    """
    conn = Connection(Server(LDAP_TEST_URI), user=LDAP_ADMIN_DN, password=_ADMIN_PASSWORD, auto_bind=True)
    conn.modify(group_dn, {"member": [(MODIFY_ADD, [_PLACEHOLDER_MEMBER_DN])]})
    conn.modify(group_dn, {"member": [(MODIFY_DELETE, [user_dn])]})
    conn.unbind()


def _create_config(auth_headers, **overrides) -> dict:
    body = {
        "server_uri": LDAP_TEST_URI,
        "bind_method": "direct_bind",
        "base_dn": LDAP_BASE_DN,
        "direct_bind_dn_template": "uid={username},ou=people,{base_dn}",
        "group_search_base": LDAP_GROUP_SEARCH_BASE,
    }
    body.update(overrides)
    resp = client.post("/api/v1/ldap-configs", params={"org_id": ROOT_ORG_ID}, json=body, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_and_get_ldap_config(auth_headers):
    created = _create_config(auth_headers)
    resp = client.get(f"/api/v1/ldap-configs/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["bind_method"] == "direct_bind"


def test_create_ldap_config_requires_permission(make_local_user):
    _, headers = make_local_user("noldapperm", "pw12345", role_names=())
    resp = client.post(
        "/api/v1/ldap-configs",
        params={"org_id": ROOT_ORG_ID},
        json={"server_uri": LDAP_TEST_URI, "bind_method": "direct_bind", "base_dn": LDAP_BASE_DN},
        headers=headers,
    )
    assert resp.status_code == 403


def test_search_bind_config_requires_service_fields(auth_headers):
    resp = client.post(
        "/api/v1/ldap-configs",
        params={"org_id": ROOT_ORG_ID},
        json={"server_uri": LDAP_TEST_URI, "bind_method": "search_bind", "base_dn": LDAP_BASE_DN},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_upn_bind_config_requires_domain(auth_headers):
    resp = client.post(
        "/api/v1/ldap-configs",
        params={"org_id": ROOT_ORG_ID},
        json={"server_uri": LDAP_TEST_URI, "bind_method": "upn_bind", "base_dn": LDAP_BASE_DN},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_only_superuser_can_create_system_wide_config(make_local_user):
    _, headers = make_local_user("orgadmin_ldap", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    resp = client.post(
        "/api/v1/ldap-configs",
        json={"server_uri": LDAP_TEST_URI, "bind_method": "direct_bind", "base_dn": LDAP_BASE_DN},
        headers=headers,
    )
    assert resp.status_code == 403


def test_test_connection_endpoint_success(auth_headers):
    created = _create_config(auth_headers)
    resp = client.post(
        f"/api/v1/ldap-configs/{created['id']}/test",
        json={"username": "jdoe", "password": "JaneSecret123"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["dn"] == "uid=jdoe,ou=people,dc=aksor,dc=test"
    assert "cn=report-admins,ou=groups,dc=aksor,dc=test" in body["groups"]


def test_test_connection_endpoint_wrong_password(auth_headers):
    created = _create_config(auth_headers)
    resp = client.post(
        f"/api/v1/ldap-configs/{created['id']}/test",
        json={"username": "jdoe", "password": "wrong"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False


# --- group -> role mappings ------------------------------------------


def _role_id(auth_headers, name: str, org_id: str = ROOT_ORG_ID) -> str:
    roles = client.get("/api/v1/roles", params={"org_id": org_id}, headers=auth_headers).json()
    return next(r["id"] for r in roles if r["name"] == name)


def test_create_and_list_group_mapping(auth_headers):
    created = _create_config(auth_headers)
    role_id = _role_id(auth_headers, "ROLE_REPORT_ADMIN")
    resp = client.post(
        f"/api/v1/ldap-configs/{created['id']}/group-mappings",
        json={"group_dn": "cn=report-admins,ou=groups,dc=aksor,dc=test", "role_id": role_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    listed = client.get(f"/api/v1/ldap-configs/{created['id']}/group-mappings", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


# --- full end-to-end login + role sync -----------------------------------


def test_ldap_user_can_log_in_and_gets_synced_role(auth_headers):
    config = _create_config(auth_headers)
    role_id = _role_id(auth_headers, "ROLE_REPORT_ADMIN")
    client.post(
        f"/api/v1/ldap-configs/{config['id']}/group-mappings",
        json={"group_dn": "cn=report-admins,ou=groups,dc=aksor,dc=test", "role_id": role_id},
        headers=auth_headers,
    )

    created_user = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "jdoe", "auth_source": "ldap"},
        headers=auth_headers,
    )
    assert created_user.status_code == 200
    user_id = created_user.json()["id"]

    token = base64.b64encode(b"jdoe:JaneSecret123").decode()
    verify = client.get("/api/v1/auth/verify", headers={"Authorization": f"Basic {token}"})
    assert verify.status_code == 200
    assert verify.json()["username"] == "jdoe"

    perms = client.get(f"/api/v1/users/{user_id}/permissions", headers=auth_headers).json()["permissions"]
    assert set(perms) == {"report:manage", "report:render", "report:view"}


def test_ldap_user_wrong_password_rejected(auth_headers):
    _create_config(auth_headers)
    client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "bsmith", "auth_source": "ldap"},
        headers=auth_headers,
    )
    token = base64.b64encode(b"bsmith:wrong-password").decode()
    resp = client.get("/api/v1/auth/verify", headers={"Authorization": f"Basic {token}"})
    assert resp.status_code == 401


def test_ldap_user_role_revoked_when_removed_from_group(auth_headers):
    config = _create_config(auth_headers)
    role_id = _role_id(auth_headers, "ROLE_REPORT_ADMIN")
    client.post(
        f"/api/v1/ldap-configs/{config['id']}/group-mappings",
        json={"group_dn": "cn=report-admins,ou=groups,dc=aksor,dc=test", "role_id": role_id},
        headers=auth_headers,
    )

    created_user = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "jdoe", "auth_source": "ldap"},
        headers=auth_headers,
    ).json()

    token = base64.b64encode(b"jdoe:JaneSecret123").decode()
    client.get("/api/v1/auth/verify", headers={"Authorization": f"Basic {token}"})
    perms_before = client.get(f"/api/v1/users/{created_user['id']}/permissions", headers=auth_headers).json()
    assert "report:manage" in perms_before["permissions"]

    # The user's *actual* directory group membership changes (they're
    # removed from report-admins) -- the mapping itself stays configured.
    # Logging in again should deactivate the ldap-sync'd role grant.
    try:
        _remove_from_group("uid=jdoe,ou=people,dc=aksor,dc=test", "cn=report-admins,ou=groups,dc=aksor,dc=test")
        client.get("/api/v1/auth/verify", headers={"Authorization": f"Basic {token}"})
        perms_after = client.get(f"/api/v1/users/{created_user['id']}/permissions", headers=auth_headers).json()
        assert perms_after["permissions"] == []
    finally:
        # Restore the seed data's membership (jdoe back in, placeholder
        # out) so other tests in this module (and re-runs) see the
        # directory in its original state.
        conn = Connection(Server(LDAP_TEST_URI), user=LDAP_ADMIN_DN, password=_ADMIN_PASSWORD, auto_bind=True)
        conn.modify(
            "cn=report-admins,ou=groups,dc=aksor,dc=test",
            {"member": [(MODIFY_ADD, ["uid=jdoe,ou=people,dc=aksor,dc=test"])]},
        )
        conn.modify(
            "cn=report-admins,ou=groups,dc=aksor,dc=test",
            {"member": [(MODIFY_DELETE, [_PLACEHOLDER_MEMBER_DN])]},
        )
        conn.unbind()
