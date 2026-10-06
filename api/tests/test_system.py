from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_metrics_requires_auth():
    resp = client.get("/api/v1/system/metrics")
    assert resp.status_code == 401


def test_metrics_requires_settings_manage(make_local_user):
    _, headers = make_local_user("nosettingsperm", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    resp = client.get("/api/v1/system/metrics", headers=headers)
    assert resp.status_code == 403


def test_metrics_shape(auth_headers):
    resp = client.get("/api/v1/system/metrics", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    assert 0.0 <= body["cpu_percent"] <= 100.0
    assert len(body["cpu_percent_per_core"]) == body["cpu_thread_count"]
    assert body["cpu_core_count"] >= 1
    assert body["cpu_thread_count"] >= body["cpu_core_count"]

    assert body["memory_total_bytes"] > 0
    assert 0.0 <= body["memory_percent"] <= 100.0

    assert isinstance(body["disks"], list)
    for disk in body["disks"]:
        assert disk["total_bytes"] >= 0
        assert 0.0 <= disk["percent"] <= 100.0

    assert body["process_thread_count"] >= 1
    assert body["process_count"] >= 1
    assert body["uptime_seconds"] >= 0
