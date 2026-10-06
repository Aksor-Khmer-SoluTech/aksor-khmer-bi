"""The change audit trail (app/audit.py, GET /api/v1/audit): every
administrative mutation leaves a row saying who/what/before/after, secrets
never reach it, a failure to write it never breaks the change itself, and
only someone holding `audit:view` may read it -- scoped to their own
organization.
"""
import json
from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app import audit, db
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


# --- helpers ------------------------------------------------------------------


def _events(action=None, entity_id=None):
    with db.SessionLocal() as session:
        query = select(db.AuditEvent).order_by(db.AuditEvent.created_at, db.AuditEvent.id)
        if action:
            query = query.where(db.AuditEvent.action == action)
        if entity_id:
            query = query.where(db.AuditEvent.entity_id == entity_id)
        return [audit.event_to_dict(r) for r in session.execute(query).scalars()]


def _one(action, entity_id=None):
    found = _events(action, entity_id)
    assert len(found) == 1, f"expected exactly one {action!r}, got {[e['action'] for e in _events()]}"
    return found[0]


def _dump_all():
    """Every audit row as one JSON string -- for "the secret appears nowhere" checks."""
    return json.dumps(_events(), default=str)


def _docx() -> bytes:
    buf = BytesIO()
    doc = Document()
    doc.add_paragraph("Hi {{ name }}")
    doc.save(buf)
    return buf.getvalue()


