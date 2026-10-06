import base64
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import db
from app.auth_events import parse_user_agent, record_login_success
from app.main import app

client = TestClient(app)

CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def _auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# --- parse_user_agent --------------------------------------------------


def test_parse_user_agent_chrome_windows_desktop():
    parsed = parse_user_agent(CHROME_WINDOWS)
    assert parsed.browser.startswith("Chrome")
    assert parsed.os == "Windows"
    assert parsed.device_type == "desktop"


def test_parse_user_agent_safari_iphone_mobile():
    parsed = parse_user_agent(SAFARI_IPHONE)
    assert parsed.browser.startswith("Safari")
    assert parsed.os == "iOS"
    assert parsed.device_type == "mobile"


def test_parse_user_agent_unknown_falls_back():
    parsed = parse_user_agent(None)
    assert parsed.browser == "Unknown"
    assert parsed.os == "Unknown"
    assert parsed.device_type == "desktop"


# --- record_login_success ---------------------------------------------


def test_record_login_success_tolerates_many_historical_matches(make_local_user):
    """Regression: a real device accumulates a *new* success row every
    time SESSION_RENEW_WINDOW lapses between sign-ins from the same
    fingerprint, so after enough real-world use there are routinely many
    prior rows for one (user, ip, user_agent) -- signing in again must
    not blow up with sqlalchemy.exc.MultipleResultsFound, which
    `.scalar_one_or_none()` (without a `.limit(1)`) previously did.
    """
    user_id, _ = make_local_user("manyrows1", "pw12345", role_names=())
    old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    with db.SessionLocal() as session:
        user = session.get(db.User, user_id)
        for _ in range(3):
            session.add(
                db.AuthEvent(
                    user_id=user_id,
                    org_id=user.org_id,
                    username=user.username,
                    success=True,
                    ip_address="127.0.0.1",
                    user_agent="TestAgent/1.0",
                    is_new_device=False,
                    created_at=old,
                    last_seen_at=old,
                )
            )
        session.commit()

        event = record_login_success(session, user, ip_address="127.0.0.1", user_agent="TestAgent/1.0")
        assert event.is_new_device is False


# --- /users/me/sessions --------------------------------------------------


def test_verify_records_a_session_visible_at_me_sessions(make_local_user):
    _, headers = make_local_user("sess1", "pw12345", role_names=())
    headers = {**headers, "User-Agent": CHROME_WINDOWS}

    client.get("/api/v1/auth/verify", headers=headers)
    resp = client.get("/api/v1/users/me/sessions", headers=headers)

    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1
    assert sessions[0]["browser"].startswith("Chrome")
    assert sessions[0]["os"] == "Windows"
    assert sessions[0]["device_type"] == "desktop"
    assert sessions[0]["is_current"] is True


def test_repeated_verify_within_window_renews_one_session_not_many(make_local_user):
    _, headers = make_local_user("sess2", "pw12345", role_names=())
    headers = {**headers, "User-Agent": CHROME_WINDOWS}

    for _ in range(3):
        client.get("/api/v1/auth/verify", headers=headers)

    resp = client.get("/api/v1/users/me/sessions", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_different_device_opens_a_second_session(make_local_user):
    _, headers = make_local_user("sess3", "pw12345", role_names=())

    client.get("/api/v1/auth/verify", headers={**headers, "User-Agent": CHROME_WINDOWS})
    client.get("/api/v1/auth/verify", headers={**headers, "User-Agent": FIREFOX_LINUX})

    resp = client.get("/api/v1/users/me/sessions", headers={**headers, "User-Agent": FIREFOX_LINUX})
    assert resp.status_code == 200
    browsers = {s["browser"].split(" ")[0] for s in resp.json()}
    assert browsers == {"Chrome", "Firefox"}


def test_sessions_requires_a_real_profile_not_break_glass(auth_headers):
    resp = client.get("/api/v1/users/me/sessions", headers=auth_headers)
    assert resp.status_code == 404


# --- /users/me/auth-log --------------------------------------------------


def test_auth_log_includes_success_and_failure(make_local_user):
    _, headers = make_local_user("sess4", "pw12345", role_names=())
    client.get("/api/v1/auth/verify", headers={**headers, "User-Agent": CHROME_WINDOWS})
    client.get("/api/v1/auth/verify", headers=_auth_header("sess4", "wrongpassword"))

    resp = client.get("/api/v1/users/me/auth-log", headers=headers)
    assert resp.status_code == 200
    entries = resp.json()
    assert any(e["success"] is True for e in entries)
    assert any(e["success"] is False for e in entries)


# --- /users/me/notifications ---------------------------------------------


def test_new_device_signin_surfaces_as_notification_then_can_be_acked(make_local_user):
    _, headers = make_local_user("sess5", "pw12345", role_names=())
    headers = {**headers, "User-Agent": CHROME_WINDOWS}
    client.get("/api/v1/auth/verify", headers=headers)

    resp = client.get("/api/v1/users/me/notifications", headers=headers)
    assert resp.status_code == 200
    notifications = resp.json()
    assert len(notifications) == 1
    assert notifications[0]["is_new_device"] is True

    ack = client.post("/api/v1/users/me/notifications/ack", headers=headers)
    assert ack.status_code == 204

    resp2 = client.get("/api/v1/users/me/notifications", headers=headers)
    assert resp2.json() == []


def test_renewed_session_is_not_a_repeat_notification(make_local_user):
    _, headers = make_local_user("sess6", "pw12345", role_names=())
    headers = {**headers, "User-Agent": CHROME_WINDOWS}
    client.get("/api/v1/auth/verify", headers=headers)
    client.post("/api/v1/users/me/notifications/ack", headers=headers)

    client.get("/api/v1/auth/verify", headers=headers)
    resp = client.get("/api/v1/users/me/notifications", headers=headers)
    assert resp.json() == []


def test_disabling_notify_new_signin_hides_future_notifications(make_local_user):
    _, headers = make_local_user("sess7", "pw12345", role_names=())
    headers = {**headers, "User-Agent": CHROME_WINDOWS}

    patched = client.patch("/api/v1/users/me", json={"notify_new_signin": False}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["notify_new_signin"] is False

    client.get("/api/v1/auth/verify", headers=headers)
    resp = client.get("/api/v1/users/me/notifications", headers=headers)
    assert resp.json() == []
