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
    assert set(rows[0]) == {"report_id", "name", "description", "template_ext", "version", "version_label", "updated_at", "access_level", "folder_path", "shortcuts", "is_draft"}
    assert rows[1]["description"] == "Fruit"


def test_folder_path_lists_nested_folders_and_hides_ones_the_caller_cannot_open(auth_headers, make_local_user):
    def folder(name, parent=None):
        body = {"org_id": ROOT_ORG_ID, "name": name, **({"parent_folder_id": parent["id"]} if parent else {})}
        return client.post("/api/v1/folders", json=body, headers=auth_headers).json()

    finance, q1 = folder("Finance"), None
    q1 = folder("Q1", finance)
    filed = _register(auth_headers, "Filed in Q1")
    root_level = _register(auth_headers, "At the root")
    assert client.patch(f"/api/v1/reports/{filed}", json={"folder_id": q1["id"]}, headers=auth_headers).status_code == 200

    # the manager sees the whole chain, outermost first
    listing = _listing(auth_headers)
    assert [f["name"] for f in listing[filed]["folder_path"]] == ["Finance", "Q1"]
    assert listing[root_level]["folder_path"] == []

    # a grant on the *child* only: the parent's name is not revealed
    user_id, headers = make_local_user("child_viewer", "pw12345", role_names=())
    resp = client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "user", "subject_id": user_id, "folder_id": q1["id"], "permission_level": "view"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert [f["name"] for f in _listing(headers)[filed]["folder_path"]] == ["Q1"]

    # a report grant alone, in a folder they can't open: no folder at all
    other_id, other_headers = make_local_user("report_only", "pw12345", role_names=())
    _grant_report(auth_headers, other_id, filed, "view")
    assert _listing(other_headers)[filed]["folder_path"] == []


def _folder(auth_headers, name, parent=None, org=ROOT_ORG_ID):
    body = {"org_id": org, "name": name, **({"parent_folder_id": parent} if parent else {})}
    resp = client.post("/api/v1/folders", json=body, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _upload(headers, name, folder_id=None):
    data = {"name": name, **({"folder_id": folder_id} if folder_id else {})}
    return client.post("/api/v1/reports", files={"file": ("t.docx", _docx_bytes(), "application/octet-stream")}, data=data, headers=headers)


def test_a_report_can_be_filed_in_a_folder_when_it_is_uploaded(auth_headers):
    folder = _folder(auth_headers, "Finance")
    resp = _upload(auth_headers, "Filed on upload", folder)
    assert resp.status_code == 200, resp.text
    assert resp.json()["folder_id"] == folder
    assert [f["name"] for f in _listing(auth_headers)[resp.json()["report_id"]]["folder_path"]] == ["Finance"]


def test_filing_into_a_missing_folder_is_refused_on_upload_and_on_move(auth_headers):
    assert _upload(auth_headers, "Nowhere", "does-not-exist").status_code == 404
    rid = _register(auth_headers, "Plain")
    assert client.patch(f"/api/v1/reports/{rid}", json={"folder_id": "does-not-exist"}, headers=auth_headers).status_code == 404


def test_filing_needs_manage_access_on_the_destination_folder(auth_headers, make_local_user):
    folder = _folder(auth_headers, "Locked")
    user_id, headers = make_local_user("report_manager", "pw12345", role_names=())
    rid = _register(auth_headers, "Mine")
    _grant_report(auth_headers, user_id, rid, "manage")
    resp = client.patch(f"/api/v1/reports/{rid}", json={"folder_id": folder}, headers=headers)
    assert resp.status_code == 403
    client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "user", "subject_id": user_id, "folder_id": folder, "permission_level": "manage"},
        headers=auth_headers,
    )
    assert client.patch(f"/api/v1/reports/{rid}", json={"folder_id": folder}, headers=headers).status_code == 200


def test_folder_list_says_which_folders_the_caller_may_file_into(auth_headers, make_local_user):
    parent = _folder(auth_headers, "Open")
    child = _folder(auth_headers, "Inner", parent)
    user_id, headers = make_local_user("folder_manager", "pw12345", role_names=())
    client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "user", "subject_id": user_id, "folder_id": child, "permission_level": "manage"},
        headers=auth_headers,
    )
    mine = {f["name"]: f["can_manage"] for f in client.get("/api/v1/folders", headers=headers).json()}
    assert mine == {"Inner": True}
    assert all(f["can_manage"] for f in client.get("/api/v1/folders", headers=auth_headers).json())


# --- shortcuts: a second place to find a report, with the original's permissions and nothing more ---------


def _shortcut(headers, rid, folder_id):
    return client.post(f"/api/v1/reports/{rid}/shortcuts", json={"folder_id": folder_id}, headers=headers)


