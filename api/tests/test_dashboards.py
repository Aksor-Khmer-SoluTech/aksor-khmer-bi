"""Dashboards (app/dashboards.py) and data alerts (app/data_alerts.py) -- Phase 4. Checked: tiles and their checks,
filters shared by name, sharing with roles (each viewer's own access to each tile's dataset), owner-only changes;
and an alert that checks a measure on its schedule, emails when it crosses (once, by default), says what it saw in
its run, and may only watch what its creator could analyze."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import analyze, data_alerts, db, job_delivery
from app.celery_app import celery_app
from app.main import app
from app.rbac import ROOT_ORG_ID
from tests.test_analyze import PP, _dataset
from tests.test_job_delivery import FakeSmtp, _mail_server

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    analyze.clear_cache()
    monkeypatch.setattr(job_delivery, "OUTPUT_DIR", tmp_path / "job_outputs")
    monkeypatch.setattr(celery_app, "send_task", lambda name, args=None, **kw: type("R", (), {"id": "stub"})())
    yield
    analyze.clear_cache()


@pytest.fixture
def smtp():
    server = FakeSmtp()
    yield server
    server.close()


def _user(make_local_user, auth_headers, name, roles=(), analyze_use=False):
    user_id, headers = make_local_user(name, f"pw-{name}-1", roles)
    if analyze_use:
        assert client.post("/api/v1/grants/permissions", headers=auth_headers, json={"user_id": user_id, "permission_code": "analyze:use"}).status_code == 200
    return user_id, headers


def _tile(tile_id="t1", **extra):
    return {"id": tile_id, "title": "Sales by branch", "dataset": "branch-sales", "values": {"p_branch": "BR01"},
            "layout": {"rows": ["branch"], "values": ["net"]}, "view": "bar", "width": 2, **extra}


def _dashboard(headers, tiles=None, filters=None):
    created = client.post("/api/v1/dashboards", headers=headers, json={"title": "Sales overview"})
    assert created.status_code == 200, created.text
    body = {"title": "Sales overview", "tiles": tiles if tiles is not None else [_tile()], "filters": filters or {}}
    resp = client.put(f"/api/v1/dashboards/{created.json()['id']}", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _role_id(headers, name):
    return next(r["id"] for r in client.get("/api/v1/roles", params={"org_id": ROOT_ORG_ID}, headers=headers).json() if r["name"] == name)


# --- dashboards -------------------------------------------------------------------------------------------------------


def test_a_dashboard_runs_its_tiles(auth_headers, make_local_user):
    _dataset(auth_headers)
    _, owner = _user(make_local_user, auth_headers, "owner", analyze_use=True)
    kpi = _tile("t2", title="Net sales", layout={"values": ["net", "orders"]}, view="kpi", width=1)
    dash = _dashboard(owner, tiles=[_tile(), kpi])
    assert [t["id"] for t in dash["tiles"]] == ["t1", "t2"] and dash["can_edit"] is True
    assert [f["name"] for f in dash["filter_bar"]] == ["p_branch"] and dash["filter_bar"][0]["tiles"] == ["t1", "t2"]
    result = client.post(f"/api/v1/dashboards/{dash['id']}/tiles/t2/run", headers=owner, json={}).json()
    assert result["total"][0] == {"v": 185000, "t": "185,000 ៛"} and result["tile"]["view"] == "kpi"
    by_branch = client.post(f"/api/v1/dashboards/{dash['id']}/tiles/t1/run", headers=owner, json={"filters": {"p_branch": "BR02"}}).json()
    assert by_branch["values_used"] == {"p_branch": "BR02"} and [k[0] for k in by_branch["row_keys"]][1] == PP
    assert client.post(f"/api/v1/dashboards/{dash['id']}/tiles/nope/run", headers=owner, json={}).status_code == 404


@pytest.mark.parametrize("tile, fragment", [
    ({"dataset": "nope"}, "no dataset 'nope'"),
    ({"layout": {"rows": ["cost"], "values": ["net"]}}, "isn't a field"),  # hidden
    ({"view": "kpi"}, "a KPI is one number"),
    ({"title": ""}, "needs a title"),
])
def test_tiles_are_checked(auth_headers, make_local_user, tile, fragment):
    _dataset(auth_headers)
    _, owner = _user(make_local_user, auth_headers, "owner", analyze_use=True)
    created = client.post("/api/v1/dashboards", headers=owner, json={"title": "x"}).json()
    resp = client.put(f"/api/v1/dashboards/{created['id']}", headers=owner, json={"title": "x", "tiles": [_tile(**tile)]})
    assert resp.status_code == 400 and fragment in resp.json()["detail"], resp.text


def test_sharing_with_a_role_and_each_viewers_own_access(auth_headers, make_local_user):
    dataset = _dataset(auth_headers)
    _, owner = _user(make_local_user, auth_headers, "owner", analyze_use=True)
    viewer_id, viewer = _user(make_local_user, auth_headers, "viewer", roles=("ROLE_REPORT_VIEWER",))  # no analyze:use
    dash = _dashboard(owner)
    # Not shared: a viewer doesn't see it at all.
    assert client.get("/api/v1/dashboards", headers=viewer).json() == []
    assert client.get(f"/api/v1/dashboards/{dash['id']}", headers=viewer).status_code == 404
    shared = client.put(f"/api/v1/dashboards/{dash['id']}/sharing", headers=owner, json={"role_ids": [_role_id(auth_headers, "ROLE_REPORT_VIEWER")]})
    assert shared.status_code == 200 and len(shared.json()["shared_role_ids"]) == 1
    listed = client.get("/api/v1/dashboards", headers=viewer).json()
    assert [(d["title"], d["mine"], d["shared"]) for d in listed] == [("Sales overview", False, True)]
    assert client.get(f"/api/v1/dashboards/{dash['id']}", headers=viewer).json()["can_edit"] is False
    assert client.post(f"/api/v1/dashboards/{dash['id']}/tiles/t1/run", headers=viewer, json={}).status_code == 200
    # Viewers can't change it.
    assert client.put(f"/api/v1/dashboards/{dash['id']}", headers=viewer, json={"title": "mine now", "tiles": []}).status_code == 403
    assert client.delete(f"/api/v1/dashboards/{dash['id']}", headers=viewer).status_code == 403

    # Restrict the dataset: the viewer only gets their grant's values -- the dashboard never widens that.
    client.put(f"/api/v1/datasets/{dataset['id']}/access/mode", headers=auth_headers, json={"mode": "restricted"})
    analyze.clear_cache()
    denied = client.post(f"/api/v1/dashboards/{dash['id']}/tiles/t1/run", headers=viewer, json={})
    assert denied.status_code == 403 and "Branch sales" in denied.json()["detail"]
    client.post(f"/api/v1/datasets/{dataset['id']}/access", headers=auth_headers, json={
        "subject_type": "user", "subject_id": viewer_id, "level": "run", "parameter_limits": {"p_branch": ["BR02"]},
    })
    bar = client.get(f"/api/v1/dashboards/{dash['id']}", headers=viewer).json()["filter_bar"]
    assert [o["value"] for o in bar[0]["options"]] == ["BR02"]
    assert client.post(f"/api/v1/dashboards/{dash['id']}/tiles/t1/run", headers=viewer, json={}).status_code == 403  # the tile's BR01
    assert client.post(f"/api/v1/dashboards/{dash['id']}/tiles/t1/run", headers=viewer, json={"filters": {"p_branch": "BR02"}}).status_code == 200


def test_making_a_dashboard_needs_analyze(auth_headers, make_local_user):
    _, viewer = _user(make_local_user, auth_headers, "viewer", roles=("ROLE_REPORT_VIEWER",))
    assert client.post("/api/v1/dashboards", headers=viewer, json={"title": "x"}).status_code == 403
    assert client.get("/api/v1/dashboards", headers=viewer).json() == []


def test_dashboard_changes_are_audited(auth_headers, make_local_user):
    _dataset(auth_headers)
    _, owner = _user(make_local_user, auth_headers, "owner", analyze_use=True)
    dash = _dashboard(owner)
    client.put(f"/api/v1/dashboards/{dash['id']}/sharing", headers=owner, json={"role_ids": [_role_id(auth_headers, "ROLE_REPORT_VIEWER")]})
    client.delete(f"/api/v1/dashboards/{dash['id']}", headers=owner)
    with db.SessionLocal() as session:
        actions = [e.action for e in session.query(db.AuditEvent).filter(db.AuditEvent.entity_id == dash["id"]).order_by(db.AuditEvent.created_at)]
    assert actions == ["dashboard.create", "dashboard.update", "dashboard.share", "dashboard.delete"]


# --- data alerts ------------------------------------------------------------------------------------------------------


def _alert(headers, expect=200, **config):
    body = {
        "name": "Net sales watch", "job_type": "data_alert", "trigger_type": "cron", "cron_expression": "0 8 * * *",
        "config": {"dataset": "branch-sales", "values": {"p_branch": "BR01"}, "measure": "net", "condition": "below",
                   "threshold": 200000, "email": {"connection": "company-mail", "to": ["finance@example.com"]}, **config},
    }
    resp = client.post("/api/v1/jobs", params={"org_id": ROOT_ORG_ID}, headers=headers, json=body)
    assert resp.status_code == expect, resp.text
    return resp.json()


def _check(headers, job) -> str:
    """One check, as the worker runs it: a queued run, the executor, then the run marked done with its summary."""
    run_id = client.post(f"/api/v1/jobs/{job['id']}/run", headers=headers).json()["id"]
    summary = data_alerts.run(job["config"], job["id"], run_id)
    with db.SessionLocal() as session:
        run = session.get(db.JobRun, run_id)
        run.status, run.result_summary, run.finished_at = "succeeded", summary, datetime.now(timezone.utc).isoformat()
        session.commit()
    return summary


def test_an_alert_emails_once_when_it_crosses(auth_headers, smtp):
    _dataset(auth_headers)
    _mail_server(auth_headers, smtp.port)
    job = _alert(auth_headers)
    assert job["config"]["title"] == "Branch sales: Net sales" and job["config"]["repeat"] == "on_change"

    first = _check(auth_headers, job)
    assert first == "Triggered: Net sales is 185,000 ៛, below 200,000 ៛ -- emailed 1 person"
    rcpts, message = smtp.messages[0]
    assert rcpts == ["finance@example.com"] and message["Subject"] == "Alert: Branch sales: Net sales"
    assert "Net sales is 185,000 ៛ -- it drops below 200,000 ៛." in message.get_content()

    second = _check(auth_headers, job)
    assert second.startswith("Triggered:") and "already emailed, not again" in second and len(smtp.messages) == 1


def test_an_alert_that_doesnt_cross_says_what_it_saw(auth_headers, smtp):
    _dataset(auth_headers)
    _mail_server(auth_headers, smtp.port)
    job = _alert(auth_headers, threshold=100000)
    assert _check(auth_headers, job) == "Not triggered: Net sales is 185,000 ៛ (alerts when it drops below 100,000 ៛)"
    assert smtp.messages == []


def test_every_time_emails_on_each_check(auth_headers, smtp):
    _dataset(auth_headers)
    _mail_server(auth_headers, smtp.port)
    job = _alert(auth_headers, condition="above", threshold=5, repeat="every_time", measure="__rows")  # 6 rows
    _check(auth_headers, job)
    _check(auth_headers, job)
    assert len(smtp.messages) == 2


@pytest.mark.parametrize("config, fragment", [
    ({"dataset": "nope"}, "Choose a dataset you may analyze"),
    ({"measure": "profit"}, "Choose the measure"),
    ({"condition": "equals"}, "rises above or drops below"),
    ({"threshold": "lots"}, "must be a number"),
    ({"email": {"connection": "no-such-mail", "to": ["a@example.com"]}}, "Choose a mail server"),
    ({"email": {"connection": "company-mail", "to": []}}, "at least one address"),
])
def test_an_alert_is_checked_when_saved(auth_headers, smtp, config, fragment):
    _dataset(auth_headers)
    _mail_server(auth_headers, smtp.port)
    resp = _alert(auth_headers, expect=400, **config)
    assert fragment in resp["detail"]


def test_an_alert_only_watches_what_its_creator_may_analyze(auth_headers, make_local_user, smtp):
    dataset = _dataset(auth_headers)
    _mail_server(auth_headers, smtp.port)
    user_id, operator = make_local_user("operator", "pw-operator-1", ("ROLE_ORG_ADMIN",))
    # ROLE_ORG_ADMIN holds dataset:manage, so it isn't limited; a job:manage holder without it is.
    limited_id, limited = _user(make_local_user, auth_headers, "limited", roles=("ROLE_JOB_OPERATOR",), analyze_use=True)
    client.post("/api/v1/grants/permissions", headers=auth_headers, json={"user_id": limited_id, "permission_code": "job:manage"})
    assert _alert(operator)["config"]["dataset"] == "branch-sales"
    client.put(f"/api/v1/datasets/{dataset['id']}/access/mode", headers=auth_headers, json={"mode": "restricted"})
    assert _alert(limited, expect=400)["detail"] == "Choose a dataset you may analyze"
