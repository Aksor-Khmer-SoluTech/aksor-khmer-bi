"""Exercises app/auth_ldap.py against a real OpenLDAP server, not a mock
-- same standard the rest of this project holds itself to (see the
Postgres-migration and portal work, both verified against real
containers rather than assumed to work from reading the code).

Requires a running OpenLDAP container seeded from
api/tests/fixtures/ldap-seed.ldif (see that file's header comment for
the exact `docker run` + `ldapadd` commands, also documented in
docs/deployment.md's LDAP section).

The whole module is skipped (not failed) if nothing is listening on
LDAP_TEST_URI, so the rest of the suite stays runnable without Docker.
"""
from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import pytest

from app.auth_ldap import LdapConfigError, authenticate
from app.db import LdapConfig

LDAP_TEST_URI = os.environ.get("LDAP_TEST_URI", "ldap://localhost:3389")
LDAP_BASE_DN = "dc=aksor,dc=test"
LDAP_ADMIN_DN = "cn=admin,dc=aksor,dc=test"
LDAP_ADMIN_PASSWORD_ENV = "AKSOR_TEST_LDAP_ADMIN_PASSWORD"
# Deliberately narrower than LDAP_BASE_DN: the test server's ACL (see
# ldap-seed.ldif's header / docs/deployment.md) only grants authenticated
# users read access to ou=groups specifically, not the whole tree from
# its root -- a realistic setup (locking down personal profile data while
# leaving group membership queryable), not a test-only workaround. See
# test_direct_bind_resolves_group_membership_via_reverse_search's comment.
LDAP_GROUP_SEARCH_BASE = "ou=groups,dc=aksor,dc=test"


def _ldap_server_reachable() -> bool:
    parsed = urlparse(LDAP_TEST_URI)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 389), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _ldap_server_reachable(), reason=f"No LDAP server reachable at {LDAP_TEST_URI} -- see module docstring"
)


@pytest.fixture(autouse=True)
def ldap_admin_password_env(monkeypatch):
    monkeypatch.setenv(LDAP_ADMIN_PASSWORD_ENV, "adminpass123")


def _config(**overrides) -> LdapConfig:
    defaults = dict(
        id="test-config",
        org_id=None,
        server_uri=LDAP_TEST_URI,
        base_dn=LDAP_BASE_DN,
        direct_bind_dn_template=None,
        service_bind_dn=None,
        service_bind_password_env=None,
        user_search_filter=None,
        upn_domain=None,
        group_search_base=LDAP_GROUP_SEARCH_BASE,
        is_enabled=True,
        created_at="",
        updated_at="",
    )
    defaults.update(overrides)
    return LdapConfig(**defaults)


# --- direct_bind ------------------------------------------------------


def test_direct_bind_succeeds_with_correct_password():
    config = _config(bind_method="direct_bind", direct_bind_dn_template="uid={username},ou=people,{base_dn}")
    result = authenticate(config, "jdoe", "JaneSecret123")
    assert result is not None
    assert result.dn == "uid=jdoe,ou=people,dc=aksor,dc=test"


def test_direct_bind_resolves_group_membership_via_reverse_search():
    config = _config(bind_method="direct_bind", direct_bind_dn_template="uid={username},ou=people,{base_dn}")
    result = authenticate(config, "jdoe", "JaneSecret123")
    assert result is not None
    assert "cn=report-admins,ou=groups,dc=aksor,dc=test" in result.groups


def test_direct_bind_fails_with_wrong_password():
    config = _config(bind_method="direct_bind", direct_bind_dn_template="uid={username},ou=people,{base_dn}")
    assert authenticate(config, "jdoe", "wrong-password") is None


def test_direct_bind_fails_for_unknown_user():
    config = _config(bind_method="direct_bind", direct_bind_dn_template="uid={username},ou=people,{base_dn}")
    assert authenticate(config, "nobody", "whatever") is None


# --- search_bind --------------------------------------------------------


def test_search_bind_succeeds_and_finds_correct_dn():
    config = _config(
        bind_method="search_bind",
        service_bind_dn=LDAP_ADMIN_DN,
        service_bind_password_env=LDAP_ADMIN_PASSWORD_ENV,
        user_search_filter="(uid={username})",
    )
    result = authenticate(config, "bsmith", "BobSecret123")
    assert result is not None
    assert result.dn == "uid=bsmith,ou=people,dc=aksor,dc=test"
    assert "cn=report-viewers,ou=groups,dc=aksor,dc=test" in result.groups


def test_search_bind_fails_with_wrong_password():
    config = _config(
        bind_method="search_bind",
        service_bind_dn=LDAP_ADMIN_DN,
        service_bind_password_env=LDAP_ADMIN_PASSWORD_ENV,
        user_search_filter="(uid={username})",
    )
    assert authenticate(config, "bsmith", "wrong-password") is None


def test_search_bind_fails_for_unknown_user():
    config = _config(
        bind_method="search_bind",
        service_bind_dn=LDAP_ADMIN_DN,
        service_bind_password_env=LDAP_ADMIN_PASSWORD_ENV,
        user_search_filter="(uid={username})",
    )
    assert authenticate(config, "nobody", "whatever") is None


def test_search_bind_raises_config_error_when_service_account_password_wrong(monkeypatch):
    monkeypatch.setenv(LDAP_ADMIN_PASSWORD_ENV, "not-the-real-password")
    config = _config(
        bind_method="search_bind",
        service_bind_dn=LDAP_ADMIN_DN,
        service_bind_password_env=LDAP_ADMIN_PASSWORD_ENV,
        user_search_filter="(uid={username})",
    )
    with pytest.raises(LdapConfigError):
        authenticate(config, "bsmith", "BobSecret123")


def test_search_bind_raises_config_error_when_password_env_var_missing(monkeypatch):
    monkeypatch.delenv(LDAP_ADMIN_PASSWORD_ENV, raising=False)
    config = _config(
        bind_method="search_bind",
        service_bind_dn=LDAP_ADMIN_DN,
        service_bind_password_env=LDAP_ADMIN_PASSWORD_ENV,
        user_search_filter="(uid={username})",
    )
    with pytest.raises(LdapConfigError):
        authenticate(config, "bsmith", "BobSecret123")


# --- upn_bind -------------------------------------------------------------
# Plain OpenLDAP has no notion of "user@domain" bind DNs (that's an
# Active-Directory-specific convenience) -- verified here to fail closed
# against OpenLDAP, not to succeed. See module/auth_ldap.py docstrings.


def test_upn_bind_fails_closed_against_plain_openldap():
    config = _config(bind_method="upn_bind", upn_domain="aksor.test")
    assert authenticate(config, "jdoe", "JaneSecret123") is None


def test_upn_bind_requires_upn_domain_configured():
    config = _config(bind_method="upn_bind", upn_domain=None)
    with pytest.raises(LdapConfigError):
        authenticate(config, "jdoe", "JaneSecret123")
