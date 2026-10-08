"""A directory (AD / LDAP) user has no password here: their credential is the directory's, so nothing in this
application may set, reset, change or accept a local one for them -- and a sign-in must never reach the
directory with a blank password (an "unauthenticated bind", which some servers accept as success). These tests
need no directory server."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import auth_ldap, db
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def _ldap_user(auth_headers, username="dir.user") -> str:
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": username, "auth_source": "ldap"},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def test_a_directory_user_is_created_without_a_password(auth_headers):
    refused = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": "with.pw", "auth_source": "ldap", "password": "Sup3r-secret-pass!"},
        headers=auth_headers,
    )
    assert refused.status_code == 400
    uid = _ldap_user(auth_headers)
    with db.SessionLocal() as session:
        row = session.get(db.User, uid)
        assert row.auth_source == "ldap" and row.password_hash is None and row.must_change_password is False


def test_an_admin_cannot_give_a_directory_user_a_password(auth_headers):
    uid = _ldap_user(auth_headers)
    assert client.post(f"/api/v1/users/{uid}/reset-password", json={}, headers=auth_headers).status_code == 400
    assert client.post(f"/api/v1/users/{uid}/reset-password", json={"password": "Sup3r-secret-pass!"}, headers=auth_headers).status_code == 400
    assert client.patch(f"/api/v1/users/{uid}", json={"password": "Sup3r-secret-pass!"}, headers=auth_headers).status_code == 400
    assert client.patch(f"/api/v1/users/{uid}", json={"must_change_password": True}, headers=auth_headers).status_code == 400
    with db.SessionLocal() as session:
        assert session.get(db.User, uid).password_hash is None


def test_a_directory_user_cannot_sign_in_with_any_local_password(auth_headers):
    """No hash, no local path: the sign-in goes to the directory or nowhere -- and with none configured, nowhere."""
    _ldap_user(auth_headers, "no.local.path")
    for password in ("", " ", "anything", "Sup3r-secret-pass!"):
        resp = client.post("/api/v1/auth/login", json={"username": "no.local.path", "password": password})
        assert resp.status_code == 401, (password, resp.text)


def _config(**overrides):
    base = dict(
        id="c", org_id=None, server_uri="ldap://127.0.0.1:1", base_dn="dc=example,dc=org", bind_method="direct_bind",
        direct_bind_dn_template=None, service_bind_dn="cn=svc,dc=example,dc=org", service_bind_password_env="X",
        user_search_filter="(uid={username})", upn_domain="example.org", group_search_base=None, is_enabled=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("method", ["direct_bind", "search_bind", "upn_bind"])
@pytest.mark.parametrize("password", ["", "   ", "\t", "pass\0word"])
def test_a_blank_password_never_reaches_the_directory(monkeypatch, method, password):
    def boom(*args, **kwargs):
        raise AssertionError("the directory was contacted with a blank password")

    monkeypatch.setattr(auth_ldap, "_bind", boom)
    assert auth_ldap.authenticate(_config(bind_method=method), "alice", password) is None


def test_a_name_with_directory_syntax_stays_a_name(monkeypatch):
    seen = {}

    def fake_bind(server_uri, dn, password):
        seen["dn"] = dn
        return None

    monkeypatch.setattr(auth_ldap, "_bind", fake_bind)
    auth_ldap.authenticate(_config(), "alice,ou=admins", "x")
    assert seen["dn"] == r"uid=alice\,ou\=admins,dc=example,dc=org"

    filters = []

    class Conn:
        entries = []

        def search(self, search_base, search_filter, attributes):
            filters.append(search_filter)
            return False

        def unbind(self):
            pass

    monkeypatch.setattr(auth_ldap, "_bind", lambda *a: Conn())
    monkeypatch.setattr(auth_ldap, "resolve_service_bind_password", lambda c: "svc")
    auth_ldap.authenticate(_config(bind_method="search_bind"), "*)(uid=*", "x")
    assert filters == [r"(uid=\2a\29\28uid=\2a)"]