def test_a_shortcut_lists_the_report_in_a_second_folder(auth_headers):
    home, other = _folder(auth_headers, "Home"), _folder(auth_headers, "Elsewhere")
    inner = _folder(auth_headers, "Inner", other)
    rid = _upload(auth_headers, "Original", home).json()["report_id"]

    made = _shortcut(auth_headers, rid, inner)
    assert made.status_code == 200, made.text
    listed = _listing(auth_headers)[rid]
    assert [f["name"] for f in listed["folder_path"]] == ["Home"]
    assert [[f["name"] for f in sc["folder_path"]] for sc in listed["shortcuts"]] == [["Elsewhere", "Inner"]]
    assert [sc["folder_id"] for sc in client.get(f"/api/v1/reports/{rid}/shortcuts", headers=auth_headers).json()] == [inner]

    # taking it away leaves the report where it was
    assert client.delete(f"/api/v1/reports/shortcuts/{made.json()['id']}", headers=auth_headers).status_code == 204
    assert _listing(auth_headers)[rid]["shortcuts"] == []
    assert _listing(auth_headers)[rid]["folder_path"][0]["name"] == "Home"


def test_a_shortcut_refuses_its_own_folder_a_repeat_and_a_missing_folder(auth_headers):
    home, other = _folder(auth_headers, "Home"), _folder(auth_headers, "Other")
    rid = _upload(auth_headers, "Original", home).json()["report_id"]
    assert _shortcut(auth_headers, rid, home).status_code == 400
    assert _shortcut(auth_headers, rid, "nope").status_code == 404
    assert _shortcut(auth_headers, rid, other).status_code == 200
    assert _shortcut(auth_headers, rid, other).status_code == 409


def test_a_folder_grant_on_the_shortcuts_folder_does_not_open_the_report(auth_headers, make_local_user):
    """The whole point: a shortcut has the original's permissions, so granting a folder that holds one reveals
    and grants nothing."""
    home, shared = _folder(auth_headers, "Private"), _folder(auth_headers, "Shared")
    rid = _upload(auth_headers, "Secret", home).json()["report_id"]
    assert _shortcut(auth_headers, rid, shared).status_code == 200
    user_id, headers = make_local_user("shared_viewer", "pw12345", role_names=())
    client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "user", "subject_id": user_id, "folder_id": shared, "permission_level": "view"},
        headers=auth_headers,
    )
    assert _listing(headers) == {}
    assert client.get("/api/v1/reports/shortcuts", headers=headers).json() == []

    # someone who does hold access to the original sees the shortcut -- but only in folders they may open
    holder_id, holder = make_local_user("original_viewer", "pw12345", role_names=())
    _grant_report(auth_headers, holder_id, rid, "view")
    assert _listing(holder)[rid]["shortcuts"] == []  # the Shared folder isn't theirs to open
    client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "user", "subject_id": holder_id, "folder_id": shared, "permission_level": "view"},
        headers=auth_headers,
    )
    assert [[f["name"] for f in sc["folder_path"]] for sc in _listing(holder)[rid]["shortcuts"]] == [["Shared"]]


def test_making_a_shortcut_needs_manage_on_the_report_and_on_the_destination_folder(auth_headers, make_local_user):
    home, other = _folder(auth_headers, "Home"), _folder(auth_headers, "Other")
    rid = _upload(auth_headers, "Original", home).json()["report_id"]
    user_id, headers = make_local_user("just_a_viewer", "pw12345", role_names=())
    _grant_report(auth_headers, user_id, rid, "view")
    assert _shortcut(headers, rid, other).status_code == 403  # view isn't enough
    _grant_report(auth_headers, user_id, rid, "manage")
    assert _shortcut(headers, rid, other).status_code == 403  # and nor is manage without the folder
    client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "user", "subject_id": user_id, "folder_id": other, "permission_level": "manage"},
        headers=auth_headers,
    )
    assert _shortcut(headers, rid, other).status_code == 200


def test_deleting_a_folder_removes_its_shortcuts_and_deleting_a_report_removes_its_shortcuts(auth_headers):
    home, other = _folder(auth_headers, "Home"), _folder(auth_headers, "Other")
    rid = _upload(auth_headers, "Original", home).json()["report_id"]
    _shortcut(auth_headers, rid, other)
    assert client.delete(f"/api/v1/folders/{other}", headers=auth_headers).status_code == 204  # links don't hold it open
    assert _listing(auth_headers)[rid]["shortcuts"] == []
    again = _folder(auth_headers, "Again")
    _shortcut(auth_headers, rid, again)
    assert client.delete(f"/api/v1/reports/{rid}", headers=auth_headers).status_code in (200, 204)
    assert client.get("/api/v1/reports/shortcuts", headers=auth_headers).json() == []


def test_filing_a_report_where_its_shortcut_is_replaces_the_shortcut(auth_headers):
    home, other = _folder(auth_headers, "Home"), _folder(auth_headers, "Other")
    rid = _upload(auth_headers, "Original", home).json()["report_id"]
    _shortcut(auth_headers, rid, other)
    assert client.patch(f"/api/v1/reports/{rid}", json={"folder_id": other}, headers=auth_headers).status_code == 200
    listed = _listing(auth_headers)[rid]
    assert [f["name"] for f in listed["folder_path"]] == ["Other"] and listed["shortcuts"] == []
