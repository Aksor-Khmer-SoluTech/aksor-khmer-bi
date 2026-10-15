"""GET /api/v1/users/{id}/overview -- app/user_overview.py."""
from datetime import datetime, timezone
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def _docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Hello {{ name }}")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _register(headers, name, folder_id=None) -> str:
    data = {"name": name}
    if folder_id:
        data["folder_id"] = folder_id
    resp = client.post("/api/v1/reports", files={"file": ("t.docx", _docx(), "application/octet-stream")}, data=data, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


def _folder(headers, name) -> str:
    resp = client.post("/api/v1/folders", json={"org_id": ROOT_ORG_ID, "name": name}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_overview_counts_uploads_reach_and_permission_sources(auth_headers, make_local_user):
    author_id, author = make_local_user("ov_author", "pw12345", role_names=("ROLE_REPORT_ADMIN",))
    mine = _register(author, "Author's invoice")
    _register(auth_headers, "Someone else's report")

    # A version uploaded later counts too, without making it a second template.
    resp = client.put(f"/api/v1/reports/{mine}/file", files={"file": ("t.docx", _docx(), "application/octet-stream")}, headers=author)
    assert resp.status_code == 200, resp.text

    body = client.get(f"/api/v1/users/{author_id}/overview", headers=auth_headers).json()
    t = body["templates"]
    assert t["contributed"] == 1 and t["started"] == 1 and t["versions"] == 2
    assert t["by_type"] == {"docx": 1}
    assert t["items"][0]["name"] == "Author's invoice" and t["items"][0]["access_level"] == "manage"
    # report:manage opens every template in the organization.
    assert body["reach"]["org_wide"] == "report:manage"
    assert body["reach"]["manage"] == body["reach"]["total"] >= 2
    perm = {p["code"]: p for p in body["permissions"]}
    assert perm["report:manage"]["sources"] == [{"kind": "role", "name": "ROLE_REPORT_ADMIN", "expires_at": None}]
    assert [r["name"] for r in body["roles"]] == ["ROLE_REPORT_ADMIN"]


def test_overview_shows_folder_grants_and_the_reach_they_give(auth_headers, make_local_user):
    viewer_id, _ = make_local_user("ov_viewer", "pw12345", role_names=())
    finance = _folder(auth_headers, "Finance")
    _register(auth_headers, "Ledger", folder_id=finance)
    _register(auth_headers, "Elsewhere")
    with db.SessionLocal() as session:
        session.add(
            db.FolderAccessGrant(
                subject_type="user", subject_id=viewer_id, folder_id=finance, permission_level="view",
                granted_at=datetime.now(timezone.utc).isoformat(), is_active=True,
            )
        )
        session.commit()

    body = client.get(f"/api/v1/users/{viewer_id}/overview", headers=auth_headers).json()
    assert body["templates"]["contributed"] == 0
    assert body["reach"]["org_wide"] is None
    assert (body["reach"]["view"], body["reach"]["render"], body["reach"]["manage"]) == (1, 0, 0)
    assert [{k: v for k, v in g.items() if k != "grant_id"} for g in body["folder_grants"]] == [
        {"folder_id": finance, "path": ["Finance"], "is_project": False, "level": "view", "via_role": None, "expires_at": None, "templates": 1}
    ]
    assert body["permissions"] == []


def test_overview_needs_user_manage(make_local_user):
    target_id, _ = make_local_user("ov_target", "pw12345", role_names=())
    _, viewer = make_local_user("ov_nosy", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    assert client.get(f"/api/v1/users/{target_id}/overview", headers=viewer).status_code == 403
    with db.SessionLocal() as session:
        assert session.execute(select(db.User.id).where(db.User.id == target_id)).scalar_one()


def test_overview_lists_template_grants_with_their_id(auth_headers, make_local_user):
    user_id, _ = make_local_user("ov_granted", "pw12345", role_names=())
    report_id = _register(auth_headers, "Payroll")
    resp = client.post(
        "/api/v1/grants/reports",
        json={"subject_type": "user", "subject_id": user_id, "report_id": report_id, "permission_level": "render"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    grants = client.get(f"/api/v1/users/{user_id}/overview", headers=auth_headers).json()["report_grants"]
    assert [(g["grant_id"], g["name"], g["level"], g["via_role"]) for g in grants] == [(resp.json()["id"], "Payroll", "render", None)]
    reach = client.get(f"/api/v1/users/{user_id}/overview", headers=auth_headers).json()["reach"]
    assert reach["render"] == 1
