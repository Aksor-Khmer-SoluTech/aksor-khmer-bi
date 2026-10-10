"""New-device sign-in alerts: a browser that has never signed in to an account (its device cookie, not its IP address
or browser version) raises an alert on the account's *other* sessions -- never on its own -- which the owner answers
with "It was me" or "Not me" (sign that session out). See app/auth_events.py and routers/users.py's /me/notifications."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db
from app.auth_events import record_login_success
from app.main import app

PASSWORD = "pw-12345678"
CHROME_WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
CHROME_WINDOWS_UPDATED = CHROME_WINDOWS.replace("128.0.0.0", "129.0.0.0")
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def _browser(user_agent: str) -> TestClient:
    """One browser: its own cookie jar (the device cookie, the refresh cookie)."""
    return TestClient(app, headers={"User-Agent": user_agent})


def _sign_in(browser: TestClient, username: str) -> dict:
    resp = browser.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _alerts(browser: TestClient, headers: dict) -> list[dict]:
    resp = browser.get("/api/v1/users/me/notifications", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_same_browser_is_known_even_after_an_update_or_a_new_network(make_local_user):
    make_local_user("ana", PASSWORD)
    laptop = _browser(CHROME_WINDOWS)
    first = _sign_in(laptop, "ana")
    assert laptop.cookies.get("aksor_device")

    # A browser update changes the User-Agent; the device cookie still says it's the same browser.
    laptop.headers["User-Agent"] = CHROME_WINDOWS_UPDATED
    _sign_in(laptop, "ana")
    assert _alerts(laptop, first) == []

    with db.SessionLocal() as session:
        rows = session.execute(select(db.AuthEvent).where(db.AuthEvent.username == "ana")).scalars().all()
        assert len(rows) == 2 and not any(r.is_new_device for r in rows)
        assert all(r.session_id and r.device_hash for r in rows)
        assert laptop.cookies.get("aksor_device") not in {r.device_hash for r in rows}  # only its hash is stored


def test_a_new_browser_alerts_the_other_sessions_but_not_itself(make_local_user):
    make_local_user("bora", PASSWORD)
    laptop, stranger = _browser(CHROME_WINDOWS), _browser(FIREFOX_LINUX)
    mine = _sign_in(laptop, "bora")
    theirs = _sign_in(stranger, "bora")

    alerts = _alerts(laptop, mine)
    assert len(alerts) == 1
    assert alerts[0]["browser"].startswith("Firefox") and alerts[0]["session_active"] is True

    # Whoever is on the new device doesn't see it, and can't clear it for the owner.
    assert _alerts(stranger, theirs) == []
    assert stranger.post("/api/v1/users/me/notifications/ack", headers=theirs).status_code == 204
    assert stranger.post(f"/api/v1/users/me/notifications/{alerts[0]['id']}/ack", headers=theirs).status_code == 404
    assert len(_alerts(laptop, mine)) == 1


def test_it_was_me_dismisses_the_alert(make_local_user):
    make_local_user("chan", PASSWORD)
    laptop, phone = _browser(CHROME_WINDOWS), _browser(FIREFOX_LINUX)
    mine = _sign_in(laptop, "chan")
    phone_headers = _sign_in(phone, "chan")
    [alert] = _alerts(laptop, mine)

    assert laptop.post(f"/api/v1/users/me/notifications/{alert['id']}/ack", headers=mine).status_code == 204
    assert _alerts(laptop, mine) == []
    assert phone.get("/api/v1/auth/me", headers=phone_headers).status_code == 200  # still signed in

    with db.SessionLocal() as session:
        assert session.execute(
            select(db.AuditEvent).where(db.AuditEvent.action == "auth.signin_confirmed")
        ).scalars().first() is not None


def test_not_me_signs_that_session_out(make_local_user):
    make_local_user("dara", PASSWORD)
    laptop, stranger = _browser(CHROME_WINDOWS), _browser(FIREFOX_LINUX)
    mine = _sign_in(laptop, "dara")
    theirs = _sign_in(stranger, "dara")
    [alert] = _alerts(laptop, mine)

    resp = laptop.post(f"/api/v1/users/me/notifications/{alert['id']}/sign-out", headers=mine)
    assert resp.status_code == 200 and resp.json() == {"signed_out": True}
    assert _alerts(laptop, mine) == []

    # Their access token and their refresh cookie are both dead; mine still works.
    assert stranger.get("/api/v1/auth/me", headers=theirs).status_code == 401
    assert stranger.post("/api/v1/auth/refresh", headers={"X-Aksor-Client": "portal"}).status_code == 401
    assert laptop.get("/api/v1/auth/me", headers=mine).status_code == 200

    with db.SessionLocal() as session:
        row = session.execute(select(db.AuditEvent).where(db.AuditEvent.action == "auth.signin_disowned")).scalars().one()
        assert row.entity_id == alert["session_id"]


def test_someone_elses_alert_is_not_found(make_local_user):
    make_local_user("eng", PASSWORD)
    make_local_user("fong", PASSWORD)
    laptop = _browser(CHROME_WINDOWS)
    mine = _sign_in(laptop, "eng")
    _sign_in(_browser(FIREFOX_LINUX), "eng")
    [alert] = _alerts(laptop, mine)

    other = _browser(CHROME_WINDOWS)
    fong = _sign_in(other, "fong")
    assert other.post(f"/api/v1/users/me/notifications/{alert['id']}/sign-out", headers=fong).status_code == 404
    assert len(_alerts(laptop, mine)) == 1


def test_browsers_known_before_the_upgrade_are_not_alerted(make_local_user):
    """Sign-ins recorded before device cookies existed have no device hash; they still vouch for their exact
    ip_address + user_agent, so the first sign-in after upgrading doesn't alert everyone."""
    user_id, _ = make_local_user("hok", PASSWORD)
    with db.SessionLocal() as session:
        user = session.get(db.User, user_id)
        record_login_success(session, user, ip_address="testclient", user_agent=CHROME_WINDOWS)  # the old, cookie-less row

    laptop = _browser(CHROME_WINDOWS)
    _sign_in(laptop, "hok")
    with db.SessionLocal() as session:
        newest = session.execute(
            select(db.AuthEvent).where(db.AuthEvent.username == "hok").order_by(db.AuthEvent.created_at.desc())
        ).scalars().first()
        assert newest.session_id is not None and newest.is_new_device is False


