"""The admin dashboard's backend surface: render telemetry
(report_render_log, written from _render_one), access-denied telemetry
(access_denied_events, written from auth.py's require_* dependencies and
the report-run-denied path), and the three new aggregate endpoints
(GET /reports/analytics/summary, GET /jobs/summary,
GET /security/activity). See specs/admin_dashboard_design.md.
"""
from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def _docx_bytes(text: str = "Hello {{ name }}") -> bytes:
    doc = Document()
    doc.add_paragraph(text)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _register(auth_headers, name: str = "Dash Report") -> str:
    resp = client.post(
        "/api/v1/reports",
        files={"file": ("t.docx", _docx_bytes(), "application/octet-stream")},
        data={"name": name},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


def _render_events(report_id: str) -> list[db.RenderEvent]:
    with db.SessionLocal() as session:
        return list(session.execute(select(db.RenderEvent).where(db.RenderEvent.report_id == report_id)).scalars().all())


def _denied_events(permission_code: str | None = None) -> list[db.AccessDeniedEvent]:
    with db.SessionLocal() as session:
        query = select(db.AccessDeniedEvent)
        if permission_code is not None:
            query = query.where(db.AccessDeniedEvent.permission_code == permission_code)
        return list(session.execute(query).scalars().all())


# --- report_render_log ----------------------------------------------------


def test_public_render_records_a_render_event(auth_headers):
    report_id = _register(auth_headers)
    resp = client.post(f"/api/v1/reports/{report_id}/render?format=docx", json={"name": "x"})
    assert resp.status_code == 200, resp.text

    rows = _render_events(report_id)
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].triggered_by == "public"
    assert rows[0].user_id is None
    assert rows[0].format == "docx"
    assert rows[0].duration_ms is not None and rows[0].duration_ms >= 0


def test_batch_render_records_one_event_per_context(auth_headers):
    report_id = _register(auth_headers)
    resp = client.post(f"/api/v1/reports/{report_id}/render/batch?format=docx", json=[{"name": "a"}, {"name": "b"}])
    assert resp.status_code == 200, resp.text
    assert len(_render_events(report_id)) == 2


def test_run_records_a_render_event_with_user_id(auth_headers, make_local_user):
    report_id = _register(auth_headers)
    user_id, headers = make_local_user("run_user", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    resp = client.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {}, "format": "docx"}, headers=headers)
    assert resp.status_code == 200, resp.text

    rows = _render_events(report_id)
    assert len(rows) == 1
    assert rows[0].triggered_by == "run"
    assert rows[0].user_id == user_id


def test_render_failure_records_an_error_event_with_no_duration(auth_headers, monkeypatch):
    from doc_engine import ConversionError

    from app.routers import reports as reports_router

    def _boom(*args, **kwargs):
        raise ConversionError("simulated failure")

    monkeypatch.setattr(reports_router, "doc_render", _boom)

    report_id = _register(auth_headers)
    resp = client.post(f"/api/v1/reports/{report_id}/render?format=docx", json={"name": "x"})
    assert resp.status_code == 500

    rows = _render_events(report_id)
    assert len(rows) == 1
    assert rows[0].status == "error"
    assert rows[0].duration_ms is None


# --- GET /reports/analytics/summary -----------------------------------