def _report(headers, name="Audited"):
    resp = client.post(
        "/api/v1/reports", files={"file": ("t.docx", _docx(), "application/octet-stream")}, data={"name": name}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


def _user(headers, username="dana", password="pw-dana-12345"):
    resp = client.post(
        "/api/v1/users",
        params={"org_id": ROOT_ORG_ID},
        json={"username": username, "auth_source": "local", "password": password, "email": f"{username}@x.test"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


# --- diff / redact (unit) -----------------------------------------------------


def test_diff_reports_only_what_changed():
    changes = audit.diff({"a": 1, "b": "x", "c": True}, {"a": 1, "b": "y", "c": True}, ["a", "b", "c"])
    assert changes == [{"field": "b", "before": "x", "after": "y"}]


def test_diff_of_a_list_of_plain_values_is_added_and_removed_not_two_lists():
    (change,) = audit.diff({"terms": ["a", "b", "c"]}, {"terms": ["b", "c", "d", "e"]}, ["terms"])
    assert change["added"] == ["d", "e"] and change["removed"] == ["a"]
    assert change["added_count"] == 2 and change["removed_count"] == 1
    assert "before" not in change  # a 5,000-term set doesn't get stored twice


def test_diff_flattens_a_nested_dict_to_the_leaf_that_moved():
    before = {"data_source": {"url": "https://a", "method": "GET"}}
    after = {"data_source": {"url": "https://b", "method": "GET"}}
    assert audit.diff(before, after, ["data_source"]) == [{"field": "data_source.url", "before": "https://a", "after": "https://b"}]


def test_a_changed_secret_is_reported_as_changed_without_either_value():
    (change,) = audit.diff({"password_hash": "OLD-HASH"}, {"password_hash": "NEW-HASH"}, ["password_hash"])
    assert change["redacted"] is True
    assert "OLD-HASH" not in json.dumps(change) and "NEW-HASH" not in json.dumps(change)


def test_header_values_are_hidden_but_their_names_stay_visible():
    before = {"data_source": {"url": "https://x", "headers": {"X-Portal-Auth": "s3cret-1"}}}
    after = {"data_source": {"url": "https://x", "headers": {"X-Portal-Auth": "s3cret-2", "X-New": "s3cret-3"}}}
    changes = audit.diff(before, after, ["data_source"])
    assert {c["field"] for c in changes} == {"data_source.headers.X-Portal-Auth", "data_source.headers.X-New"}
    assert all(c["redacted"] for c in changes)
    assert "s3cret" not in json.dumps(changes)


def test_an_env_var_name_is_not_a_secret_and_stays_visible():
    """`token_env` holds the *name* of the variable that holds the token --
    exactly what an investigator needs, and not itself sensitive."""
    (change,) = audit.diff({"auth": {"token_env": "OLD_TOKEN"}}, {"auth": {"token_env": "NEW_TOKEN"}}, ["auth"])
    assert change["before"] == "OLD_TOKEN" and change["after"] == "NEW_TOKEN"
    assert "redacted" not in change


def test_redact_walks_nested_structures():
    out = audit.redact({"url": "u", "auth": {"password": "p", "username": "bob"}, "items": [{"api_key": "k"}]})
    assert out == {"url": "u", "auth": {"password": "[redacted]", "username": "bob"}, "items": [{"api_key": "[redacted]"}]}


def test_named_list_change_summarises_parameters():
    before = [{"name": "p_a", "label": "A"}, {"name": "p_b", "label": "B"}]
    after = [{"name": "p_b", "label": "B!"}, {"name": "p_c", "label": "C"}]
    change = audit.named_list_change("parameters", before, after)
    assert change["added"] == ["p_c"] and change["removed"] == ["p_a"] and change["modified"] == ["p_b"]
    assert audit.named_list_change("parameters", before, before) is None


def test_a_failure_to_write_an_audit_row_never_breaks_the_change(auth_headers, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("audit store is down")

    with monkeypatch.context() as m:  # scoped: a bare undo() would also revert the temp-database fixture
        m.setattr(db, "AuditEvent", boom)
        resp = client.post("/api/v1/organizations", json={"id": "acme", "name": "Acme"}, headers=auth_headers)
    assert resp.status_code == 200  # the organization was still created
    assert client.get("/api/v1/organizations/acme", headers=auth_headers).status_code == 200
    assert _events("organization.create") == []  # ...and the gap is the logged failure, not a crash


# --- the sweep: every kind of change leaves the right row ---------------------


def test_users_lifecycle_is_recorded_and_no_password_is_ever_stored(auth_headers):
    user_id = _user(auth_headers, password="pw-dana-INITIAL")
    created = _one("user.create", user_id)
    assert created["actor_username"] == "testadmin" and created["entity_label"] == "dana"
    assert created["org_id"] == ROOT_ORG_ID

    client.patch(f"/api/v1/users/{user_id}", json={"is_active": False, "display_name": "Dana K"}, headers=auth_headers)
    updated = _one("user.update", user_id)
    assert updated["summary"] == "Deactivated user dana"
    assert {c["field"]: (c["before"], c["after"]) for c in updated["changes"]} == {
        "display_name": (None, "Dana K"),
        "is_active": (True, False),
    }

    client.patch(f"/api/v1/users/{user_id}", json={"password": "pw-dana-ROTATED", "reset_totp": True}, headers=auth_headers)
    _one("user.password_reset", user_id)
    _one("user.totp_reset", user_id)

    dump = _dump_all()
    assert "pw-dana-INITIAL" not in dump and "pw-dana-ROTATED" not in dump


def test_a_user_changing_their_own_password_is_recorded(make_local_user):
    user_id, headers = make_local_user("sam", "pw-sam-12345", ("ROLE_USER",))
    resp = client.patch(
        "/api/v1/users/me", json={"current_password": "pw-sam-12345", "new_password": "pw-sam-67890"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    event = _one("user.password_change", user_id)
    assert event["actor_username"] == "sam" and event["actor_user_id"] == user_id
    assert "pw-sam" not in _dump_all()


def test_role_and_permission_grants_and_revokes(auth_headers):
    user_id = _user(auth_headers)
    with db.SessionLocal() as session:
        role_id = session.execute(
            select(db.Role.id).where(db.Role.name == "ROLE_REPORT_VIEWER", db.Role.org_id == ROOT_ORG_ID)
        ).scalar_one()

    grant = client.post("/api/v1/grants/roles", json={"user_id": user_id, "role_id": role_id}, headers=auth_headers).json()
    granted = _one("user.role_grant", user_id)
    assert granted["details"]["role_name"] == "ROLE_REPORT_VIEWER" and "dana" in granted["summary"]
    client.delete(f"/api/v1/grants/roles/{grant['id']}", headers=auth_headers)
    _one("user.role_revoke", user_id)
    # Revoking a grant that's already revoked is a no-op, not a second event.
    client.delete(f"/api/v1/grants/roles/{grant['id']}", headers=auth_headers)
    assert len(_events("user.role_revoke")) == 1

    perm = client.post(
        "/api/v1/grants/permissions", json={"user_id": user_id, "permission_code": "job:view"}, headers=auth_headers
    ).json()
    assert _one("user.permission_grant", user_id)["details"]["permission_code"] == "job:view"
    client.delete(f"/api/v1/grants/permissions/{perm['id']}", headers=auth_headers)
    _one("user.permission_revoke", user_id)


def test_report_and_folder_access_grants_land_on_the_thing_being_shared(auth_headers):
    user_id = _user(auth_headers)
    report_id = _report(auth_headers)
    folder = client.post("/api/v1/folders", json={"org_id": ROOT_ORG_ID, "name": "Shared"}, headers=auth_headers).json()

    rg = client.post(
        "/api/v1/grants/reports",
        json={"subject_type": "user", "subject_id": user_id, "report_id": report_id, "permission_level": "render"},
        headers=auth_headers,
    ).json()
    granted = _one("report.access_grant", report_id)
    assert granted["details"]["subject_name"] == "dana" and granted["details"]["permission_level"] == "render"
    client.delete(f"/api/v1/grants/reports/{rg['id']}", headers=auth_headers)
    _one("report.access_revoke", report_id)

    fg = client.post(
        "/api/v1/grants/folders",
        json={"subject_type": "user", "subject_id": user_id, "folder_id": folder["id"], "permission_level": "view"},
        headers=auth_headers,
    ).json()
    _one("folder.access_grant", folder["id"])
    client.delete(f"/api/v1/grants/folders/{fg['id']}", headers=auth_headers)
    _one("folder.access_revoke", folder["id"])


def test_role_permission_changes_record_exactly_what_was_added_and_removed(auth_headers):
    role = client.post(
        "/api/v1/roles", json={"org_id": ROOT_ORG_ID, "name": "Auditor-Lite", "description": "d"}, headers=auth_headers
    ).json()
    _one("role.create", role["id"])

    client.put(f"/api/v1/roles/{role['id']}/permissions", json={"permissions": ["report:view", "job:view"]}, headers=auth_headers)
    client.put(f"/api/v1/roles/{role['id']}/permissions", json={"permissions": ["report:view", "user:manage"]}, headers=auth_headers)
    second = _events("role.permissions_update", role["id"])[1]
    (change,) = second["changes"]
    assert change["added"] == ["user:manage"] and change["removed"] == ["job:view"]
    # Re-saving the same set changes nothing, so records nothing.
    client.put(f"/api/v1/roles/{role['id']}/permissions", json={"permissions": ["report:view", "user:manage"]}, headers=auth_headers)
    assert len(_events("role.permissions_update", role["id"])) == 2

    client.delete(f"/api/v1/roles/{role['id']}", headers=auth_headers)
    assert _one("role.delete", role["id"])["details"]["permissions"] == ["report:view", "user:manage"]


def test_ldap_config_changes_are_recorded_and_the_test_bind_never_stores_a_password(auth_headers):
    created = client.post(
        "/api/v1/ldap-configs",
        params={"org_id": ROOT_ORG_ID},
        json={
            "server_uri": "ldap://dc1.example.test:389", "bind_method": "search_bind", "base_dn": "dc=example,dc=test",
            "service_bind_dn": "cn=svc,dc=example,dc=test", "service_bind_password_env": "LDAP_SVC_PW",
            "user_search_filter": "(uid={username})",
        },
        headers=auth_headers,
    ).json()
    _one("ldap_config.create", created["id"])

    client.patch(
        f"/api/v1/ldap-configs/{created['id']}",
        # (a search_bind PATCH has to resend the search fields -- existing validation, unrelated to audit)
        json={
            "server_uri": "ldap://evil.example.test:389", "service_bind_password_env": "OTHER_PW",
            "service_bind_dn": "cn=svc,dc=example,dc=test", "user_search_filter": "(uid={username})",
        },
        headers=auth_headers,
    )
    changes = {c["field"]: c for c in _one("ldap_config.update", created["id"])["changes"]}
    assert set(changes) == {"server_uri", "service_bind_password_env"}  # the resent, unchanged fields aren't noise
    assert changes["server_uri"]["before"] == "ldap://dc1.example.test:389"
    assert changes["server_uri"]["after"] == "ldap://evil.example.test:389"
    assert changes["service_bind_password_env"]["after"] == "OTHER_PW"  # a variable *name*, visible

    role_id = client.post("/api/v1/roles", json={"org_id": ROOT_ORG_ID, "name": "Mapped"}, headers=auth_headers).json()["id"]
    mapping = client.post(
        f"/api/v1/ldap-configs/{created['id']}/group-mappings",
        json={"group_dn": "cn=admins,dc=example,dc=test", "role_id": role_id},
        headers=auth_headers,
    ).json()
    assert "cn=admins" in _one("ldap_config.mapping_add", created["id"])["summary"]
    client.delete(f"/api/v1/ldap-configs/{created['id']}/group-mappings/{mapping['id']}", headers=auth_headers)
    _one("ldap_config.mapping_remove", created["id"])

    client.post(f"/api/v1/ldap-configs/{created['id']}/test", json={"username": "someone", "password": "TOPSECRET-PW"}, headers=auth_headers)
    tested = _one("ldap_config.test", created["id"])
    assert tested["details"]["username"] == "someone" and "TOPSECRET-PW" not in _dump_all()

    client.delete(f"/api/v1/ldap-configs/{created['id']}", headers=auth_headers)
    _one("ldap_config.delete", created["id"])


def test_protected_term_sets_record_which_terms_were_added_and_removed(auth_headers):
    made = client.post(
        "/api/v1/protected-term-sets",
        json={"org_id": ROOT_ORG_ID, "name": "Bank names", "terms": ["ធនាគារ", "អេស៊ីលីដា"], "exclude_terms": []},
        headers=auth_headers,
    )
    assert made.status_code == 200, made.text
    set_id = made.json()["id"]
    _one("protected_term_set.create", set_id)

    client.put(
        f"/api/v1/protected-term-sets/{set_id}",
        json={"name": "Bank names", "terms": ["ធនាគារ", "វីង"], "exclude_terms": []},
        headers=auth_headers,
    )
    (change,) = _one("protected_term_set.update", set_id)["changes"]
    assert change["field"] == "terms" and change["added"] == ["វីង"] and change["removed"] == ["អេស៊ីលីដា"]

    client.delete(f"/api/v1/protected-term-sets/{set_id}", headers=auth_headers)
    assert _one("protected_term_set.delete", set_id)["details"]["term_count"] == 2


def test_jobs_folders_images_stylesheets_organizations(auth_headers):
    job = client.post(
        "/api/v1/jobs",
        params={"org_id": ROOT_ORG_ID},
        json={"name": "Sweep", "job_type": "file_output", "config": {"destination_path": "/tmp/x", "source": "static", "content": "x"},
              "trigger_type": "cron", "cron_expression": "0 2 * * *"},
        headers=auth_headers,
    ).json()
    _one("job.create", job["id"])
    client.patch(f"/api/v1/jobs/{job['id']}", json={"is_enabled": False}, headers=auth_headers)
    assert _one("job.update", job["id"])["summary"] == 'Disabled job "Sweep"'
    client.delete(f"/api/v1/jobs/{job['id']}", headers=auth_headers)
    _one("job.delete", job["id"])

    a = client.post("/api/v1/folders", json={"org_id": ROOT_ORG_ID, "name": "A"}, headers=auth_headers).json()
    b = client.post("/api/v1/folders", json={"org_id": ROOT_ORG_ID, "name": "B"}, headers=auth_headers).json()
    client.patch(f"/api/v1/folders/{b['id']}", json={"parent_folder_id": a["id"]}, headers=auth_headers)
    assert _one("folder.move", b["id"])["changes"][0]["after"] == a["id"]
    client.delete(f"/api/v1/folders/{b['id']}", headers=auth_headers)
    _one("folder.delete", b["id"])

    img = client.post(
        "/api/v1/images", files={"file": ("l.png", _png(), "image/png")}, data={"name": "Logo", "org_id": ROOT_ORG_ID}, headers=auth_headers
    ).json()
    uploaded = _one("image.upload", img["id"])
    assert len(uploaded["details"]["sha256"]) == 64 and uploaded["details"]["original_filename"] == "l.png"
    client.delete(f"/api/v1/images/{img['id']}", headers=auth_headers)
    _one("image.delete", img["id"])

    css = client.post(
        "/api/v1/stylesheets", files={"file": ("t.css", b"body{color:red}", "text/css")},
        data={"name": "Theme", "org_id": ROOT_ORG_ID}, headers=auth_headers,
    ).json()
    _one("stylesheet.upload", css["id"])
    client.delete(f"/api/v1/stylesheets/{css['id']}", headers=auth_headers)
    _one("stylesheet.delete", css["id"])

    client.post("/api/v1/organizations", json={"id": "acme", "name": "Acme"}, headers=auth_headers)
    assert _one("organization.create", "acme")["org_id"] == "acme"


def test_report_settings_changes_record_a_diff_and_hide_credentials(auth_headers):
    report_id = _report(auth_headers, name="Original Name")
    client.patch(f"/api/v1/reports/{report_id}", json={"name": "Renamed", "is_public": True}, headers=auth_headers)
    upd = _one("report.update", report_id)
    assert {c["field"] for c in upd["changes"]} == {"name", "is_public"}

    client.patch(f"/api/v1/reports/{report_id}", json={"name": "Renamed"}, headers=auth_headers)  # no-op
    assert len(_events("report.update", report_id)) == 1

    client.patch(f"/api/v1/reports/{report_id}", json={"sample_context": {"name": "Bopha", "ssn": "123-45"}}, headers=auth_headers)
    sample = _events("report.update", report_id)[1]
    assert sample["changes"] == [{"field": "sample_context", "opaque": True}]
    assert "123-45" not in _dump_all()

    put = client.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={
            "parameters": [{"name": "p_branch", "label": "Branch", "options": [{"value": "PP", "label": "Phnom Penh"}]}],
            "data_source": {
                "url": "https://core.example.test/api", "method": "POST",
                "headers": {"X-Portal-Auth": "Bearer SUPERSECRET-TOKEN"},
                "body_template": {"api_key": "SUPERSECRET-BODY"},
                "auth": {"type": "bearer", "token_env": "CORE_TOKEN"},
            },
        },
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    cfg = _one("report.data_config_update", report_id)
    by_field = {c["field"]: c for c in cfg["changes"]}
    assert by_field["parameters"]["added"] == ["p_branch"]
    assert by_field["data_source.url"]["after"] == "https://core.example.test/api"
    assert by_field["data_source.headers.X-Portal-Auth"]["redacted"] is True
    assert by_field["data_source.auth.token_env"]["after"] == "CORE_TOKEN"
    assert "SUPERSECRET" not in _dump_all()

    client.put(
        f"/api/v1/reports/{report_id}/protected-terms-config",
        json={"set_ids": [], "terms": ["ឈ្មោះ"], "exclude_terms": []},
        headers=auth_headers,
    )
    (terms,) = _one("report.terms_config_update", report_id)["changes"]
    assert terms["field"] == "terms" and terms["added"] == ["ឈ្មោះ"]


def test_recording_a_deployment_terms_change_from_a_file_edit(auth_headers):
    from app import deployment_terms_sync as dts

    before = {"version": 1, "terms": ["a", "b"], "exclude_terms": []}
    after = {"version": 2, "terms": ["b", "c"], "exclude_terms": [], "source_paths": {"terms_file": "/etc/terms.txt"}}
    dts.record_change(before, after)
    event = _one("deployment_terms.change")
    assert event["actor_username"] == "system" and event["org_id"] is None
    assert event["changes"][0]["added"] == ["c"] and event["changes"][0]["removed"] == ["a"]

    dts.record_change(after, dict(after))  # same version: nothing moved
    dts.record_change(None, after)  # the very first sync is a baseline, not a change
    assert len(_events("deployment_terms.change")) == 1


# --- reading it ---------------------------------------------------------------


def test_the_audit_feed_needs_audit_view(auth_headers, make_local_user):
    _report(auth_headers)
    assert client.get("/api/v1/audit").status_code == 401
    _, plain = make_local_user("nosy", "pw-nosy-12345", ("ROLE_REPORT_ADMIN",))  # manages reports, can't audit
    assert client.get("/api/v1/audit", headers=plain).status_code == 403
    _, boss = make_local_user("boss", "pw-boss-12345", ("ROLE_ORG_ADMIN",))
    assert client.get("/api/v1/audit", headers=boss).status_code == 200


def test_the_feed_is_scoped_to_the_callers_own_organization(auth_headers, make_local_user):
    client.post("/api/v1/organizations", json={"id": "acme", "name": "Acme"}, headers=auth_headers)
    _, root_admin = make_local_user("root-admin", "pw-root-12345", ("ROLE_ORG_ADMIN",), org_id=ROOT_ORG_ID)
    _, acme_admin = make_local_user("acme-admin", "pw-acme-12345", ("ROLE_ORG_ADMIN",), org_id="acme")

    _report(root_admin, name="Root report")
    client.post("/api/v1/reports", files={"file": ("t.docx", _docx(), "application/octet-stream")}, data={"name": "Acme report"}, headers=acme_admin)

    mine = client.get("/api/v1/audit", params={"entity_type": "report"}, headers=acme_admin).json()
    assert {e["entity_label"] for e in mine["items"]} == {"Acme report"}
    assert {e["org_id"] for e in mine["items"]} == {"acme"}
    # Asking for another org's slice by id is refused (404, not "empty").
    assert client.get("/api/v1/audit", params={"org_id": ROOT_ORG_ID}, headers=acme_admin).status_code == 404
    # ...while the superuser sees across organizations.
    everyone = client.get("/api/v1/audit", params={"entity_type": "report"}, headers=auth_headers).json()
    assert {e["entity_label"] for e in everyone["items"]} == {"Root report", "Acme report"}


def test_filters_pagination_and_wildcards(auth_headers):
    ids = [_report(auth_headers, name=f"Report {n}") for n in range(3)]
    client.patch(f"/api/v1/reports/{ids[0]}", json={"name": "100% Complete_Report"}, headers=auth_headers)
    _user(auth_headers, username="dana")

    def get(**params):
        resp = client.get("/api/v1/audit", params=params, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    assert {e["action"] for e in get(entity_type="user")["items"]} == {"user.create"}
    assert {e["action"] for e in get(action="report")["items"]} == {"report.create", "report.update"}  # prefix
    assert {e["action"] for e in get(action="report.update")["items"]} == {"report.update"}  # exact
    assert len(get(entity_id=ids[1])["items"]) == 1
    assert len(get(actor="TESTADM")["items"]) == get()["total"]  # substring, case-insensitive
    assert get(actor="nobody")["total"] == 0

    # `%` and `_` in a search are literal characters, not SQL wildcards.
    assert get(q="100%")["total"] == 1
    assert get(q="%")["total"] == 1
    assert get(q="Complete_Report")["total"] == 1
    assert get(q="Complete-Report")["total"] == 0

    page1, page2 = get(limit=2, offset=0), get(limit=2, offset=2)
    assert page1["total"] == page2["total"] and len(page1["items"]) == 2
    assert not {e["id"] for e in page1["items"]} & {e["id"] for e in page2["items"]}
    stamps = [e["created_at"] for e in get(limit=200)["items"]]
    assert stamps == sorted(stamps, reverse=True)  # newest first

    assert get(since="2999-01-01T00:00:00Z")["total"] == 0
    assert get(until="2000-01-01T00:00:00Z")["total"] == 0
    assert get(since="2000-01-01", until="2999-01-01")["total"] == get()["total"]
    assert client.get("/api/v1/audit", params={"since": "yesterday-ish"}, headers=auth_headers).status_code == 400
    assert client.get("/api/v1/audit", params={"limit": 999}, headers=auth_headers).status_code == 422


def test_there_is_no_way_to_edit_or_delete_an_audit_row(auth_headers):
    _report(auth_headers)
    event_id = _events()[0]["id"]
    for method in ("put", "patch", "delete"):
        resp = getattr(client, method)(f"/api/v1/audit/{event_id}", headers=auth_headers)
        assert resp.status_code in (404, 405)
    assert client.post("/api/v1/audit", json={}, headers=auth_headers).status_code == 405


@pytest.mark.parametrize("action", ["report.create", "report.file_replace", "report.template_download"])
def test_template_actions_carry_a_checksum(auth_headers, action):
    report_id = _report(auth_headers)
    client.put(
        f"/api/v1/reports/{report_id}/file", files={"file": ("n.docx", _docx() + b"", "application/octet-stream")}, headers=auth_headers
    )
    client.get(f"/api/v1/reports/{report_id}/file", headers=auth_headers)
    assert len(_events(action, report_id)[0]["details"]["sha256"]) == 64
