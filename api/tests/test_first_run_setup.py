"""First-run setup: the PORTAL_PASSWORD that `deployment.sh init` generates is a one-time key. Signed in with it while
no administrator account exists, everything but the setup is refused; POST /auth/setup-admin turns it into a real
administrator account with the same name and the person's own password, and retires the .env password for that name.
See app/auth.py (setup_required) and app/routers/auth.py (setup_admin)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, db
from app.main import app
from app.rbac import SYSTEM_ADMIN_ROLE_NAME

from .conftest import TEST_PASSWORD, TEST_USERNAME

NEW_PASSWORD = "my-own-Passw0rd!"


@pytest.fixture(autouse=True)
def gate_on(monkeypatch):
    monkeypatch.setattr(auth, "FIRST_RUN_SETUP", True)


@pytest.fixture
def http():
    return TestClient(app)


def _login(http, username, password, expect=200):
    resp = http.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == expect, resp.text
    return resp


def _bearer(resp):
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_the_generated_password_only_leads_to_the_setup(http):
    resp = _login(http, TEST_USERNAME, TEST_PASSWORD)
    user = resp.json()["user"]
    assert user["setup_required"] is True and user["must_change_password"] is True

    refused = http.get("/api/v1/users", headers=_bearer(resp))
    assert refused.status_code == 403 and refused.json()["detail"] == "PASSWORD_CHANGE_REQUIRED"


def test_setup_creates_your_administrator_account_and_retires_the_generated_password(http):
    first = _login(http, TEST_USERNAME, TEST_PASSWORD)

    weak = http.post("/api/v1/auth/setup-admin", json={"new_password": "short"}, headers=_bearer(first))
    assert weak.status_code == 400

    done = http.post("/api/v1/auth/setup-admin", json={"new_password": NEW_PASSWORD}, headers=_bearer(first))
    assert done.status_code == 200, done.text
    me = done.json()["user"]
    assert me["username"] == TEST_USERNAME and me["is_superuser"] is True
    assert me["setup_required"] is False and me["must_change_password"] is False
    assert "aksor_refresh=" in done.headers["set-cookie"]

    # Signed in as the new account straight away: the console and the profile work.
    assert http.get("/api/v1/users", headers=_bearer(done)).status_code == 200
    profile = http.get("/api/v1/users/me", headers=_bearer(done))
    assert profile.status_code == 200 and profile.json()["username"] == TEST_USERNAME

    # The break-glass session the setup started from is over.
    assert http.get("/api/v1/auth/me", headers=_bearer(first)).status_code == 401

    # The generated .env password no longer signs in; your own does.
    _login(http, TEST_USERNAME, TEST_PASSWORD, expect=401)
    again = _login(http, TEST_USERNAME, NEW_PASSWORD)
    assert again.json()["user"]["setup_required"] is False

    with db.SessionLocal() as session:
        row = session.execute(select(db.User).where(db.User.username == TEST_USERNAME)).scalar_one()
        assert row.auth_source == "local" and row.must_change_password is False
        roles = session.execute(
            select(db.Role.name).join(db.UserRoleAssignment, db.UserRoleAssignment.role_id == db.Role.id)
            .where(db.UserRoleAssignment.user_id == row.id)
        ).scalars().all()
        assert roles == [SYSTEM_ADMIN_ROLE_NAME]
        audit_rows = session.execute(
            select(db.AuditEvent).where(db.AuditEvent.action == "user.create", db.AuditEvent.entity_id == row.id)
        ).scalars().all()
        assert len(audit_rows) == 1


def test_setup_happens_once(http):
    first = _login(http, TEST_USERNAME, TEST_PASSWORD)
    done = http.post("/api/v1/auth/setup-admin", json={"new_password": NEW_PASSWORD}, headers=_bearer(first))
    assert done.status_code == 200
    twice = http.post("/api/v1/auth/setup-admin", json={"new_password": "another-Passw0rd"}, headers=_bearer(done))
    assert twice.status_code == 409


def test_once_an_administrator_exists_a_recovery_login_is_not_gated(http, monkeypatch, make_local_user):
    make_local_user("boss", "boss-Passw0rd", (SYSTEM_ADMIN_ROLE_NAME,))
    # The documented recovery: a *different* PORTAL_USERNAME in .env.
    monkeypatch.setenv("PORTAL_USERNAME", "recovery")
    monkeypatch.setenv("PORTAL_PASSWORD", "recovery-Passw0rd")
    resp = _login(http, "recovery", "recovery-Passw0rd")
    assert resp.json()["user"]["setup_required"] is False
    assert http.get("/api/v1/users", headers=_bearer(resp)).status_code == 200
    # ...and it can't run the setup: there's already an administrator.
    assert http.post("/api/v1/auth/setup-admin", json={"new_password": NEW_PASSWORD}, headers=_bearer(resp)).status_code == 409


def test_a_database_user_cannot_run_the_setup(http, make_local_user):
    make_local_user("alice", "alice-Passw0rd", ("ROLE_REPORT_VIEWER",))
    resp = _login(http, "alice", "alice-Passw0rd")
    assert http.post("/api/v1/auth/setup-admin", json={"new_password": NEW_PASSWORD}, headers=_bearer(resp)).status_code == 409