def test_analytics_summary_aggregates_across_render_kinds(auth_headers, make_local_user):
    report_id = _register(auth_headers, name="Popular One")
    client.post(f"/api/v1/reports/{report_id}/render?format=docx", json={"name": "x"})
    _, run_headers = make_local_user("analytics_user", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    client.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {}, "format": "docx"}, headers=run_headers)

    resp = client.get("/api/v1/reports/analytics/summary", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    by_id = {row["report_id"]: row for row in resp.json()}
    assert by_id[report_id]["name"] == "Popular One"
    assert by_id[report_id]["render_count"] == 2
    assert by_id[report_id]["error_count"] == 0
    assert by_id[report_id]["avg_duration_ms"] is not None


def test_analytics_summary_requires_report_view(auth_headers, make_local_user):
    _register(auth_headers)
    _, headers = make_local_user("no_perms", "pw12345", role_names=())
    resp = client.get("/api/v1/reports/analytics/summary", headers=headers)
    assert resp.status_code == 403


def test_analytics_summary_days_window_excludes_old_rows(auth_headers):
    report_id = _register(auth_headers)
    client.post(f"/api/v1/reports/{report_id}/render?format=docx", json={"name": "x"})
    with db.SessionLocal() as session:
        row = session.execute(select(db.RenderEvent).where(db.RenderEvent.report_id == report_id)).scalars().one()
        row.created_at = "2000-01-01T00:00:00+00:00"
        session.commit()

    resp = client.get("/api/v1/reports/analytics/summary", params={"days": 30}, headers=auth_headers)
    assert resp.status_code == 200
    assert report_id not in {row["report_id"] for row in resp.json()}


# --- access_denied_events ---------------------------------------------


def test_missing_global_permission_records_access_denied(make_local_user):
    _, headers = make_local_user("cant_manage", "pw12345", role_names=())
    resp = client.post(
        "/api/v1/reports",
        files={"file": ("t.docx", _docx_bytes(), "application/octet-stream")},
        data={"name": "nope"},
        headers=headers,
    )
    assert resp.status_code == 403
    rows = _denied_events("report:manage")
    assert any(r.username == "cant_manage" for r in rows)


def test_missing_report_permission_records_access_denied_with_resource(auth_headers, make_local_user):
    report_id = _register(auth_headers)
    _, headers = make_local_user("cant_edit_report", "pw12345", role_names=())
    resp = client.patch(f"/api/v1/reports/{report_id}", json={"name": "renamed"}, headers=headers)
    assert resp.status_code == 403
    rows = [r for r in _denied_events() if r.resource == report_id]
    assert any(r.username == "cant_edit_report" for r in rows)


def test_run_denied_by_grant_limit_records_access_denied(auth_headers, make_local_user):
    report_id = _register(auth_headers, name="Branch report")
    resp = client.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": [{"name": "p_branch", "label": "Branch", "options": [{"value": "BR01"}, {"value": "BR02"}]}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    user_id, headers = make_local_user("limited_runner", "pw12345", role_names=())
    grant_resp = client.post(
        "/api/v1/grants/reports",
        json={
            "subject_type": "user",
            "subject_id": user_id,
            "report_id": report_id,
            "permission_level": "render",
            "parameter_limits": {"p_branch": ["BR01"]},
        },
        headers=auth_headers,
    )
    assert grant_resp.status_code == 200, grant_resp.text

    resp = client.post(
        f"/api/v1/reports/{report_id}/run",
        json={"parameters": {"p_branch": "BR02"}, "format": "docx"},
        headers=headers,
    )
    assert resp.status_code == 403
    rows = [r for r in _denied_events("report:run") if r.resource == report_id]
    assert any(r.username == "limited_runner" for r in rows)


def test_a_400_parameter_error_is_not_recorded_as_access_denied(auth_headers):
    report_id = _register(auth_headers)  # no parameters configured at all
    resp = client.post(
        f"/api/v1/reports/{report_id}/run", json={"parameters": {"unexpected": "x"}, "format": "docx"}, headers=auth_headers
    )
    assert resp.status_code == 400, resp.text  # "Unknown parameter(s): unexpected" -- malformed request, not a denial
    assert _denied_events("report:run") == []


# --- GET /jobs/summary --------------------------------------------------


def test_jobs_summary_counts(auth_headers, monkeypatch):
    from app.celery_app import celery_app

    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: None)

    resp = client.post(
        "/api/v1/jobs",
        params={"org_id": ROOT_ORG_ID},
        json={
            "name": "Nightly",
            "job_type": "file_output",
            "config": {"destination_path": "/tmp/x.txt", "source": "static", "content": "hi"},
            "trigger_type": "cron",
            "cron_expression": "0 2 * * *",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    summary = client.get("/api/v1/jobs/summary", headers=auth_headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["total_jobs"] >= 1
    assert body["enabled_jobs"] >= 1


def test_jobs_summary_requires_job_view(make_local_user):
    _, headers = make_local_user("no_job_view", "pw12345", role_names=())
    resp = client.get("/api/v1/jobs/summary", headers=headers)
    assert resp.status_code == 403


# --- GET /security/activity ---------------------------------------------


def test_security_activity_lists_failed_login(auth_headers, make_local_user):
    make_local_user("will_fail_login", "correctpassword", role_names=())
    bad = client.get("/api/v1/auth/verify", auth=("will_fail_login", "wrongpassword"))
    assert bad.status_code == 401

    resp = client.get("/api/v1/security/activity", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert any(i["kind"] == "login_failed" and i["username"] == "will_fail_login" for i in items)


def test_security_activity_lists_access_denied(make_local_user, auth_headers):
    _, headers = make_local_user("will_be_denied", "pw12345", role_names=())
    client.post(
        "/api/v1/reports",
        files={"file": ("t.docx", _docx_bytes(), "application/octet-stream")},
        data={"name": "nope"},
        headers=headers,
    )
    resp = client.get("/api/v1/security/activity", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()
    assert any(i["kind"] == "access_denied" and i["username"] == "will_be_denied" for i in items)


def test_security_activity_requires_audit_view(make_local_user):
    _, headers = make_local_user("no_audit_view", "pw12345", role_names=())
    resp = client.get("/api/v1/security/activity", headers=headers)
    assert resp.status_code == 403


def test_security_activity_unusual_flag_requires_at_least_three_failures(make_local_user):
    make_local_user("flappy_login", "correctpassword", role_names=())
    admin_id, admin_headers = make_local_user("audit_admin", "pw12345", role_names=("ROLE_ORG_ADMIN",))

    for _ in range(2):
        client.get("/api/v1/auth/verify", auth=("flappy_login", "wrong"))
    resp = client.get("/api/v1/security/activity", headers=admin_headers)
    items = [i for i in resp.json() if i["username"] == "flappy_login"]
    assert len(items) == 2
    assert all(not i["unusual"] for i in items)

    client.get("/api/v1/auth/verify", auth=("flappy_login", "wrong"))
    resp = client.get("/api/v1/security/activity", headers=admin_headers)
    items = [i for i in resp.json() if i["username"] == "flappy_login"]
    assert len(items) == 3
    assert all(i["unusual"] for i in items)
