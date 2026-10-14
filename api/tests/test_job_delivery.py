"""Report jobs that email their files and split them by a filter (app/job_delivery.py, app/mailer.py), and the Mail
Server connections they send through -- tested against a real SMTP conversation with a small local server, real
rendered documents, and real unspaced Khmer in subjects and file names."""
from __future__ import annotations

import socket
import socketserver
import threading
from email import message_from_bytes, policy
from io import BytesIO

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient

from app import db, job_delivery, mailer, report_data
from app.celery_app import celery_app
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)

KHMER_SUBJECT = "របាយការណ៍លក់ប្រចាំថ្ងៃ"
BRANCHES = [
    {"value": "BR01", "label": "ភ្នំពេញ"},
    {"value": "BR02", "label": "សៀមរាប"},
    {"value": "BR03", "label": "បាត់ដំបង"},
]


# --- a small SMTP server -------------------------------------------------------------------------------------------


class FakeSmtp:
    """Speaks enough SMTP for smtplib: records each accepted message; `refuse` rejects RCPT for some addresses,
    `data_reply` overrides the answer to DATA (e.g. a 452 'try later')."""

    def __init__(self):
        self.messages: list = []
        self.refuse: set[str] = set()
        self.data_reply: str | None = None
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.wfile.write(b"220 fake ESMTP\r\n")
                rcpts: list[str] = []
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    cmd = line.decode(errors="replace").strip()
                    upper = cmd.upper()
                    if upper.startswith(("EHLO", "HELO")):
                        self.wfile.write(b"250-fake\r\n250 8BITMIME\r\n")
                    elif upper.startswith("MAIL FROM"):
                        rcpts = []
                        self.wfile.write(b"250 OK\r\n")
                    elif upper.startswith("RCPT TO"):
                        address = cmd.split(":", 1)[1].strip().strip("<>")
                        if address in fake.refuse:
                            self.wfile.write(b"550 mailbox unavailable\r\n")
                        else:
                            rcpts.append(address)
                            self.wfile.write(b"250 OK\r\n")
                    elif upper == "DATA":
                        if fake.data_reply:
                            self.wfile.write(fake.data_reply.encode() + b"\r\n")
                            continue
                        self.wfile.write(b"354 go ahead\r\n")
                        data = b""
                        while True:
                            chunk = self.rfile.readline()
                            if chunk in (b".\r\n", b".\n", b""):
                                break
                            data += chunk[1:] if chunk.startswith(b"..") else chunk
                        fake.messages.append((rcpts, message_from_bytes(data, policy=policy.default)))
                        self.wfile.write(b"250 queued\r\n")
                    elif upper in ("RSET", "NOOP"):
                        self.wfile.write(b"250 OK\r\n")
                    elif upper == "QUIT":
                        self.wfile.write(b"221 bye\r\n")
                        return
                    else:
                        self.wfile.write(b"502 not implemented\r\n")

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def smtp():
    server = FakeSmtp()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(job_delivery, "OUTPUT_DIR", tmp_path / "job_outputs")
    monkeypatch.setattr(celery_app, "send_task", lambda name, args=None, **kw: type("R", (), {"id": "stub"})())


