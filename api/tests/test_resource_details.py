"""The Resources details panel's backend: where an image or stylesheet is used, renaming and moving one (dragging it
into a folder), and replacing an image's picture while keeping its id -- every template using it changes with it."""
import io
import json

import pytest
from docx import Document
from fastapi.testclient import TestClient
from PIL import Image

from app import db, image_store, stylesheet_store
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(image_store, "STORE_DIR", tmp_path / "images")
    monkeypatch.setattr(stylesheet_store, "STORE_DIR", tmp_path / "styles")


def png(color=(10, 80, 160)):
    out = io.BytesIO()
    Image.new("RGB", (20, 10), color).save(out, format="PNG")
    return out.getvalue()


def image(headers, name="logo", content=None, folder_id=None):
    data = {"name": name, "org_id": ROOT_ORG_ID, **({"folder_id": folder_id} if folder_id else {})}
    resp = client.post("/api/v1/images", files={"file": ("l.png", content or png(), "image/png")}, data=data, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def folder(headers, name):
    return client.post("/api/v1/folders", json={"org_id": ROOT_ORG_ID, "name": name}, headers=headers).json()


def test_used_by_an_html_mapping_and_a_word_templates_data(auth_headers):
    logo = image(auth_headers)
    css = client.post("/api/v1/stylesheets", files={"file": ("t.css", b"h1{color:red}", "text/css")}, data={"name": "theme", "org_id": ROOT_ORG_ID}, headers=auth_headers).json()
    html = b'<link rel="stylesheet" href="{{ resource(\'theme\') }}"><img src="{{ resource(\'logo\') }}"><img src="{{ resource(\'mark\') }}">'
    client.post("/api/v1/reports", files={"file": ("r.html", html, "text/html")}, headers=auth_headers, data={
        "name": "Receipt", "resource_bindings": json.dumps({"theme": {"kind": "stylesheet", "id": css["id"]}, "logo": {"kind": "image", "id": logo["id"]},
                                                            "mark": {"kind": "image", "id": logo["id"]}})}).raise_for_status()
    d = Document(); d.add_paragraph("{{ LOGO }}"); buf = io.BytesIO(); d.save(buf)
    word = client.post("/api/v1/reports", files={"file": ("w.docx", buf.getvalue(), "application/octet-stream")}, data={"name": "Form"}, headers=auth_headers).json()
    client.patch(f"/api/v1/reports/{word['report_id']}", json={"sample_context": {"LOGO": {"image_id": logo["id"], "width_mm": 30}}}, headers=auth_headers)
    used = client.get(f"/api/v1/images/{logo['id']}/usage", headers=auth_headers).json()
    assert [(u["name"], u["as"], u["in_data"]) for u in used] == [("Form", [], True), ("Receipt", ["logo", "mark"], False)]
    assert [u["as"] for u in client.get(f"/api/v1/stylesheets/{css['id']}/usage", headers=auth_headers).json()] == [["theme"]]
    assert client.get(f"/api/v1/images/{image(auth_headers, 'unused', png((1, 1, 1)))['id']}/usage", headers=auth_headers).json() == []


def test_move_and_rename(auth_headers):
    logo = image(auth_headers)
    target = folder(auth_headers, "Brand")
    moved = client.patch(f"/api/v1/images/{logo['id']}", json={"folder_id": target["id"]}, headers=auth_headers)
    assert moved.status_code == 200 and moved.json()["folder_id"] == target["id"] and moved.json()["id"] == logo["id"]
    renamed = client.patch(f"/api/v1/images/{logo['id']}", json={"name": "brand-logo"}, headers=auth_headers).json()
    assert renamed["name"] == "brand-logo" and renamed["folder_id"] == target["id"]  # omitted folder_id: stays put
    back = client.patch(f"/api/v1/images/{logo['id']}", json={"folder_id": None}, headers=auth_headers).json()
    assert back["folder_id"] is None
    assert client.patch(f"/api/v1/images/{logo['id']}", json={"folder_id": "nope"}, headers=auth_headers).status_code == 404
    css = client.post("/api/v1/stylesheets", files={"file": ("t.scss", b"$c:red; h1{color:$c}", "text/plain")}, data={"name": "theme", "org_id": ROOT_ORG_ID}, headers=auth_headers).json()
    assert client.patch(f"/api/v1/stylesheets/{css['id']}", json={"folder_id": target["id"]}, headers=auth_headers).json()["folder_id"] == target["id"]
    with db.SessionLocal() as session:
        summaries = [e.summary for e in session.query(db.AuditEvent).filter(db.AuditEvent.action.in_(["image.update", "stylesheet.update"])).order_by(db.AuditEvent.created_at)]
    assert summaries == ['Moved image "logo" to Brand', 'Renamed image "brand-logo"', 'Moved image "brand-logo" to (top level)', 'Moved stylesheet "theme" to Brand']


def test_moving_needs_manage_on_both_folders(auth_headers, make_local_user):
    logo = image(auth_headers)
    target = folder(auth_headers, "Brand")
    _, viewer = make_local_user("viewer", "pw-viewer-1", ("ROLE_REPORT_VIEWER",))
    assert client.patch(f"/api/v1/images/{logo['id']}", json={"folder_id": target["id"]}, headers=viewer).status_code in (403, 404)


def test_replacing_an_image_keeps_its_id(auth_headers):
    logo = image(auth_headers)
    resp = client.put(f"/api/v1/images/{logo['id']}/file", files={"file": ("new.png", png((200, 0, 0)), "image/png")}, headers=auth_headers)
    assert resp.status_code == 200 and resp.json()["id"] == logo["id"] and resp.json()["sha256"] != logo["sha256"]
    assert Image.open(io.BytesIO(client.get(f"/api/v1/images/{logo['id']}/file", headers=auth_headers).content)).getpixel((0, 0)) == (200, 0, 0)
    bad = client.put(f"/api/v1/images/{logo['id']}/file", files={"file": ("x.png", b"not an image", "image/png")}, headers=auth_headers)
    assert bad.status_code == 400
