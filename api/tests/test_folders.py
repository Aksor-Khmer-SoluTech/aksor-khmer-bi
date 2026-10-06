from fastapi.testclient import TestClient

from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def _create_folder(headers, name, parent_folder_id=None, org_id=ROOT_ORG_ID):
    return client.post(
        "/api/v1/folders",
        json={"org_id": org_id, "name": name, "parent_folder_id": parent_folder_id},
        headers=headers,
    )


def test_create_root_folder(auth_headers):
    resp = _create_folder(auth_headers, "Finance")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Finance"
    assert body["parent_folder_id"] is None


def test_create_subfolder(auth_headers):
    parent = _create_folder(auth_headers, "Finance").json()
    resp = _create_folder(auth_headers, "Q1", parent_folder_id=parent["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["parent_folder_id"] == parent["id"]


def test_duplicate_sibling_name_rejected(auth_headers):
    _create_folder(auth_headers, "Finance")
    resp = _create_folder(auth_headers, "Finance")
    assert resp.status_code == 409


def test_same_name_allowed_under_different_parents(auth_headers):
    a = _create_folder(auth_headers, "A").json()
    b = _create_folder(auth_headers, "B").json()
    r1 = _create_folder(auth_headers, "Shared", parent_folder_id=a["id"])
    r2 = _create_folder(auth_headers, "Shared", parent_folder_id=b["id"])
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_create_folder_requires_permission(make_local_user):
    _, headers = make_local_user("nofolder", "pw12345", role_names=())
    resp = _create_folder(headers, "Finance")
    assert resp.status_code == 403


def test_rename_folder(auth_headers):
    folder = _create_folder(auth_headers, "Finance").json()
    resp = client.patch(f"/api/v1/folders/{folder['id']}", json={"name": "Accounting"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Accounting"


def test_move_folder_to_new_parent(auth_headers):
    a = _create_folder(auth_headers, "A").json()
    b = _create_folder(auth_headers, "B").json()
    child = _create_folder(auth_headers, "Child", parent_folder_id=a["id"]).json()
    resp = client.patch(f"/api/v1/folders/{child['id']}", json={"parent_folder_id": b["id"]}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["parent_folder_id"] == b["id"]


def test_move_folder_to_root(auth_headers):
    a = _create_folder(auth_headers, "A").json()
    child = _create_folder(auth_headers, "Child", parent_folder_id=a["id"]).json()
    resp = client.patch(f"/api/v1/folders/{child['id']}", json={"parent_folder_id": None}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["parent_folder_id"] is None


def test_move_folder_into_own_subfolder_rejected(auth_headers):
    a = _create_folder(auth_headers, "A").json()
    child = _create_folder(auth_headers, "Child", parent_folder_id=a["id"]).json()
    resp = client.patch(f"/api/v1/folders/{a['id']}", json={"parent_folder_id": child["id"]}, headers=auth_headers)
    assert resp.status_code == 400


def test_delete_empty_folder(auth_headers):
    folder = _create_folder(auth_headers, "Finance").json()
    resp = client.delete(f"/api/v1/folders/{folder['id']}", headers=auth_headers)
    assert resp.status_code == 204


def test_delete_nonempty_folder_rejected(auth_headers):
    parent = _create_folder(auth_headers, "Finance").json()
    _create_folder(auth_headers, "Q1", parent_folder_id=parent["id"])
    resp = client.delete(f"/api/v1/folders/{parent['id']}", headers=auth_headers)
    assert resp.status_code == 409


# --- inheritance + union-not-override ---------------------------------


def test_folder_grant_inherits_to_subfolder(auth_headers, make_local_user):
    """A role granted 'view' on a parent folder can see a child folder
    nested two levels down, with no grant on the child itself."""
    parent = _create_folder(auth_headers, "Finance").json()
    child = _create_folder(auth_headers, "Q1", parent_folder_id=parent["id"]).json()
    grandchild = _create_folder(auth_headers, "Detail", parent_folder_id=child["id"]).json()

    role_resp = client.post("/api/v1/roles", json={"org_id": ROOT_ORG_ID, "name": "ViewerRole"}, headers=auth_headers)
    role_id = role_resp.json()["id"]

    user_id, headers = make_local_user("viewer_inherit", "pw12345", role_names=())
    client.post("/api/v1/grants/roles", json={"user_id": user_id, "role_id": role_id}, headers=auth_headers)
    client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "role", "subject_id": role_id, "folder_id": parent["id"], "permission_level": "view"},
        headers=auth_headers,
    )

    resp = client.get("/api/v1/folders", params={"org_id": ROOT_ORG_ID}, headers=headers)
    assert resp.status_code == 200
    visible_ids = {f["id"] for f in resp.json()}
    assert parent["id"] in visible_ids
    assert child["id"] in visible_ids
    assert grandchild["id"] in visible_ids


def test_folder_grant_does_not_leak_to_unrelated_folder(auth_headers, make_local_user):
    granted = _create_folder(auth_headers, "Finance").json()
    unrelated = _create_folder(auth_headers, "HR").json()

    role_resp = client.post("/api/v1/roles", json={"org_id": ROOT_ORG_ID, "name": "ViewerRole2"}, headers=auth_headers)
    role_id = role_resp.json()["id"]
    user_id, headers = make_local_user("viewer_scoped", "pw12345", role_names=())
    client.post("/api/v1/grants/roles", json={"user_id": user_id, "role_id": role_id}, headers=auth_headers)
    client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "role", "subject_id": role_id, "folder_id": granted["id"], "permission_level": "view"},
        headers=auth_headers,
    )

    resp = client.get("/api/v1/folders", params={"org_id": ROOT_ORG_ID}, headers=headers)
    visible_ids = {f["id"] for f in resp.json()}
    assert granted["id"] in visible_ids
    assert unrelated["id"] not in visible_ids


def test_org_admin_unaffected_by_folder_grants(auth_headers, make_local_user):
    """A global folder:manage/org-admin holder sees every folder
    regardless of whether any folder-specific grant exists at all --
    union-not-override: folder grants only ever add visibility, never
    take any away from someone who already has the global permission."""
    _create_folder(auth_headers, "Finance")
    _create_folder(auth_headers, "HR")

    _, headers = make_local_user("orgadmin_folders", "pw12345", role_names=("ROLE_ORG_ADMIN",))
    resp = client.get("/api/v1/folders", params={"org_id": ROOT_ORG_ID}, headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 2
