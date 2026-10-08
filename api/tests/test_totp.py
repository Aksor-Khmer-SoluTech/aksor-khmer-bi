import base64

import pyotp
from fastapi.testclient import TestClient

from app import totp
from app.main import app

client = TestClient(app)


def _auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _code_at_step(secret: str, step: int) -> str:
    return pyotp.TOTP(secret).at(step * 30)


def _current_step() -> int:
    return totp.now() // 30


def _bearer(username: str, password: str, code: str) -> dict:
    """Sign in through /auth/login with a 2FA code and return the Bearer header. Once an account has 2FA
    it can no longer use HTTP Basic on the other routes (a script can't supply the code), so this is how
    a test acts as that account afterwards."""
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password, "totp_code": code})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _enroll_and_confirm(headers: dict) -> str:
    """Enroll + confirm 2FA for the account behind `headers`, returning
    its now-confirmed secret. Confirms with the *previous* step's code --
    the window accepts it -- so the current and next steps stay free for
    a follow-up login and a disable (replay protection rejects any step at
    or before the last one used; see _code_at_step/_current_step).
    """
    enroll = client.post("/api/v1/users/me/totp/enroll", headers=headers)
    assert enroll.status_code == 200, enroll.text
    secret = enroll.json()["secret"]
    confirm = client.post(
        "/api/v1/users/me/totp/confirm", json={"code": _code_at_step(secret, _current_step() - 1)}, headers=headers
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["totp_enabled"] is True
    return secret


# --- enroll / confirm / disable ------------------------------------------


def test_enroll_returns_secret_and_qr_but_does_not_enable_yet(make_local_user):
    _, headers = make_local_user("totp1", "pw12345", role_names=())
    resp = client.post("/api/v1/users/me/totp/enroll", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["secret"]) >= 16
    assert body["qr_code_data_url"].startswith("data:image/png;base64,")
    assert body["otpauth_url"].startswith("otpauth://totp/")

    me = client.get("/api/v1/users/me", headers=headers).json()
    assert me["totp_enabled"] is False


def test_confirm_with_correct_code_enables_2fa(make_local_user):
    _, headers = make_local_user("totp2", "pw12345", role_names=())
    _enroll_and_confirm(headers)


def test_confirm_with_wrong_code_rejected(make_local_user):
    _, headers = make_local_user("totp3", "pw12345", role_names=())
    client.post("/api/v1/users/me/totp/enroll", headers=headers)
    resp = client.post("/api/v1/users/me/totp/confirm", json={"code": "000000"}, headers=headers)
    assert resp.status_code == 400

    me = client.get("/api/v1/users/me", headers=headers).json()
    assert me["totp_enabled"] is False


def test_enroll_blocked_once_already_enabled(make_local_user):
    _, headers = make_local_user("totp4", "pw12345", role_names=())
    secret = _enroll_and_confirm(headers)
    token = _bearer("totp4", "pw12345", _code_at_step(secret, _current_step()))
    resp = client.post("/api/v1/users/me/totp/enroll", headers=token)
    assert resp.status_code == 409


def test_disable_requires_valid_code(make_local_user):
    _, headers = make_local_user("totp5", "pw12345", role_names=())
    secret = _enroll_and_confirm(headers)
    token = _bearer("totp5", "pw12345", _code_at_step(secret, _current_step()))

    wrong = client.post("/api/v1/users/me/totp/disable", json={"code": "000000"}, headers=token)
    assert wrong.status_code == 400

    resp = client.post(
        "/api/v1/users/me/totp/disable", json={"code": _code_at_step(secret, _current_step() + 1)}, headers=token
    )
    assert resp.status_code == 200
    assert resp.json()["totp_enabled"] is False


def test_totp_endpoints_404_for_break_glass(auth_headers):
    assert client.post("/api/v1/users/me/totp/enroll", headers=auth_headers).status_code == 404
    assert client.post("/api/v1/users/me/totp/confirm", json={"code": "000000"}, headers=auth_headers).status_code == 404
    assert client.post("/api/v1/users/me/totp/disable", json={"code": "000000"}, headers=auth_headers).status_code == 404


# --- replay protection -----------------------------------------------------


def test_same_code_cannot_be_reused_for_confirm_then_disable(make_local_user):
    _, headers = make_local_user("totp6", "pw12345", role_names=())
    enroll = client.post("/api/v1/users/me/totp/enroll", headers=headers).json()
    secret = enroll["secret"]
    code = pyotp.TOTP(secret).now()

    confirm = client.post("/api/v1/users/me/totp/confirm", json={"code": code}, headers=headers)
    assert confirm.status_code == 200

    # Replaying the exact same code that just confirmed enrollment must
    # not also work for a second, unrelated action (disable).
    token = _bearer("totp6", "pw12345", _code_at_step(secret, _current_step() + 1))
    replay = client.post("/api/v1/users/me/totp/disable", json={"code": code}, headers=token)
    assert replay.status_code == 400


# --- login-gate enforcement (routers/auth.py's /auth/verify) --------------


def test_verify_without_login_flag_never_asks_for_totp(make_local_user):
    """/auth/verify without login=true is a plain password check and doesn't ask for a code, even for a 2FA
    account -- it's the narrower, older check; /auth/login is what enforces the second factor."""
    _, headers = make_local_user("totp7", "pw12345", role_names=())
    _enroll_and_confirm(headers)
    resp = client.get("/api/v1/auth/verify", headers=headers)
    assert resp.status_code == 200


def test_login_without_code_returns_totp_required_sentinel(make_local_user):
    _, headers = make_local_user("totp8", "pw12345", role_names=())
    _enroll_and_confirm(headers)
    resp = client.get("/api/v1/auth/verify?login=true", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "2FA_REQUIRED"


def test_login_with_wrong_code_rejected_and_logged(make_local_user):
    _, headers = make_local_user("totp9", "pw12345", role_names=())
    secret = _enroll_and_confirm(headers)
    resp = client.get("/api/v1/auth/verify?login=true&totp_code=000000", headers=headers)
    assert resp.status_code == 401

    token = _bearer("totp9", "pw12345", _code_at_step(secret, _current_step()))
    log = client.get("/api/v1/users/me/auth-log", headers=token).json()
    assert any(not e["success"] for e in log)


def test_login_with_correct_code_succeeds(make_local_user):
    _, headers = make_local_user("totp10", "pw12345", role_names=())
    secret = _enroll_and_confirm(headers)
    code = _code_at_step(secret, _current_step() + 1)
    resp = client.get(f"/api/v1/auth/verify?login=true&totp_code={code}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is True


def test_login_rejects_password_only_account_without_2fa_setup(make_local_user):
    """Sanity check the gate doesn't false-positive for an account that
    never enrolled at all."""
    _, headers = make_local_user("totp11", "pw12345", role_names=())
    resp = client.get("/api/v1/auth/verify?login=true", headers=headers)
    assert resp.status_code == 200


# --- admin reset (lost-authenticator recovery) ----------------------------


def test_admin_reset_totp_clears_enrollment(auth_headers, make_local_user):
    user_id, headers = make_local_user("totp12", "pw12345", role_names=())
    _enroll_and_confirm(headers)

    resp = client.patch(f"/api/v1/users/{user_id}", json={"reset_totp": True}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["totp_enabled"] is False

    # And the login gate no longer demands a code.
    verify = client.get("/api/v1/auth/verify?login=true", headers=headers)
    assert verify.status_code == 200


# --- the secret at rest -----------------------------------------------------


def _stored_secret(user_id: str) -> str:
    from app import db

    with db.SessionLocal() as session:
        return session.get(db.User, user_id).totp_secret


def test_the_secret_is_stored_encrypted_and_still_checks_codes(make_local_user):
    user_id, headers = make_local_user("totp20", "pw12345", role_names=())
    secret = _enroll_and_confirm(headers)

    stored = _stored_secret(user_id)
    assert stored.startswith("v1:") and secret not in stored  # a copy of the database doesn't hold the secret
    token = _bearer("totp20", "pw12345", _code_at_step(secret, _current_step()))
    assert client.get("/api/v1/users/me", headers=token).status_code == 200


def test_a_secret_saved_before_encryption_still_works_and_is_encrypted_at_startup(make_local_user):
    from app import db

    user_id, headers = make_local_user("totp21", "pw12345", role_names=())
    secret = _enroll_and_confirm(headers)
    with db.SessionLocal() as session:  # put it back the way an older version stored it
        session.get(db.User, user_id).totp_secret = secret
        session.commit()

    assert totp.verify_totp_code(_stored_secret(user_id), _code_at_step(secret, _current_step()), None) is not None
    with db.SessionLocal() as session:
        assert totp.encrypt_legacy_secrets(session) == 1
        assert totp.encrypt_legacy_secrets(session) == 0  # idempotent
    stored = _stored_secret(user_id)
    assert stored.startswith("v1:") and secret not in stored
    assert totp.verify_totp_code(stored, _code_at_step(secret, _current_step()), None) is not None


def test_a_secret_that_cant_be_decrypted_never_matches(make_local_user, monkeypatch):
    from app import secret_store

    user_id, headers = make_local_user("totp22", "pw12345", role_names=())
    secret = _enroll_and_confirm(headers)
    stored = _stored_secret(user_id)

    monkeypatch.setenv(secret_store.KEY_ENV, secret_store.Fernet.generate_key().decode())  # "the key changed"
    assert totp.verify_totp_code(stored, _code_at_step(secret, _current_step()), None) is None
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "totp22", "password": "pw12345", "totp_code": _code_at_step(secret, _current_step())},
    )
    assert resp.status_code == 401  # fails closed; an administrator's reset_totp is the way back


def test_starting_the_api_encrypts_a_legacy_secret(make_local_user):
    from app import db, secret_store
    from app.main import app as the_app

    user_id, _ = make_local_user("totp23", "pw12345", role_names=())
    with db.SessionLocal() as session:
        row = session.get(db.User, user_id)
        row.totp_secret, row.totp_enabled = "JBSWY3DPEHPK3PXP", True
        session.commit()
    with TestClient(the_app):  # entering the client runs the app's startup
        pass
    stored = _stored_secret(user_id)
    assert stored.startswith("v1:") and secret_store.decrypt(stored) == "JBSWY3DPEHPK3PXP"
