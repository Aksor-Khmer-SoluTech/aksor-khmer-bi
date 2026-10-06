import io

from fastapi.testclient import TestClient
from PIL import Image

from app import avatar_store
from app.main import app

client = TestClient(app)


def _png_bytes(size=(64, 64), color=(200, 50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_upload_avatar_then_fetch_it_back(make_local_user):
    _, headers = make_local_user("avatar1", "pw12345", role_names=())

    resp = client.put(
        "/api/v1/users/me/avatar", files={"file": ("photo.png", _png_bytes(), "image/png")}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["avatar_content_type"] in ("image/png", "image/jpeg")

    fetched = client.get("/api/v1/users/me/avatar", headers=headers)
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] in ("image/png", "image/jpeg")
    assert len(fetched.content) > 0


def test_avatar_is_downscaled_to_max_dimension(make_local_user):
    _, headers = make_local_user("avatar2", "pw12345", role_names=())
    client.put(
        "/api/v1/users/me/avatar",
        files={"file": ("big.png", _png_bytes(size=(2000, 1200)), "image/png")},
        headers=headers,
    )
    fetched = client.get("/api/v1/users/me/avatar", headers=headers)
    with Image.open(io.BytesIO(fetched.content)) as img:
        assert max(img.size) <= avatar_store._MAX_DIMENSION


def test_upload_rejects_non_image_content(make_local_user):
    _, headers = make_local_user("avatar3", "pw12345", role_names=())
    resp = client.put(
        "/api/v1/users/me/avatar",
        files={"file": ("not-an-image.txt", b"just some text, not an image", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 400


def test_upload_rejects_oversized_file(make_local_user, monkeypatch):
    monkeypatch.setattr(avatar_store, "_MAX_UPLOAD_BYTES", 100)
    _, headers = make_local_user("avatar4", "pw12345", role_names=())
    resp = client.put(
        "/api/v1/users/me/avatar", files={"file": ("photo.png", _png_bytes(), "image/png")}, headers=headers
    )
    assert resp.status_code == 400


def test_get_avatar_404s_when_none_uploaded(make_local_user):
    _, headers = make_local_user("avatar5", "pw12345", role_names=())
    resp = client.get("/api/v1/users/me/avatar", headers=headers)
    assert resp.status_code == 404


def test_delete_avatar_clears_it(make_local_user):
    _, headers = make_local_user("avatar6", "pw12345", role_names=())
    client.put("/api/v1/users/me/avatar", files={"file": ("photo.png", _png_bytes(), "image/png")}, headers=headers)

    resp = client.delete("/api/v1/users/me/avatar", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["avatar_content_type"] is None

    assert client.get("/api/v1/users/me/avatar", headers=headers).status_code == 404


def test_avatar_endpoints_404_for_break_glass(auth_headers):
    assert client.get("/api/v1/users/me/avatar", headers=auth_headers).status_code == 404
    assert client.delete("/api/v1/users/me/avatar", headers=auth_headers).status_code == 404
    resp = client.put(
        "/api/v1/users/me/avatar", files={"file": ("photo.png", _png_bytes(), "image/png")}, headers=auth_headers
    )
    assert resp.status_code == 404
