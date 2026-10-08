"""The sign-in flow: short-lived access token (JWT) + rotating refresh token in an HttpOnly cookie,
backed by revocable sessions. See app/auth_tokens.py and app/routers/auth.py."""
import base64
import json
import time
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth_tokens, db, totp
from app.main import app
from app.rbac import ROOT_ORG_ID

DELIBERATE = {"X-Aksor-Client": "test"}


@pytest.fixture
def http():
    """A client with its own cookie jar -- the refresh cookie must not leak between tests."""
    return TestClient(app)


def _login(http, username, password, *, remember=False, totp_code=None, expect=200):
    body = {"username": username, "password": password, "remember": remember}
    if totp_code:
        body["totp_code"] = totp_code
    resp = http.post("/api/v1/auth/login", json=body)
    assert resp.status_code == expect, resp.text
    return resp


def _bearer(resp) -> dict:
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _refresh(http, headers=None):
    return http.post("/api/v1/auth/refresh", headers={**DELIBERATE, **(headers or {})})


def _sessions():
    with db.SessionLocal() as session:
        return list(session.scalars(select(db.AuthSession).order_by(db.AuthSession.created_at)))


def _forge(claims_patch=None, *, alg="HS256", key=None, drop_signature=False):
    """A token built by hand, to try the ways a bad one can be bad."""
    token, _ = auth_tokens.encode_access_token(session_id="s1", username="u", user_id="x", org_id=None)
    header_part, payload_part, _sig = token.split(".")
    claims = json.loads(auth_tokens._b64u_decode(payload_part))
    claims.update(claims_patch or {})
    header = {"alg": alg, "typ": "JWT"}
    signing_input = (
        f"{auth_tokens._b64u(json.dumps(header).encode())}.{auth_tokens._b64u(json.dumps(claims).encode())}"
    )
    if drop_signature:
        return signing_input + "."
    import hashlib
    import hmac

    signature = hmac.new(key or auth_tokens._signing_key(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{auth_tokens._b64u(signature)}"


# --- signing in ------------------------------------------------------------------------------------


def test_login_returns_an_access_token_and_sets_an_httponly_refresh_cookie(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ("ROLE_REPORT_VIEWER",))
    resp = _login(http, "alice", "pw-alice-1")
    body = resp.json()

    assert body["token_type"] == "bearer" and body["expires_in"] == 900
    assert body["user"]["username"] == "alice" and "report:view" in body["user"]["permissions"]
    assert "refresh" not in json.dumps(body).lower()  # the refresh token never travels in the body
    assert resp.headers["cache-control"] == "no-store"

    cookie = resp.headers["set-cookie"].lower()
    assert "aksor_refresh=" in cookie and "httponly" in cookie and "path=/api/v1/auth" in cookie and "samesite=lax" in cookie
    assert "max-age" not in cookie and "secure" not in cookie  # a session cookie, over plain http


def test_remember_keeps_the_cookie_beyond_the_browser_and_the_session_for_longer(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    resp = _login(http, "alice", "pw-alice-1", remember=True)
    assert "max-age=" in resp.headers["set-cookie"].lower()
    row = _sessions()[0]
    assert row.remember is True
    assert datetime.fromisoformat(row.expires_at) - datetime.now(timezone.utc) > timedelta(days=29)

    other = TestClient(app)
    _login(other, "alice", "pw-alice-1")
    short = _sessions()[1]
    assert datetime.fromisoformat(short.expires_at) - datetime.now(timezone.utc) < timedelta(hours=13)


def test_the_secure_flag_follows_https_and_samesite_none_forces_it(http, make_local_user, monkeypatch):
    make_local_user("alice", "pw-alice-1", ())
    proxied = http.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "pw-alice-1"}, headers={"X-Forwarded-Proto": "https"}
    )
    assert "secure" in proxied.headers["set-cookie"].lower()

    monkeypatch.setenv("AUTH_COOKIE_SAMESITE", "none")
    cross_site = _login(TestClient(app), "alice", "pw-alice-1")
    cookie = cross_site.headers["set-cookie"].lower()
    assert "samesite=none" in cookie and "secure" in cookie


def test_the_access_token_authenticates_api_calls(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ("ROLE_REPORT_VIEWER",))
    headers = _bearer(_login(http, "alice", "pw-alice-1"))
    me = http.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200 and me.json()["username"] == "alice"
    assert http.get("/api/v1/auth/me", headers=headers).json()["username"] == "alice"


def test_wrong_password_is_a_logged_401(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    resp = _login(http, "alice", "nope", expect=401)
    assert resp.json()["detail"] == "Invalid credentials" and "set-cookie" not in resp.headers
    with db.SessionLocal() as session:
        assert session.scalars(select(db.AuthEvent).where(db.AuthEvent.success.is_(False))).first() is not None


def test_a_locked_account_cannot_sign_in(http, make_local_user, auth_headers):
    user_id, _ = make_local_user("alice", "pw-alice-1", ())
    http.patch(f"/api/v1/users/{user_id}", json={"is_locked": True}, headers=auth_headers)
    resp = _login(http, "alice", "pw-alice-1", expect=401)
    assert "locked" in resp.json()["detail"]
    assert _login(http, "alice", "wrong", expect=401).json()["detail"] == "Invalid credentials"  # a wrong guess learns nothing


def test_the_break_glass_login_works_and_stops_with_its_configuration(http, monkeypatch):
    resp = _login(http, "testadmin", "testpass123")
    assert resp.json()["user"]["is_superuser"] is True
    headers = _bearer(resp)
    assert http.get("/api/v1/auth/me", headers=headers).status_code == 200
    monkeypatch.setenv("PORTAL_USERNAME", "someoneelse")
    assert http.get("/api/v1/auth/me", headers=headers).status_code == 401


# --- two-factor authentication ---------------------------------------------------------------------


def _enable_2fa(client, headers):
    secret = client.post("/api/v1/users/me/totp/enroll", headers=headers).json()["secret"]
    step = totp.now() // 30
    confirm = client.post("/api/v1/users/me/totp/confirm", json={"code": pyotp.TOTP(secret).at((step - 1) * 30)}, headers=headers)
    assert confirm.status_code == 200
    return secret, step


def test_login_demands_the_code_and_a_2fa_account_cannot_use_basic_afterwards(http, make_local_user):
    _, basic = make_local_user("alice", "pw-alice-1", ())
    secret, step = _enable_2fa(http, basic)

    assert _login(http, "alice", "pw-alice-1", expect=401).json()["detail"] == "2FA_REQUIRED"
    assert _login(http, "alice", "pw-alice-1", totp_code="000000", expect=401).json()["detail"] == "Invalid or expired code"
    ok = _login(http, "alice", "pw-alice-1", totp_code=pyotp.TOTP(secret).at(step * 30))
    assert http.get("/api/v1/users/me", headers=_bearer(ok)).status_code == 200

    # The same account with only its password -- the bypass 2FA used to have -- is refused.
    refused = http.get("/api/v1/users/me", headers=basic)
    assert refused.status_code == 401 and "two-factor" in refused.json()["detail"]


# --- refreshing ------------------------------------------------------------------------------------


def test_refresh_rotates_the_cookie_and_issues_a_new_access_token(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    first = _login(http, "alice", "pw-alice-1")
    old_cookie = http.cookies.get("aksor_refresh")

    refreshed = _refresh(http)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"] != first.json()["access_token"]
    assert refreshed.json()["user"]["username"] == "alice"
    assert http.cookies.get("aksor_refresh") != old_cookie and len(_sessions()) == 1
    assert http.get("/api/v1/users/me", headers=_bearer(refreshed)).status_code == 200


def test_refresh_needs_the_deliberate_header_and_a_known_origin(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    _login(http, "alice", "pw-alice-1")
    assert http.post("/api/v1/auth/refresh").status_code == 400
    assert _refresh(http, headers={"Origin": "https://evil.example"}).status_code == 403
    assert _refresh(http, headers={"Origin": "http://testserver"}).status_code == 200  # the server's own origin


def test_refresh_without_a_cookie_is_a_401_that_clears_it(http):
    resp = _refresh(http)
    assert resp.status_code == 401 and "aksor_refresh" in resp.headers["set-cookie"]


def test_a_replayed_refresh_token_ends_the_session(http, make_local_user, monkeypatch):
    monkeypatch.setenv("REFRESH_GRACE_SECONDS", "0")
    make_local_user("alice", "pw-alice-1", ())
    _login(http, "alice", "pw-alice-1")
    stolen = http.cookies.get("aksor_refresh")

    legitimate = _refresh(http)  # the owner refreshes first: `stolen` is now an old token
    assert legitimate.status_code == 200

    thief = TestClient(app)
    thief.cookies.set("aksor_refresh", stolen, path="/api/v1/auth")
    replay = _refresh(thief)
    assert replay.status_code == 401 and "twice" in replay.json()["detail"]
    assert _sessions()[0].revoked_reason == "reuse_detected"

    # ...and the owner's newest token and access token died with it.
    assert _refresh(http).status_code == 401
    assert http.get("/api/v1/users/me", headers=_bearer(legitimate)).status_code == 401


def test_two_tabs_refreshing_at_once_are_not_mistaken_for_theft(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    _login(http, "alice", "pw-alice-1")
    shared = http.cookies.get("aksor_refresh")

    assert _refresh(http).status_code == 200  # tab A rotates the cookie
    tab_b = TestClient(app)
    tab_b.cookies.set("aksor_refresh", shared, path="/api/v1/auth")  # tab B still carries the old value
    late = _refresh(tab_b)
    assert late.status_code == 200 and "set-cookie" not in late.headers  # served, cookie untouched
    assert _sessions()[0].revoked_at is None


def test_a_session_past_its_end_cannot_refresh(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    _login(http, "alice", "pw-alice-1")
    with db.SessionLocal() as session:
        row = session.scalars(select(db.AuthSession)).one()
        row.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        session.commit()
    assert _refresh(http).status_code == 401


# --- signing out and revocation --------------------------------------------------------------------


def test_logout_revokes_the_session_clears_the_cookie_and_kills_the_access_token(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    headers = _bearer(_login(http, "alice", "pw-alice-1"))
    out = http.post("/api/v1/auth/logout", headers=DELIBERATE)
    assert out.status_code == 204 and "aksor_refresh" in out.headers["set-cookie"]
    assert http.get("/api/v1/users/me", headers=headers).status_code == 401  # at once, not when it would have expired
    assert _refresh(http).status_code == 401
    assert _sessions()[0].revoked_reason == "logout"


def test_password_change_signs_out_the_other_sessions_but_not_this_one(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    here = _bearer(_login(http, "alice", "pw-alice-1"))
    elsewhere = _bearer(_login(TestClient(app), "alice", "pw-alice-1"))

    changed = http.patch("/api/v1/users/me", json={"current_password": "pw-alice-1", "new_password": "pw-alice-2"}, headers=here)
    assert changed.status_code == 200
    assert http.get("/api/v1/users/me", headers=here).status_code == 200
    assert http.get("/api/v1/users/me", headers=elsewhere).status_code == 401


def test_an_admin_disabling_locking_or_resetting_ends_the_sessions_at_once(http, make_local_user, auth_headers):
    user_id, _ = make_local_user("alice", "pw-alice-1", ())
    for change in ({"is_active": False}, {"is_locked": True}, {"password": "pw-brand-new-9"}):
        token = _bearer(_login(TestClient(app), "alice", "pw-alice-1"))
        assert http.get("/api/v1/users/me", headers=token).status_code == 200
        http.patch(f"/api/v1/users/{user_id}", json=change, headers=auth_headers)
        assert http.get("/api/v1/users/me", headers=token).status_code == 401, change
        http.patch(f"/api/v1/users/{user_id}", json={"is_active": True, "is_locked": False, "password": "pw-alice-1"}, headers=auth_headers)

    reset_token = _bearer(_login(TestClient(app), "alice", "pw-alice-1"))
    http.post(f"/api/v1/users/{user_id}/reset-password", json={"password": "pw-reset-by-admin-1"}, headers=auth_headers)
    assert http.get("/api/v1/users/me", headers=reset_token).status_code == 401


def test_permissions_are_read_fresh_so_a_role_change_applies_to_the_token_already_issued(http, make_local_user, auth_headers):
    user_id, _ = make_local_user("alice", "pw-alice-1", ())
    headers = _bearer(_login(http, "alice", "pw-alice-1"))
    assert "report:view" not in http.get("/api/v1/auth/me", headers=headers).json()["permissions"]

    with db.SessionLocal() as session:
        role = session.scalar(select(db.Role).where(db.Role.name == "ROLE_REPORT_VIEWER", db.Role.org_id == ROOT_ORG_ID))
    http.post("/api/v1/grants/roles", json={"user_id": user_id, "role_id": role.id}, headers=auth_headers)
    assert "report:view" in http.get("/api/v1/auth/me", headers=headers).json()["permissions"]


def test_an_account_that_must_change_its_password_is_gated_but_can_change_it(http, make_local_user):
    user_id, _ = make_local_user("alice", "pw-alice-1", ())
    with db.SessionLocal() as session:
        session.get(db.User, user_id).must_change_password = True
        session.commit()
    resp = _login(http, "alice", "pw-alice-1")
    assert resp.json()["user"]["must_change_password"] is True
    headers = _bearer(resp)
    assert http.get("/api/v1/reports/accessible", headers=headers).json()["detail"] == "PASSWORD_CHANGE_REQUIRED"
    assert http.patch("/api/v1/users/me", json={"current_password": "pw-alice-1", "new_password": "pw-alice-2"}, headers=headers).status_code == 200
    assert http.get("/api/v1/reports/accessible", headers=headers).status_code == 200


# --- the access token itself -----------------------------------------------------------------------


def test_expired_tampered_and_foreign_tokens_are_refused(http, make_local_user, monkeypatch):
    make_local_user("alice", "pw-alice-1", ())
    resp = _login(http, "alice", "pw-alice-1")
    good = resp.json()["access_token"]
    assert http.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {good}"}).status_code == 200

    header, payload, signature = good.split(".")
    bad_signature = f"{header}.{payload}.{signature[:-3]}abc"
    other_payload = auth_tokens._b64u(json.dumps({**json.loads(auth_tokens._b64u_decode(payload)), "usr": "root"}).encode())
    candidates = {
        "bad signature": bad_signature,
        "payload swapped": f"{header}.{other_payload}.{signature}",
        "alg none": _forge(alg="none", drop_signature=True),
        "alg none, signed": _forge(alg="none"),
        "RS256 claimed": _forge(alg="RS256"),
        "wrong issuer": _forge({"iss": "someone-else"}),
        "an embed-ticket style token": _forge({"typ": "embed"}),
        "signed with another key": _forge(key=b"x" * 40),
        "garbage": "not.a.token",
        "empty parts": "..",
    }
    for name, token in candidates.items():
        refused = http.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert refused.status_code == 401, name

    real_time = time.time
    monkeypatch.setattr(auth_tokens.time, "time", lambda: real_time() + 901)
    assert http.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {good}"}).status_code == 401


def test_a_token_cannot_be_pointed_at_someone_elses_session(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    make_local_user("bob", "pw-bob-1", ())
    alice = _login(http, "alice", "pw-alice-1")
    bob = _login(TestClient(app), "bob", "pw-bob-1")
    bob_session = next(row for row in _sessions() if row.username == "bob")
    forged = _forge({"sid": bob_session.id, "sub": alice.json()["user"]["username"], "usr": "alice"})
    assert http.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert bob.status_code == 200


def test_the_signing_key_comes_from_the_environment_or_a_private_file(http, monkeypatch, tmp_path):
    assert auth_tokens._signing_key() and auth_tokens.KEY_FILE.exists()
    assert oct(auth_tokens.KEY_FILE.stat().st_mode & 0o777) == "0o600"

    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(RuntimeError, match="32"):
        auth_tokens._signing_key()
    monkeypatch.setenv("JWT_SECRET", "s" * 40)
    assert auth_tokens._signing_key() == b"s" * 40


# --- HTTP Basic, for scripts -----------------------------------------------------------------------


def test_basic_still_works_for_scripts_and_can_be_switched_off(http, make_local_user, monkeypatch):
    _, basic = make_local_user("alice", "pw-alice-1", ())
    assert http.get("/api/v1/users/me", headers=basic).status_code == 200

    monkeypatch.setenv("AUTH_ALLOW_BASIC", "false")
    refused = http.get("/api/v1/users/me", headers=basic)
    assert refused.status_code == 401 and "auth/login" in refused.json()["detail"]
    # signing in and using a token is unaffected
    assert http.get("/api/v1/users/me", headers=_bearer(_login(http, "alice", "pw-alice-1"))).status_code == 200


def test_no_credentials_is_a_401_that_names_bearer(http):
    resp = http.get("/api/v1/users/me")
    assert resp.status_code == 401 and resp.headers["www-authenticate"] == "Bearer"


# --- the places I'm signed in ------------------------------------------------------------------------


def test_sessions_list_marks_the_current_one_and_can_end_the_others(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    here = _bearer(_login(http, "alice", "pw-alice-1"))
    laptop = TestClient(app)
    other = _bearer(_login(laptop, "alice", "pw-alice-1", remember=True))

    listed = http.get("/api/v1/auth/sessions", headers=here).json()
    assert len(listed) == 2 and sum(s["current"] for s in listed) == 1
    assert {s["remember"] for s in listed} == {True, False}

    revoked = http.post("/api/v1/auth/sessions/revoke-others", headers=here)
    assert revoked.json() == {"revoked": 1}
    assert http.get("/api/v1/users/me", headers=other).status_code == 401
    assert http.get("/api/v1/users/me", headers=here).status_code == 200
    assert len(http.get("/api/v1/auth/sessions", headers=here).json()) == 1


def test_a_session_can_be_ended_by_id_but_only_your_own(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    make_local_user("bob", "pw-bob-1", ())
    alice = _bearer(_login(http, "alice", "pw-alice-1"))
    other = TestClient(app)
    bob = _bearer(_login(other, "bob", "pw-bob-1"))
    bobs_id = other.get("/api/v1/auth/sessions", headers=bob).json()[0]["id"]

    assert http.delete(f"/api/v1/auth/sessions/{bobs_id}", headers=alice).status_code == 404
    assert other.get("/api/v1/users/me", headers=bob).status_code == 200

    mine = http.get("/api/v1/auth/sessions", headers=alice).json()[0]["id"]
    assert http.delete(f"/api/v1/auth/sessions/{mine}", headers=alice).status_code == 204
    assert http.get("/api/v1/users/me", headers=alice).status_code == 401


def test_only_the_hash_of_a_refresh_token_is_stored(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    _login(http, "alice", "pw-alice-1")
    plain = http.cookies.get("aksor_refresh")
    row = _sessions()[0]
    assert plain not in (row.refresh_hash, row.previous_hash or "") and row.refresh_hash == auth_tokens.hash_token(plain)


def test_ended_sessions_are_forgotten_at_the_next_sign_in(http, make_local_user):
    make_local_user("alice", "pw-alice-1", ())
    _login(http, "alice", "pw-alice-1")
    with db.SessionLocal() as session:
        row = session.scalars(select(db.AuthSession)).one()
        row.revoked_at = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
        session.commit()
    _login(TestClient(app), "alice", "pw-alice-1")
    assert len(_sessions()) == 1


# --- throttling ------------------------------------------------------------------------------------


def test_sign_in_attempts_are_throttled_per_account_and_per_address(http, make_local_user, monkeypatch):
    monkeypatch.setenv("LOGIN_ATTEMPTS_PER_MINUTE", "3")
    make_local_user("alice", "pw-alice-1", ())
    for _ in range(3):
        _login(http, "alice", "wrong-guess", expect=401)
    blocked = _login(http, "alice", "pw-alice-1", expect=429)  # even the right password waits out the window
    assert int(blocked.headers["retry-after"]) >= 1 and "Too many" in blocked.json()["detail"]

    # another account from the same address is unaffected until the (looser) address limit
    make_local_user("bob", "pw-bob-1", ())
    _login(http, "bob", "pw-bob-1")
    assert http.get("/api/v1/auth/verify", auth=("bob", "pw-bob-1")).status_code == 200


# --- the schema check at startup ---------------------------------------------------------------------


def _head_revision() -> str:
    """The newest migration -- read from the migrations folder, so adding one doesn't break these tests."""
    from alembic.script import ScriptDirectory

    from app import schema_check

    return ScriptDirectory(str(schema_check._MIGRATIONS)).get_current_head()


def test_a_database_on_a_squashed_away_migration_is_called_out_with_the_fix(tmp_path, monkeypatch, caplog):
    import logging

    from sqlalchemy import create_engine, text

    from app import schema_check

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0004_jdbc_drivers')"))
    monkeypatch.setattr(db, "engine", engine)

    with caplog.at_level(logging.ERROR, logger="aksor_khmer_bi.schema"):
        message = schema_check.check_schema_version()
    assert "0004_jdbc_drivers" in message and f"stamp --purge {_head_revision()}" in message
    assert any("squashed" in record.message for record in caplog.records)


def test_a_current_or_alembic_less_database_is_left_alone(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text

    from app import schema_check

    bare = create_engine(f"sqlite:///{tmp_path / 'bare.db'}")  # built without Alembic, like the test suite's own
    monkeypatch.setattr(db, "engine", bare)
    assert schema_check.check_schema_version() is None

    engine = create_engine(f"sqlite:///{tmp_path / 'ok.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text(f"INSERT INTO alembic_version VALUES ('{_head_revision()}')"))
    monkeypatch.setattr(db, "engine", engine)
    assert schema_check.check_schema_version() is None

    # one migration behind is called out, with the one command that fixes it
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '0001_initial_schema'"))
    assert "alembic upgrade head" in schema_check.check_schema_version()


# --- unhandled errors ---------------------------------------------------------------------------------


def test_an_unhandled_error_answers_json_with_a_reference_and_no_internals(make_local_user, caplog):
    import logging

    from app.main import app as the_app

    async def boom():
        raise RuntimeError("no such table: secret_internal_name")

    the_app.add_api_route("/__boom", boom, methods=["GET"])
    try:
        resp = TestClient(the_app, raise_server_exceptions=False).get("/__boom", headers={"Origin": "http://localhost:5173"})
    finally:
        the_app.router.routes.pop()
    assert resp.status_code == 500 and resp.headers["content-type"].startswith("application/json")
    detail = resp.json()["detail"]
    assert "unexpected error (ref " in detail and "secret_internal_name" not in resp.text
    reference = detail.split("ref ")[1].split(")")[0]
    assert any(reference in record.getMessage() for record in caplog.records)  # the same reference is in the log
