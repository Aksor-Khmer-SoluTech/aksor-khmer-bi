"""GET /api/v1/me/dashboard -- a person's own report activity, and only theirs."""
from fastapi.testclient import TestClient

from app import audit, db
from app.main import app

http = TestClient(app)


def _run(actor, report_id, ok=True, n=2):
    audit.record(
        actor, "report.run" if ok else "report.run_failed", "report", report_id, label=f"Report {report_id}", summary="x",
        details={"via": "run", "format": "pdf", "parameters_selected": n, **({} if ok else {"reason": "boom"})},
    )


def test_it_summarises_only_the_callers_own_runs(auth_headers, make_local_user):
    me = http.get("/api/v1/auth/me", headers=auth_headers).json()
    mine = audit.Actor(username=me["username"], user_id=me.get("user_id"), org_id=me.get("org_id"))
    other = audit.Actor(username="someone-else", user_id="not-me")
    for rid in ("a", "a", "b"):
        _run(mine, rid)
    _run(mine, "b", ok=False)
    for _ in range(5):
        _run(other, "a")

    body = http.get("/api/v1/me/dashboard", headers=auth_headers).json()
    assert body["runs_30d"] == 3 and body["runs_7d"] == 3 and body["failed_30d"] == 1
    assert body["top_reports"][0] == {"report_id": "a", "name": "Report a", "runs": 2}
    assert body["recent"][0]["ok"] is False and body["recent"][0]["reason"] == "boom"
    assert all(r["parameters_selected"] == 2 for r in body["recent"])
    assert len(body["daily"]) == 30
    assert body["daily"][-1]["runs"] == 3 and body["daily"][-1]["failed"] == 1
    assert sum(d["runs"] for d in body["daily"]) == 3


def test_it_needs_a_signed_in_user():
    assert http.get("/api/v1/me/dashboard").status_code == 401


def test_a_new_user_gets_an_empty_dashboard(auth_headers):
    body = http.get("/api/v1/me/dashboard", headers=auth_headers).json()
    assert body["runs_30d"] == 0 and body["recent"] == [] and body["last_run_at"] is None


def test_a_database_user_sees_their_own_rows_by_user_id(make_local_user):
    user_id, headers = make_local_user("demo", "pw-demo-1234", ())
    _run(audit.Actor(username="demo", user_id=user_id), "a")
    _run(audit.Actor(username="demo", user_id="a-different-account"), "a")  # same name, other account
    body = http.get("/api/v1/me/dashboard", headers=headers).json()
    assert body["runs_30d"] == 1