# --- naming the browser -------------------------------------------------------------------------------------------


def test_brave_is_named_from_its_client_hint_or_the_portals_hint(make_local_user):
    """Brave's User-Agent is Chrome's, unchanged. It names itself in Sec-CH-UA (https, localhost); on plain http the
    portal says so itself (X-Aksor-Browser). Versions show the major number only."""
    make_local_user("kim", PASSWORD)
    hinted = _browser(CHROME_WINDOWS)
    hinted.headers["Sec-CH-UA"] = '"Brave";v="128", "Chromium";v="128", "Not;A=Brand";v="24"'
    first = _sign_in(hinted, "kim")
    portal = _browser(CHROME_WINDOWS)
    portal.headers["X-Aksor-Browser"] = "Brave"
    _sign_in(portal, "kim")
    plain = _browser(CHROME_WINDOWS)
    plain.headers["Sec-CH-UA"] = '"Google Chrome";v="128", "Chromium";v="128", "Not;A=Brand";v="24"'
    plain.headers["X-Aksor-Browser"] = "Netscape"  # not a name the portal can report: ignored
    _sign_in(plain, "kim")

    sessions = hinted.get("/api/v1/auth/sessions", headers=first).json()
    assert sorted(s["browser"] for s in sessions) == ["Brave 128", "Brave 128", "Chrome 128"]
    alerts = _alerts(hinted, first)
    assert sorted(a["browser"] for a in alerts) == ["Brave 128", "Chrome 128"]
