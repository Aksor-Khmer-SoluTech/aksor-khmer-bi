"""Reports and Resources (folders, images, stylesheets) stay inside their organization.

`report:manage` and `folder:manage` are permissions an organization's own admin roles hold -- they cover the reports
and folders *of that organization*, not anyone else's. Addressing another organization's report, folder, image or
stylesheet by id answers 404, the same as an id that doesn't exist, and so does granting access to one.
"""
from io import BytesIO

from docx import Document

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)

OTHER = "acme"


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), (0, 128, 0)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def other_org_resources(auth_headers):
    """A folder, an image and a stylesheet in another organization, made by the server-wide admin."""
    client.post("/api/v1/organizations", json={"id": OTHER, "name": "Acme"}, headers=auth_headers)
    folder = client.post("/api/v1/folders", json={"org_id": OTHER, "name": "Acme private"}, headers=auth_headers).json()
    image = client.post(
        "/api/v1/images", files={"file": ("a.png", _png(), "image/png")},
        data={"name": "Acme logo", "org_id": OTHER, "folder_id": folder["id"]}, headers=auth_headers,
    ).json()
    sheet = client.post(
        "/api/v1/stylesheets", files={"file": ("a.css", b"body { color: red; }", "text/css")},
        data={"name": "Acme style", "org_id": OTHER, "folder_id": folder["id"]}, headers=auth_headers,
    ).json()
    assert {"id"} <= folder.keys() and {"id"} <= image.keys() and {"id"} <= sheet.keys(), (folder, image, sheet)
    return folder, image, sheet


@pytest.fixture
def root_org_admin(make_local_user):
    """(user_id, headers) of the root organization's admin -- holds report:manage and folder:manage there."""
    return make_local_user("rootorgadmin", "pw12345", role_names=("ROLE_ORG_ADMIN",), org_id=ROOT_ORG_ID)


@pytest.fixture
def other_org_report(auth_headers, make_local_user):
    """A report in another organization -- a report lands in its uploader's organization, so acme's admin adds it."""
    client.post("/api/v1/organizations", json={"id": OTHER, "name": "Acme"}, headers=auth_headers)
    _, acme_admin = make_local_user("acmereports", "pw12345", role_names=("ROLE_ORG_ADMIN",), org_id=OTHER)
    d = Document()
    d.add_paragraph("Hello {{ name }}")
    buf = BytesIO()
    d.save(buf)
    resp = client.post(
        "/api/v1/reports", files={"file": ("acme.docx", buf.getvalue(), "application/octet-stream")},
        data={"name": "Acme payroll"}, headers=acme_admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["org_id"] == OTHER
    return resp.json()["report_id"]


def test_report_of_another_org_is_not_found(other_org_report, root_org_admin):
    _, root_org_admin = root_org_admin
    rid = other_org_report
    assert client.get(f"/api/v1/reports/{rid}/file", headers=root_org_admin).status_code == 404
    assert client.get(f"/api/v1/reports/{rid}/shortcuts", headers=root_org_admin).status_code == 404
    assert client.patch(f"/api/v1/reports/{rid}", json={"name": "Taken"}, headers=root_org_admin).status_code == 404
    assert client.delete(f"/api/v1/reports/{rid}", headers=root_org_admin).status_code == 404


def test_cannot_grant_access_to_another_orgs_report_or_folder(other_org_report, other_org_resources, root_org_admin):
    me, root_org_admin = root_org_admin
    folder, _, _ = other_org_resources
    report_grant = {"subject_type": "user", "subject_id": me, "report_id": other_org_report, "permission_level": "manage"}
    folder_grant = {"subject_type": "user", "subject_id": me, "folder_id": folder["id"], "permission_level": "manage"}
    assert client.post("/api/v1/grants/reports", json=report_grant, headers=root_org_admin).status_code == 404
    assert client.post("/api/v1/grants/folders", json=folder_grant, headers=root_org_admin).status_code == 404
    assert client.get("/api/v1/grants/reports", params={"report_id": other_org_report}, headers=root_org_admin).status_code == 404
    assert client.get("/api/v1/grants/folders", params={"folder_id": folder["id"]}, headers=root_org_admin).status_code == 404
    # Nothing slipped through: the report is still out of reach.
    assert client.get(f"/api/v1/reports/{other_org_report}/file", headers=root_org_admin).status_code == 404


def test_folder_of_another_org_is_not_found(other_org_resources, root_org_admin):
    _, root_org_admin = root_org_admin
    folder, _, _ = other_org_resources
    assert client.get(f"/api/v1/folders/{folder['id']}", headers=root_org_admin).status_code == 404
    assert client.patch(f"/api/v1/folders/{folder['id']}", json={"name": "Taken"}, headers=root_org_admin).status_code == 404
    assert client.delete(f"/api/v1/folders/{folder['id']}", headers=root_org_admin).status_code == 404


def test_image_of_another_org_is_not_found(other_org_resources, root_org_admin):
    _, root_org_admin = root_org_admin
    _, image, _ = other_org_resources
    base = f"/api/v1/images/{image['id']}"
    for path in (base, f"{base}/file", f"{base}/thumbnail", f"{base}/usage"):
        assert client.get(path, headers=root_org_admin).status_code == 404, path
    assert client.patch(base, json={"name": "Taken"}, headers=root_org_admin).status_code == 404
    replaced = client.put(f"{base}/file", files={"file": ("b.png", _png(), "image/png")}, headers=root_org_admin)
    assert replaced.status_code == 404
    assert client.delete(base, headers=root_org_admin).status_code == 404


def test_stylesheet_of_another_org_is_not_found(other_org_resources, root_org_admin):
    _, root_org_admin = root_org_admin
    _, _, sheet = other_org_resources
    base = f"/api/v1/stylesheets/{sheet['id']}"
    for path in (base, f"{base}/file", f"{base}/source", f"{base}/usage"):
        assert client.get(path, headers=root_org_admin).status_code == 404, path
    assert client.patch(base, json={"name": "Taken"}, headers=root_org_admin).status_code == 404
    replaced = client.put(f"{base}/file", files={"file": ("b.css", b"p {}", "text/css")}, headers=root_org_admin)
    assert replaced.status_code == 404
    assert client.delete(base, headers=root_org_admin).status_code == 404


def test_own_org_admin_still_manages_them(auth_headers, make_local_user, other_org_resources):
    """The fix scopes the check, it doesn't take the permission away: acme's own admin reaches all three."""
    folder, image, sheet = other_org_resources
    _, headers = make_local_user("acmeadmin", "pw12345", role_names=("ROLE_ORG_ADMIN",), org_id=OTHER)
    assert client.get(f"/api/v1/folders/{folder['id']}", headers=headers).status_code == 200
    assert client.get(f"/api/v1/images/{image['id']}/file", headers=headers).status_code == 200
    assert client.get(f"/api/v1/stylesheets/{sheet['id']}/file", headers=headers).status_code == 200
    assert client.patch(f"/api/v1/images/{image['id']}", json={"name": "Renamed"}, headers=headers).status_code == 200
