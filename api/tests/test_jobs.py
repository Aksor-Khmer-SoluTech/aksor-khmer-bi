import pytest
from fastapi.testclient import TestClient

from app.celery_app import celery_app
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


@pytest.fixture(autouse=True)
def stub_celery_send_task(monkeypatch):
    """These router tests exercise permission checks, org-scoping, and
    JobRun bookkeeping -- not Celery's ability to actually publish to a
    broker, which would otherwise require a live Redis just to run this
    file. Real end-to-end task execution (a live Redis + a real Celery
    worker actually running app/job_executors.py code, including a
    forced-failure retry case) is verified separately -- see
    docs/deployment.md's job-scheduling section for how, matching the
    same standard applied to Postgres/LDAP elsewhere in this project.
    """
    sent = []

    class _StubResult:
        id = "stub-task-id"

    def _stub_send_task(name, args=None, **kwargs):
        sent.append((name, args))
        return _StubResult()

    monkeypatch.setattr(celery_app, "send_task", _stub_send_task)
    return sent


def _create_job(auth_headers, **overrides) -> dict:
    body = {
        "name": "Nightly sweep",
        "job_type": "file_output",
        "config": {"destination_path": "/tmp/out-{job_id}.txt", "source": "static", "content": "hi"},
        "trigger_type": "cron",
        "cron_expression": "0 2 * * *",
    }
    body.update(overrides)
    resp = client.post("/api/v1/jobs", params={"org_id": ROOT_ORG_ID}, json=body, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_and_get_job(auth_headers):
    created = _create_job(auth_headers)
    resp = client.get(f"/api/v1/jobs/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Nightly sweep"
    assert resp.json()["is_enabled"] is True


def test_create_job_requires_permission(make_local_user):
    _, headers = make_local_user("nojobperm", "pw12345", role_names=())
    resp = client.post(
        "/api/v1/jobs",
        params={"org_id": ROOT_ORG_ID},
        json={"name": "x", "job_type": "file_output", "config": {}, "trigger_type": "cron", "cron_expression": "0 2 * * *"},
        headers=headers,
    )
    assert resp.status_code == 403


def test_job_operator_can_trigger_but_not_manage(make_local_user, auth_headers):
    created = _create_job(auth_headers)
    _, operator_headers = make_local_user("operator1", "pw12345", role_names=("ROLE_JOB_OPERATOR",))

    run_resp = client.post(f"/api/v1/jobs/{created['id']}/run", headers=operator_headers)
    assert run_resp.status_code == 200

    update_resp = client.patch(f"/api/v1/jobs/{created['id']}", json={"name": "renamed"}, headers=operator_headers)
    assert update_resp.status_code == 403


def test_create_cron_job_validates_expression(auth_headers):
    resp = client.post(
        "/api/v1/jobs",
        params={"org_id": ROOT_ORG_ID},
        json={
            "name": "bad cron",
            "job_type": "file_output",
            "config": {"destination_path": "/tmp/x", "source": "static", "content": "x"},
            "trigger_type": "cron",
            "cron_expression": "not a cron expression",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_create_interval_job_requires_positive_seconds(auth_headers):
    resp = client.post(
        "/api/v1/jobs",
        params={"org_id": ROOT_ORG_ID},
        json={
            "name": "bad interval",
            "job_type": "file_output",
            "config": {},
            "trigger_type": "interval",
            "interval_seconds": 0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_create_one_off_job_requires_run_at(auth_headers):
    resp = client.post(
        "/api/v1/jobs",
        params={"org_id": ROOT_ORG_ID},
        json={"name": "bad one-off", "job_type": "file_output", "config": {}, "trigger_type": "one_off"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_update_job_disable(auth_headers):
    created = _create_job(auth_headers)
    resp = client.patch(f"/api/v1/jobs/{created['id']}", json={"is_enabled": False}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_enabled"] is False


def test_delete_job(auth_headers):
    created = _create_job(auth_headers)
    resp = client.delete(f"/api/v1/jobs/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get(f"/api/v1/jobs/{created['id']}", headers=auth_headers).status_code == 404


def test_run_job_creates_a_queued_run_and_appears_in_history(auth_headers):
    created = _create_job(auth_headers)
    run = client.post(f"/api/v1/jobs/{created['id']}/run", headers=auth_headers)
    assert run.status_code == 200
    assert run.json()["triggered_by"] == "manual"
    assert run.json()["status"] == "queued"

    history = client.get(f"/api/v1/jobs/{created['id']}/runs", headers=auth_headers)
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["id"] == run.json()["id"]


def test_run_job_requires_job_trigger_permission(make_local_user, auth_headers):
    created = _create_job(auth_headers)
    _, headers = make_local_user("notrigger", "pw12345", role_names=())
    resp = client.post(f"/api/v1/jobs/{created['id']}/run", headers=headers)
    assert resp.status_code == 403


def test_jobs_are_org_scoped(auth_headers, make_local_user):
    client.post("/api/v1/organizations", json={"id": "jobsorg", "name": "Jobs Org"}, headers=auth_headers)
    root_org_job = _create_job(auth_headers, name="root org job")
    other_org_job = client.post(
        "/api/v1/jobs",
        params={"org_id": "jobsorg"},
        json={
            "name": "org-scoped job",
            "job_type": "file_output",
            "config": {"destination_path": "/tmp/x", "source": "static", "content": "x"},
            "trigger_type": "cron",
            "cron_expression": "0 2 * * *",
        },
        headers=auth_headers,
    ).json()

    _, root_operator_headers = make_local_user(
        "jobsorgoperator", "pw12345", role_names=("ROLE_JOB_OPERATOR",), org_id=ROOT_ORG_ID
    )
    # A ROOT_ORG_ID job operator cannot see a job belonging to jobsorg...
    forbidden = client.get(f"/api/v1/jobs/{other_org_job['id']}", headers=root_operator_headers)
    assert forbidden.status_code == 404
    # ...but can see the root-org one.
    ok = client.get(f"/api/v1/jobs/{root_org_job['id']}", headers=root_operator_headers)
    assert ok.status_code == 200
