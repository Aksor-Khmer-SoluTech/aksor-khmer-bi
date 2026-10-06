import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import db
from app.main import app
from app.models import settings as settings_models
from app.routers import users as users_router

client = TestClient(app)

URL = "/api/v1/users/me/settings"


def _row_count(user_id: str) -> int:
    with db.SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(db.UserSetting).where(db.UserSetting.user_id == user_id))


def test_settings_start_empty(make_local_user):
    _, headers = make_local_user("settings1", "pw12345")
    resp = client.get(URL, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {}


@pytest.mark.parametrize(
    "value",
    ["dark", 3, 1.5, True, ["a", 1, None], {"nested": {"list": [1, 2, 3]}}, "ខ្មែរ"],
)
def test_put_then_get_roundtrips_any_json_value(make_local_user, value):
    _, headers = make_local_user("settings2", "pw12345")
    put = client.put(f"{URL}/some_setting", json={"value": value}, headers=headers)
    assert put.status_code == 200
    assert put.json()["code"] == "some_setting"
    assert put.json()["value"] == value

    assert client.get(URL, headers=headers).json() == {"some_setting": value}


def test_put_overwrites_in_place_instead_of_adding_a_row(make_local_user):
    user_id, headers = make_local_user("settings3", "pw12345")
    client.put(f"{URL}/report_preview_layout", json={"value": "left"}, headers=headers)
    client.put(f"{URL}/report_preview_layout", json={"value": "fullscreen"}, headers=headers)

    assert client.get(URL, headers=headers).json() == {"report_preview_layout": "fullscreen"}
    assert _row_count(user_id) == 1


def test_settings_are_isolated_per_user(make_local_user):
    _, alice = make_local_user("alice_s", "pw12345")
    _, bob = make_local_user("bob_s", "pw12345")
    client.put(f"{URL}/theme_mode", json={"value": "dark"}, headers=alice)

    assert client.get(URL, headers=alice).json() == {"theme_mode": "dark"}
    assert client.get(URL, headers=bob).json() == {}

    client.put(f"{URL}/theme_mode", json={"value": "light"}, headers=bob)
    assert client.get(URL, headers=alice).json() == {"theme_mode": "dark"}


def test_delete_clears_a_setting_and_is_idempotent(make_local_user):
    _, headers = make_local_user("settings4", "pw12345")
    client.put(f"{URL}/theme_accent", json={"value": "teal"}, headers=headers)

    assert client.delete(f"{URL}/theme_accent", headers=headers).status_code == 204
    assert client.get(URL, headers=headers).json() == {}
    # Clearing something that isn't set (or was just cleared) is fine.
    assert client.delete(f"{URL}/theme_accent", headers=headers).status_code == 204


@pytest.mark.parametrize("bad_code", ["UPPER", "has-dash", "1starts_with_digit", "a" * 65, "with space"])
def test_invalid_code_is_rejected(make_local_user, bad_code):
    _, headers = make_local_user("settings5", "pw12345")
    assert client.put(f"{URL}/{bad_code}", json={"value": "x"}, headers=headers).status_code == 422
    assert client.delete(f"{URL}/{bad_code}", headers=headers).status_code == 422


def test_missing_value_is_rejected(make_local_user):
    _, headers = make_local_user("settings6", "pw12345")
    assert client.put(f"{URL}/x", json={}, headers=headers).status_code == 422


def test_null_value_is_rejected(make_local_user):
    _, headers = make_local_user("settings7", "pw12345")
    resp = client.put(f"{URL}/x", json={"value": None}, headers=headers)
    assert resp.status_code == 422
    assert "DELETE" in resp.text


@pytest.mark.parametrize("raw_body", ['{"value": NaN}', '{"value": Infinity}', '{"value": [1, {"n": NaN}]}'])
def test_non_finite_number_is_rejected_with_a_clean_422(make_local_user, raw_body):
    user_id, headers = make_local_user("settings8", "pw12345")
    # NaN/Infinity parse from a request body (Python's json accepts them)
    # but aren't valid JSON -- PostgreSQL's JSON type would refuse them at
    # insert time, and SQLite would store one and then fail every read.
    # Must come back as a normal 422, not a crash rendering the error.
    resp = client.put(f"{URL}/x", content=raw_body, headers={**headers, "Content-Type": "application/json"})
    assert resp.status_code == 422
    assert "NaN" in resp.json()["detail"]
    assert _row_count(user_id) == 0


def test_oversized_value_is_rejected(make_local_user):
    _, headers = make_local_user("settings9", "pw12345")
    too_big = "x" * (settings_models.MAX_SETTING_VALUE_BYTES + 1)
    assert client.put(f"{URL}/x", json={"value": too_big}, headers=headers).status_code == 422


def test_per_user_limit_blocks_new_codes_but_not_updates(make_local_user, monkeypatch):
    monkeypatch.setattr(users_router, "_MAX_SETTINGS_PER_USER", 2)
    _, headers = make_local_user("settings10", "pw12345")
    assert client.put(f"{URL}/one", json={"value": 1}, headers=headers).status_code == 200
    assert client.put(f"{URL}/two", json={"value": 2}, headers=headers).status_code == 200

    assert client.put(f"{URL}/three", json={"value": 3}, headers=headers).status_code == 400
    # Already at the limit, but rewriting an existing code doesn't add a row.
    assert client.put(f"{URL}/one", json={"value": 11}, headers=headers).status_code == 200
    assert client.get(URL, headers=headers).json() == {"one": 11, "two": 2}


def test_concurrent_first_write_of_the_same_code_retries_as_an_update(make_local_user, monkeypatch):
    user_id, headers = make_local_user("settings11", "pw12345")
    real_commit = Session.commit
    raced = {"done": False}

    def racing_commit(self):
        # Simulate a second request landing its own first write of the same
        # (user, code) between this request's SELECT and its INSERT -- the
        # unique constraint then rejects this request's insert.
        if not raced["done"] and any(isinstance(obj, db.UserSetting) for obj in self.new):
            raced["done"] = True
            with db.SessionLocal() as other:
                other.add(
                    db.UserSetting(user_id=user_id, code="theme_mode", value="dark", created_at="t", updated_at="t")
                )
                real_commit(other)
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", racing_commit)

    resp = client.put(f"{URL}/theme_mode", json={"value": "light"}, headers=headers)

    assert raced["done"]
    assert resp.status_code == 200
    assert resp.json()["value"] == "light"
    assert client.get(URL, headers=headers).json() == {"theme_mode": "light"}
    assert _row_count(user_id) == 1


def test_break_glass_login_has_no_settings(auth_headers):
    # The env-var break-glass credential has no `users` row to attach
    # settings to -- same 404 every other /users/me/* endpoint gives it.
    assert client.get(URL, headers=auth_headers).status_code == 404
    assert client.put(f"{URL}/x", json={"value": 1}, headers=auth_headers).status_code == 404
    assert client.delete(f"{URL}/x", headers=auth_headers).status_code == 404


def test_settings_require_authentication():
    assert client.get(URL).status_code == 401
    assert client.put(f"{URL}/x", json={"value": 1}).status_code == 401
    assert client.delete(f"{URL}/x").status_code == 401