@pytest.fixture
def erp(monkeypatch):
    """The report's REST data source: two sales rows per branch, none for BR03."""

    def handler(request: httpx.Request) -> httpx.Response:
        branch = request.url.params["branch"]
        rows = [] if branch == "BR03" else [{"item": f"{branch}-a", "amount": 10}, {"item": f"{branch}-b", "amount": 5}]
        return httpx.Response(200, json={"rows": rows})

    monkeypatch.setattr(report_data, "_make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def _mail_server(auth_headers, port: int, name="company-mail", **config):
    body = {"name": name, "kind": "smtp", "config": {"host": "127.0.0.1", "port": port, "security": "none",
                                                      "from_address": "reports@example.com", "from_name": "អក្សរខ្មែរ BI", **config}}
    resp = client.post("/api/v1/connections", json=body, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _report(auth_headers) -> str:
    doc = Document()
    doc.add_paragraph("Branch {{ p_branch }}: {{ rows | length }} rows")
    buf = BytesIO()
    doc.save(buf)
    report_id = client.post(
        "/api/v1/reports", files={"file": ("t.docx", buf.getvalue(), "application/octet-stream")}, data={"name": "Daily sales"},
        headers=auth_headers,
    ).json()["report_id"]
    resp = client.put(
        f"/api/v1/reports/{report_id}/data-config",
        json={"parameters": [{"name": "p_branch", "label": "Branch", "options": BRANCHES}],
              "data_source": {"url": "https://erp.example.test/sales?branch={{ p_branch }}", "method": "GET"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return report_id


def _job(auth_headers, config: dict, expect=200):
    resp = client.post(
        "/api/v1/jobs", params={"org_id": ROOT_ORG_ID},
        json={"name": "Daily sales to branches", "job_type": "render_report", "config": config,
              "trigger_type": "cron", "cron_expression": "0 8 * * 1-5"},
        headers=auth_headers,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _run(auth_headers, job) -> str:
    """A queued run (as Run now makes), then the executor itself, as the worker would call it."""
    run_id = client.post(f"/api/v1/jobs/{job['id']}/run", headers=auth_headers).json()["id"]
    return run_id


def _burst_config(report_id, **overrides):
    return {
        "report_id": report_id, "format": "docx", "parameters": {},
        "email": {"connection": "company-mail", "to": ["finance@example.com"], "cc": [],
                  "subject": KHMER_SUBJECT + " · {{ p_branch_label }} · {{ date }}",
                  "body": "Hello,\nThe {{ report }} for {{ p_branch_label }} is attached."},
        "burst": {"by": "p_branch", "values": [
            {"value": "BR01", "to": ["pp@example.com"]},
            {"value": "BR02", "to": ["sr@example.com"], "cc": ["sr.accounts@example.com"]},
            {"value": "BR03", "to": ["bb@example.com"]},
        ]},
        **overrides,
    }


def _deliveries(auth_headers, job_id, run_id):
    resp = client.get(f"/api/v1/jobs/{job_id}/runs/{run_id}/deliveries", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _docx_text(content: bytes) -> str:
    return "\n".join(p.text for p in Document(BytesIO(content)).paragraphs).replace("​", "")


# --- mail server connections ----------------------------------------------------------------------------------------


def test_a_mail_server_is_a_connection_with_checked_settings(auth_headers, smtp):
    created = _mail_server(auth_headers, smtp.port)
    assert created["kind"] == "smtp" and created["config"]["from_name"] == "អក្សរខ្មែរ BI"
    listed = {c["name"]: c for c in client.get("/api/v1/connections", headers=auth_headers).json()}
    assert listed["company-mail"]["base_url"] == f"smtp://127.0.0.1:{smtp.port} · reports@example.com"

    for config, fragment in (
        ({"from_address": "not-an-address"}, "doesn't look like an email address"),
        ({"host": "smtp gmail com"}, "host name"),
        ({"auth": {"type": "basic", "username": "u", "password_env": "X"}}, "needs STARTTLS or TLS"),
    ):
        resp = client.post("/api/v1/connections", json={"name": "bad-mail", "kind": "smtp", "config": {
            "host": "127.0.0.1", "port": 25, "security": "none", "from_address": "a@example.com", **config}}, headers=auth_headers)
        assert resp.status_code == 400 and fragment in resp.json()["detail"], resp.text


def test_a_test_email_goes_through_the_settings_given(auth_headers, smtp):
    resp = client.post("/api/v1/connections/test-mail", headers=auth_headers, json={
        "config": {"host": "127.0.0.1", "port": smtp.port, "security": "none", "from_address": "reports@example.com"},
        "to": "admin@example.com"})
    assert resp.json()["ok"] is True, resp.text
    rcpts, message = smtp.messages[0]
    assert rcpts == ["admin@example.com"] and message["Subject"] == "Aksor Khmer BI: test email"


def test_a_report_source_cant_use_a_mail_server(auth_headers, smtp):
    _mail_server(auth_headers, smtp.port)
    report_id = _report(auth_headers)
    resp = client.put(f"/api/v1/reports/{report_id}/data-config", headers=auth_headers,
                      json={"parameters": [], "data_source": {"connection": "company-mail", "url": "/x"}})
    assert resp.status_code == 400 and "is a mail server" in resp.json()["detail"]


# --- saving a job that emails and splits ------------------------------------------------------------------------------


def test_saving_checks_the_email_and_the_split(auth_headers, smtp):
    _mail_server(auth_headers, smtp.port)
    report_id = _report(auth_headers)
    good = _burst_config(report_id)
    for change, fragment in (
        ({"email": {**good["email"], "connection": "nope"}}, "Choose a mail server"),
        ({"email": {**good["email"], "to": ["finance(at)example.com"]}}, "doesn't look like an email address"),
        ({"email": {**good["email"], "subject": "{{ p_brnch }}"}}, "{{ p_brnch }}, which isn't a filter"),
        ({"burst": {**good["burst"], "by": "nope"}}, "choose one of the report's filters"),
        ({"burst": {**good["burst"], "values": [{"value": "BR09"}]}}, "'BR09' isn't one of Branch's choices"),
        ({"burst": {**good["burst"], "values": []}}, "pick at least one value"),
        ({"parameters": {"p_branch": "BR01"}}, "can't also be a fixed filter value"),
        ({"email": None, "burst": None}, "save it to a folder, email it, or both"),
    ):
        detail = _job(auth_headers, {**good, **change}, expect=400)["detail"]
        assert fragment in detail, (change, detail)
    saved = _job(auth_headers, good)
    assert [v["value"] for v in saved["config"]["burst"]["values"]] == ["BR01", "BR02", "BR03"]
    assert saved["config"]["burst"]["skip_empty"] is True


def test_a_split_value_outside_the_savers_access_is_refused():
    definitions = [{"name": "p_branch", "label": "Branch", "options": BRANCHES}]
    config = {"destination_path": "/tmp/x.docx", "burst": {"by": "p_branch", "values": [{"value": "BR01"}, {"value": "BR02"}]}}
    with pytest.raises(report_data.ParameterError) as caught:
        job_delivery.validate(config, definitions, {"p_branch": {"BR01"}}, ROOT_ORG_ID)
    assert caught.value.status == 403
    assert job_delivery.validate(config, definitions, {"p_branch": {"BR01", "BR02"}}, ROOT_ORG_ID)["burst"]["by"] == "p_branch"


# --- running it -------------------------------------------------------------------------------------------------------


def test_a_split_run_mails_each_branch_its_own_report(auth_headers, smtp, erp):
    _mail_server(auth_headers, smtp.port)
    job = _job(auth_headers, _burst_config(_report(auth_headers)))
    run_id = _run(auth_headers, job)

    summary = job_delivery.run(job["config"], job["id"], run_id)
    assert summary == "2 sent, 1 skipped"

    assert len(smtp.messages) == 2
    by_branch = {}
    for rcpts, message in smtp.messages:
        attachment = next(message.iter_attachments())
        by_branch[_docx_text(attachment.get_content())] = (rcpts, message, attachment.get_filename())
    pp_rcpts, pp, pp_file = by_branch["Branch BR01: 2 rows"]
    sr_rcpts, sr, sr_file = by_branch["Branch BR02: 2 rows"]
    # Everyone above the list gets each file; each branch's own people get only theirs.
    assert pp_rcpts == ["finance@example.com", "pp@example.com"]
    assert sr_rcpts == ["finance@example.com", "sr@example.com", "sr.accounts@example.com"]
    assert sr["Cc"] == "sr.accounts@example.com"
    # Khmer survives the trip: subject, sender name, file name.
    assert sr["Subject"].startswith(f"{KHMER_SUBJECT} · សៀមរាប · ")
    assert "អក្សរខ្មែរ BI" in str(sr["From"])
    assert sr_file.startswith("Daily-sales-សៀមរាប-") and sr_file.endswith(".docx")
    assert "The Daily sales for សៀមរាប is attached." in sr.get_body().get_content()

    lines = {d["burst_value"]: d for d in _deliveries(auth_headers, job["id"], run_id)}
    assert {v: d["status"] for v, d in lines.items()} == {"BR01": "sent", "BR02": "sent", "BR03": "skipped"}
    assert lines["BR03"]["reason"] == "No data for this value, so nothing was sent"
    assert lines["BR02"]["burst_label"] == "សៀមរាប" and lines["BR02"]["size_bytes"] > 0


def test_a_refused_email_fails_alone_and_is_resent_with_the_same_file(auth_headers, smtp, erp):
    _mail_server(auth_headers, smtp.port)
    job = _job(auth_headers, _burst_config(_report(auth_headers), email={
        "connection": "company-mail", "to": [], "cc": [], "subject": "{{ report }}", "body": ""}))
    run_id = _run(auth_headers, job)
    smtp.refuse = {"sr@example.com", "sr.accounts@example.com"}

    assert job_delivery.run(job["config"], job["id"], run_id) == "1 sent, 1 failed, 1 skipped"
    lines = {d["burst_value"]: d for d in _deliveries(auth_headers, job["id"], run_id)}
    assert lines["BR02"]["status"] == "failed" and "refused" in lines["BR02"]["reason"] and lines["BR02"]["can_resend"]
    first_file = next(m for r, m in smtp.messages if r == ["pp@example.com"])

    smtp.refuse = set()
    assert client.post(f"/api/v1/jobs/{job['id']}/runs/{run_id}/resend", headers=auth_headers).json() == {"queued": 1}
    assert job_delivery.resend(run_id) == "re-sent 1"
    lines = {d["burst_value"]: d for d in _deliveries(auth_headers, job["id"], run_id)}
    assert lines["BR02"]["status"] == "sent" and lines["BR02"]["attempts"] == 2
    assert len(smtp.messages) == 2 and first_file is not None  # BR01 wasn't sent twice
    nothing = client.post(f"/api/v1/jobs/{job['id']}/runs/{run_id}/resend", headers=auth_headers)
    assert nothing.status_code == 400


def test_a_mail_server_thats_down_makes_the_run_retry_and_a_retry_starts_clean(auth_headers, smtp, erp):
    _mail_server(auth_headers, smtp.port)
    job = _job(auth_headers, _burst_config(_report(auth_headers)))
    run_id = _run(auth_headers, job)
    smtp.close()  # nothing listening any more

    with pytest.raises(job_delivery.RetryableJobError):
        job_delivery.run(job["config"], job["id"], run_id)
    assert [d["status"] for d in _deliveries(auth_headers, job["id"], run_id)].count("failed") == 2

    with db.SessionLocal() as session:  # a retry of the same run replaces, not adds to, its history
        server = FakeSmtp()
        row = session.query(db.DataConnection).filter_by(name="company-mail").one()
        row.config = {**row.config, "port": server.port}
        session.commit()
    try:
        assert job_delivery.run(job["config"], job["id"], run_id) == "2 sent, 1 skipped"
        assert len(_deliveries(auth_headers, job["id"], run_id)) == 3
    finally:
        server.close()


def test_a_try_later_answer_is_retryable_and_a_saved_copy_counts_as_delivered(auth_headers, smtp, erp, tmp_path):
    _mail_server(auth_headers, smtp.port)
    report_id = _report(auth_headers)
    smtp.data_reply = "452 try again later"
    job = _job(auth_headers, _burst_config(report_id))
    with pytest.raises(job_delivery.RetryableJobError):
        job_delivery.run(job["config"], job["id"], _run(auth_headers, job))

    # With a copy saved to a folder, something went out: the run finishes (a retry would save it twice) and the
    # failed emails wait to be re-sent from the history.
    folder = tmp_path / "out" / "sales-{value}-{timestamp}.docx"
    job = _job(auth_headers, _burst_config(report_id, destination_path=str(folder)))
    run_id = _run(auth_headers, job)
    assert job_delivery.run(job["config"], job["id"], run_id) == "2 failed, 1 skipped"
    assert sorted(p.name.split("-")[1] for p in (tmp_path / "out").iterdir()) == ["BR01", "BR02"]
    lines = [d for d in _deliveries(auth_headers, job["id"], run_id) if d["status"] == "failed"]
    assert all(d["saved_to"] and d["can_resend"] and "try again later" in d["reason"] for d in lines)


def test_without_a_split_one_file_is_saved_and_mailed(auth_headers, smtp, erp, tmp_path):
    _mail_server(auth_headers, smtp.port)
    report_id = _report(auth_headers)
    job = _job(auth_headers, {
        "report_id": report_id, "format": "docx", "parameters": {"p_branch": "BR02"},
        "destination_path": str(tmp_path / "sales-{timestamp}.docx"),
        "email": {"connection": "company-mail", "to": ["finance@example.com"], "subject": "Sales\r\nBcc: evil@example.com", "body": ""},
    })
    run_id = _run(auth_headers, job)
    assert job_delivery.run(job["config"], job["id"], run_id) == "1 sent"
    (rcpts, message), = smtp.messages
    assert rcpts == ["finance@example.com"]  # a line break in the subject can't add a recipient
    assert message["Bcc"] is None and message["Subject"] == "Sales Bcc: evil@example.com"
    saved = list(tmp_path.glob("sales-*.docx"))
    assert len(saved) == 1 and _docx_text(saved[0].read_bytes()) == "Branch BR02: 2 rows"
    (line,) = _deliveries(auth_headers, job["id"], run_id)
    assert line["status"] == "sent" and line["saved_to"] == str(saved[0])


def test_deleting_a_job_removes_its_history(auth_headers, smtp, erp):
    _mail_server(auth_headers, smtp.port)
    job = _job(auth_headers, _burst_config(_report(auth_headers)))
    job_delivery.run(job["config"], job["id"], _run(auth_headers, job))
    assert client.delete(f"/api/v1/jobs/{job['id']}", headers=auth_headers).status_code == 204
    with db.SessionLocal() as session:
        assert session.query(db.JobDelivery).filter_by(job_id=job["id"]).count() == 0
        assert session.query(db.JobRun).filter_by(job_id=job["id"]).count() == 0


def test_a_too_large_attachment_is_a_clear_failure(monkeypatch):
    monkeypatch.setenv("MAIL_MAX_ATTACHMENT_MB", "1")
    with mailer.Session({"host": "127.0.0.1", "port": 1, "security": "none", "from_address": "a@example.com"}) as session:
        with pytest.raises(mailer.MailError, match="larger than 1 MB") as caught:
            session.send(mailer.Message(to=["b@example.com"], cc=[], subject="x", body="",
                                        attachment=mailer.Attachment("big.pdf", b"x" * (1024 * 1024 + 1))))
    assert caught.value.retryable is False


def test_nothing_listening_is_retryable():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with mailer.Session({"host": "127.0.0.1", "port": port, "security": "none", "from_address": "a@example.com"}) as session:
        with pytest.raises(mailer.MailError, match="Couldn't reach the mail server") as caught:
            session.send(mailer.Message(to=["b@example.com"], cc=[], subject="x", body=""))
    assert caught.value.retryable is True
