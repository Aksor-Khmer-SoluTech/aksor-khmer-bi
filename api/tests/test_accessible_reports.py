"""GET /api/v1/reports/accessible -- the end-user "Reports" listing. It
must agree with what the write/render routes actually enforce (a global
report:* permission, a report grant, or an inherited folder grant), stay
inside the caller's own organization, and fail closed for everything else.
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from app import db, report_store
from app.main import app
from app.rbac import ROOT_ORG_ID, create_organization

client = TestClient(app)


def _docx_bytes() -> bytes:
    doc = Document()
    doc.add_paragraph("Hello {{ name }}")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _register(auth_headers, name: str, description: str | None = None) -> str:
    data = {"name": name}
    if description is not None:
        data["description"] = description
    resp = client.post(
        "/api/v1/reports",
        files={"file": ("t.docx", _docx_bytes(), "application/octet-stream")},
        data=data,
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


def _grant_report(auth_headers, user_id: str, report_id: str, level: str, expires_at: str | None = None):
    body = {"subject_type": "user", "subject_id": user_id, "report_id": report_id, "permission_level": level}
    if expires_at is not None:
        body["expires_at"] = expires_at
    resp = client.post("/api/v1/grants/reports", json=body, headers=auth_headers)
    assert resp.status_code == 200, resp.text


def _listing(headers) -> dict[str, dict]:
    resp = client.get("/api/v1/reports/accessible", headers=headers)
    assert resp.status_code == 200, resp.text
    return {r["report_id"]: r for r in resp.json()}


def test_requires_authentication():
    assert client.get("/api/v1/reports/accessible").status_code == 401


def test_superuser_sees_every_report_as_manage(auth_headers):
    a = _register(auth_headers, "Alpha")
    b = _register(auth_headers, "Bravo")
    listing = _listing(auth_headers)
    assert set(listing) == {a, b}
    assert {r["access_level"] for r in listing.values()} == {"manage"}


def test_user_with_no_grants_sees_nothing(auth_headers, make_local_user):
    _register(auth_headers, "Hidden")
    _, headers = make_local_user("nobody", "pw12345", role_names=())
    assert _listing(headers) == {}


def test_report_grant_lists_only_that_report_at_the_granted_level(auth_headers, make_local_user):
    granted = _register(auth_headers, "Granted")
    other = _register(auth_headers, "Not Granted")
    user_id, headers = make_local_user("grantee", "pw12345", role_names=())
    _grant_report(auth_headers, user_id, granted, "view")

    listing = _listing(headers)
    assert set(listing) == {granted}
    assert listing[granted]["access_level"] == "view"
    assert other not in listing


def test_access_level_reflects_the_highest_grant(auth_headers, make_local_user):
    r_view = _register(auth_headers, "V")
    r_render = _register(auth_headers, "R")
    r_manage = _register(auth_headers, "M")
    user_id, headers = make_local_user("leveled", "pw12345", role_names=())
    _grant_report(auth_headers, user_id, r_view, "view")
    _grant_report(auth_headers, user_id, r_render, "render")
    _grant_report(auth_headers, user_id, r_manage, "manage")

    listing = _listing(headers)
    assert listing[r_view]["access_level"] == "view"
    assert listing[r_render]["access_level"] == "render"
    assert listing[r_manage]["access_level"] == "manage"


def test_expired_grant_is_not_listed(auth_headers, make_local_user):
    report_id = _register(auth_headers, "Expired")
    user_id, headers = make_local_user("expired_grantee", "pw12345", role_names=())
    _grant_report(auth_headers, user_id, report_id, "view", expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    assert _listing(headers) == {}


def test_global_report_view_permission_lists_every_report_in_the_org(auth_headers, make_local_user):
    # ROLE_USER holds report:view globally -- so it sees the whole org's
    # reports. Restricting a user to specific reports means granting them
    # per report/folder instead of giving them this role.
    a = _register(auth_headers, "One")
    b = _register(auth_headers, "Two")
    _, headers = make_local_user("role_user", "pw12345", role_names=("ROLE_USER",))
    listing = _listing(headers)
    assert set(listing) == {a, b}
    assert {r["access_level"] for r in listing.values()} == {"view"}


def test_report_viewer_role_reports_render_level(auth_headers, make_local_user):
    report_id = _register(auth_headers, "Renderable")
    _, headers = make_local_user("viewer_role", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    assert _listing(headers)[report_id]["access_level"] == "render"


def test_folder_grant_is_inherited_by_reports_filed_in_it(auth_headers, make_local_user):
    parent = client.post("/api/v1/folders", json={"org_id": ROOT_ORG_ID, "name": "Finance"}, headers=auth_headers).json()
    child = client.post(
        "/api/v1/folders", json={"org_id": ROOT_ORG_ID, "name": "Q1", "parent_folder_id": parent["id"]}, headers=auth_headers
    ).json()
    filed = _register(auth_headers, "Filed in Q1")
    unfiled = _register(auth_headers, "Unfiled")
    assert client.patch(f"/api/v1/reports/{filed}", json={"folder_id": child["id"]}, headers=auth_headers).status_code == 200

    user_id, headers = make_local_user("folder_viewer", "pw12345", role_names=())
    resp = client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "user", "subject_id": user_id, "folder_id": parent["id"], "permission_level": "view"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    listing = _listing(headers)
    assert set(listing) == {filed}
    assert listing[filed]["access_level"] == "view"
    assert unfiled not in listing


def test_other_organizations_reports_never_appear(auth_headers, make_local_user):
    with db.SessionLocal() as session:
        create_organization(session, "other-org", "Other Org")
        session.commit()
    foreign = report_store.create_report(
        name="Foreign", content=_docx_bytes(), template_ext="docx", org_id="other-org"
    )["report_id"]
    own = _register(auth_headers, "Own")

    # Global view in the root org still doesn't reach into another org...
    _, headers = make_local_user("root_viewer", "pw12345", role_names=("ROLE_USER",))
    assert set(_listing(headers)) == {own}

    # ...and neither does a direct grant on the foreign report.
    user_id, granted_headers = make_local_user("cross_org_grantee", "pw12345", role_names=())
    _grant_report(auth_headers, user_id, foreign, "view")
    assert _listing(granted_headers) == {}


def _set_public(auth_headers, report_id: str, is_public: bool):
    resp = client.patch(f"/api/v1/reports/{report_id}", json={"is_public": is_public}, headers=auth_headers)
    assert resp.status_code == 200, resp.text


def test_public_report_is_listed_at_view_level_for_every_org_member(auth_headers, make_local_user):
    report_id = _register(auth_headers, "Everyone")
    _set_public(auth_headers, report_id, True)

    _, headers = make_local_user("public_viewer", "pw12345", role_names=())
    listing = _listing(headers)
    assert listing[report_id]["access_level"] == "view"


def test_public_report_in_another_org_is_not_listed(auth_headers, make_local_user):
    with db.SessionLocal() as session:
        create_organization(session, "other-org-2", "Other Org 2")
        session.commit()
    report_id = report_store.create_report(
        name="Foreign Public", content=_docx_bytes(), template_ext="docx", org_id="other-org-2"
    )["report_id"]
    report_store.update_report_meta(report_id, is_public=True)

    _, headers = make_local_user("root_viewer_2", "pw12345", role_names=())
    assert report_id not in _listing(headers)


def test_listing_is_lean_and_sorted_by_name(auth_headers):
    _register(auth_headers, "banana", description="Fruit")
    _register(auth_headers, "Apple")
    resp = client.get("/api/v1/reports/accessible", headers=auth_headers)
    rows = resp.json()
    assert [r["name"] for r in rows] == ["Apple", "banana"]
    assert set(rows[0]) == {"report_id", "name", "description", "template_ext", "version", "version_label", "updated_at", "access_level"}
    assert rows[1]["description"] == "Fruit"
