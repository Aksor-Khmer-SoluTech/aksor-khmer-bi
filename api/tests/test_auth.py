from fastapi.testclient import TestClient

from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)


def test_verify_succeeds_with_correct_credentials(auth_headers):
    resp = client.get("/api/v1/auth/verify", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is True


def test_verify_reports_superuser_for_break_glass_credentials(auth_headers):
    body = client.get("/api/v1/auth/verify", headers=auth_headers).json()
    assert body["is_superuser"] is True
    assert body["org_id"] is None


def test_verify_reports_org_and_effective_permissions_for_database_user(make_local_user):
    _, headers = make_local_user("permcheck", "pw12345", role_names=("ROLE_REPORT_VIEWER",))
    body = client.get("/api/v1/auth/verify", headers=headers).json()
    assert body["is_superuser"] is False
    assert body["org_id"] == ROOT_ORG_ID
    assert set(body["permissions"]) == {"report:view", "report:render"}


def test_verify_fails_with_wrong_password():
    import base64

    token = base64.b64encode(b"testadmin:wrongpassword").decode()
    resp = client.get("/api/v1/auth/verify", headers={"Authorization": f"Basic {token}"})
    assert resp.status_code == 401


def test_verify_fails_with_no_credentials():
    resp = client.get("/api/v1/auth/verify")
    assert resp.status_code == 401


def test_verify_fails_closed_when_unconfigured(monkeypatch, auth_headers):
    # Even with an otherwise-correct header, missing server config must
    # reject everything (fail closed) rather than let it through.
    monkeypatch.delenv("PORTAL_USERNAME", raising=False)
    monkeypatch.delenv("PORTAL_PASSWORD", raising=False)
    resp = client.get("/api/v1/auth/verify", headers=auth_headers)
    assert resp.status_code == 503
