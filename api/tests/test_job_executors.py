"""Exercises app/job_executors.py for real: a real local HTTP server for
rest_call (not mocked), real report_store/doc_engine rendering for
render_report/file_output, real filesystem writes. See test_soap_call.py
for the soap_call executor (its own file since the WSDL test fixture is
sizeable enough to warrant separating).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

import pytest
from docx import Document

from app import report_store
from app.job_executors import (
    PermanentJobError,
    RetryableJobError,
    execute_file_output,
    execute_render_report,
    execute_rest_call,
)


def _make_docx_report(name="Executor Test") -> str:
    doc = Document()
    doc.add_paragraph("Hello {{ customer_name }}")
    buf = BytesIO()
    doc.save(buf)
    meta = report_store.create_report(name=name, content=buf.getvalue(), template_ext="docx")
    return meta["report_id"]


# --- render_report / file_output ------------------------------------


def test_execute_render_report_writes_a_real_pdf(tmp_path):
    report_id = _make_docx_report()
    destination = tmp_path / "{job_id}" / "out-{timestamp}.pdf"
    summary = execute_render_report(
        {"report_id": report_id, "format": "pdf", "context": {"customer_name": "Sotheara"}, "destination_path": str(destination)},
        job_id="job123",
    )
    written = list((tmp_path / "job123").glob("out-*.pdf"))
    assert len(written) == 1
    assert written[0].read_bytes().startswith(b"%PDF")
    assert "wrote" in summary


def test_execute_render_report_unknown_report_is_permanent_error(tmp_path):
    with pytest.raises(PermanentJobError):
        execute_render_report(
            {"report_id": "does-not-exist", "format": "pdf", "context": {}, "destination_path": str(tmp_path / "x.pdf")},
            job_id="job1",
        )


def test_execute_file_output_static_content(tmp_path):
    destination = tmp_path / "flag-{job_id}.txt"
    summary = execute_file_output(
        {"destination_path": str(destination), "source": "static", "content": "done"}, job_id="job456"
    )
    written = tmp_path / "flag-job456.txt"
    assert written.read_text() == "done"
    assert "wrote" in summary


def test_execute_file_output_render_report_source(tmp_path):
    report_id = _make_docx_report()
    destination = tmp_path / "report.docx"
    execute_file_output(
        {
            "destination_path": str(destination),
            "source": "render_report",
            "report_id": report_id,
            "format": "docx",
            "context": {"customer_name": "Bob"},
        },
        job_id="job789",
    )
    assert destination.read_bytes()[:2] == b"PK"


def test_execute_file_output_permission_error_is_permanent(tmp_path, monkeypatch):
    from app import job_executors

    def _raise_permission(self, content):  # noqa: ARG001
        raise PermissionError("nope")

    monkeypatch.setattr(job_executors.Path, "write_bytes", _raise_permission)
    with pytest.raises(PermanentJobError):
        execute_file_output(
            {"destination_path": str(tmp_path / "x.txt"), "source": "static", "content": "x"}, job_id="job1"
        )


# --- rest_call, against a real local HTTP server -------------------------


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: ARG002 -- silence default stderr logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        self.server.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})

        if self.path == "/ok":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        elif self.path == "/server-error":
            self.send_response(503)
            self.end_headers()
        elif self.path == "/bad-request":
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"bad request")
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()


def _base_url(server) -> str:
    return f"http://127.0.0.1:{server.server_port}"


def test_execute_rest_call_success(http_server):
    summary = execute_rest_call(
        {"url": f"{_base_url(http_server)}/ok", "method": "POST", "body_template": {"name": "{{ name }}"}, "context": {"name": "Sotheara"}},
        job_id="job1",
    )
    assert "200" in summary
    assert len(http_server.requests) == 1
    assert json.loads(http_server.requests[0]["body"]) == {"name": "Sotheara"}


def test_execute_rest_call_templates_the_body(http_server):
    execute_rest_call(
        {
            "url": f"{_base_url(http_server)}/ok",
            "method": "POST",
            "body_template": {"greeting": "Hello {{ name }}!"},
            "context": {"name": "Bob"},
        },
        job_id="job1",
    )
    assert json.loads(http_server.requests[-1]["body"]) == {"greeting": "Hello Bob!"}


def test_execute_rest_call_5xx_is_retryable(http_server):
    with pytest.raises(RetryableJobError):
        execute_rest_call({"url": f"{_base_url(http_server)}/server-error", "method": "POST"}, job_id="job1")


def test_execute_rest_call_4xx_is_permanent(http_server):
    with pytest.raises(PermanentJobError):
        execute_rest_call({"url": f"{_base_url(http_server)}/bad-request", "method": "POST"}, job_id="job1")


def test_execute_rest_call_connection_error_is_retryable():
    with pytest.raises(RetryableJobError):
        # Port 1 is reserved and nothing will ever answer on it locally.
        execute_rest_call({"url": "http://127.0.0.1:1/unreachable", "method": "POST"}, job_id="job1")


def test_execute_rest_call_bearer_auth_header(http_server, monkeypatch):
    monkeypatch.setenv("TEST_BEARER_TOKEN", "s3cr3t")
    execute_rest_call(
        {
            "url": f"{_base_url(http_server)}/ok",
            "method": "POST",
            "auth": {"type": "bearer", "token_env": "TEST_BEARER_TOKEN"},
        },
        job_id="job1",
    )
    assert http_server.requests[-1]["headers"]["Authorization"] == "Bearer s3cr3t"


def test_execute_rest_call_basic_auth(http_server, monkeypatch):
    import base64

    monkeypatch.setenv("TEST_BASIC_PASSWORD", "hunter2")
    execute_rest_call(
        {
            "url": f"{_base_url(http_server)}/ok",
            "method": "POST",
            "auth": {"type": "basic", "username": "svc", "password_env": "TEST_BASIC_PASSWORD"},
        },
        job_id="job1",
    )
    sent = http_server.requests[-1]["headers"]["Authorization"]
    assert sent == "Basic " + base64.b64encode(b"svc:hunter2").decode()
