from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def _make_png_bytes(size=(20, 10), color=(255, 0, 0)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _create_folder(headers, name, org_id=ROOT_ORG_ID):
    return client.post("/api/v1/folders", json={"org_id": org_id, "name": name}, headers=headers).json()


def _upload_image(headers, name="logo.png", org_id=ROOT_ORG_ID, folder_id=None, content=None):
    data = {"name": name, "org_id": org_id}
    if folder_id is not None:
        data["folder_id"] = folder_id
    return client.post(
        "/api/v1/images",
        files={"file": ("logo.png", content or _make_png_bytes(), "image/png")},
        data=data,
        headers=headers,
    )


def test_upload_image_at_root(auth_headers):
    resp = _upload_image(auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["width_px"] == 20
    assert body["height_px"] == 10
    assert body["content_type"] == "image/png"


def test_upload_image_into_folder(auth_headers):
    folder = _create_folder(auth_headers, "Logos")
    resp = _upload_image(auth_headers, folder_id=folder["id"])
    assert resp.status_code == 200
    assert resp.json()["folder_id"] == folder["id"]


def test_upload_rejects_non_image_content(auth_headers):
    resp = _upload_image(auth_headers, content=b"not an image at all")
    assert resp.status_code == 400


def test_upload_requires_permission(make_local_user):
    _, headers = make_local_user("noimage", "pw12345", role_names=())
    resp = _upload_image(headers)
    assert resp.status_code == 403


def test_get_image_file_returns_bytes(auth_headers):
    content = _make_png_bytes()
    created = _upload_image(auth_headers, content=content).json()
    resp = client.get(f"/api/v1/images/{created['id']}/file", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == content


def test_delete_image(auth_headers):
    created = _upload_image(auth_headers).json()
    resp = client.delete(f"/api/v1/images/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get(f"/api/v1/images/{created['id']}", headers=auth_headers).status_code == 404


def test_image_visibility_inherits_from_folder_grant(auth_headers, make_local_user):
    folder = _create_folder(auth_headers, "Logos")
    image = _upload_image(auth_headers, folder_id=folder["id"]).json()

    role_resp = client.post("/api/v1/roles", json={"org_id": ROOT_ORG_ID, "name": "ImageViewer"}, headers=auth_headers)
    role_id = role_resp.json()["id"]
    user_id, headers = make_local_user("image_viewer", "pw12345", role_names=())
    client.post("/api/v1/grants/roles", json={"user_id": user_id, "role_id": role_id}, headers=auth_headers)

    # No grant yet -- invisible.
    resp = client.get(f"/api/v1/images/{image['id']}", headers=headers)
    assert resp.status_code == 404

    client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "role", "subject_id": role_id, "folder_id": folder["id"], "permission_level": "view"},
        headers=auth_headers,
    )
    resp = client.get(f"/api/v1/images/{image['id']}", headers=headers)
    assert resp.status_code == 200
