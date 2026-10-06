"""Batch render's size limit is per output format, not one number: pdf/png cost
~2 s a record (each is a LibreOffice conversion) while docx/xlsx cost ~10 ms,
so 200 was ~6.5 minutes for the former and a needless 2 seconds for the latter.
See app/batch_limits.py."""
import pytest
from docx import Document
from fastapi.testclient import TestClient
from io import BytesIO

from app import batch_limits
from app.main import app

client = TestClient(app)


def _register(auth_headers) -> str:
    doc = Document()
    doc.add_paragraph("Hello {{ customer_name }}")
    buf = BytesIO()
    doc.save(buf)
    resp = client.post(
        "/api/v1/reports",
        files={"file": ("t.docx", buf.getvalue(), "application/octet-stream")},
        data={"name": "Batchable"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MAX_BATCH_PDF_PNG", raising=False)
    monkeypatch.delenv("MAX_BATCH_DOCX_XLSX", raising=False)


def test_defaults_are_sized_by_cost_not_one_number():
    assert batch_limits.max_batch_size("pdf") == batch_limits.max_batch_size("png") == 30
    assert batch_limits.max_batch_size("docx") == batch_limits.max_batch_size("xlsx") == 1000
    # ~a minute of LibreOffice work at the measured ~2 s a record
    assert batch_limits.max_batch_size("pdf") * batch_limits.SECONDS_PER_RECORD["pdf"] <= 60


def test_settings_override_and_are_clamped(monkeypatch):
    monkeypatch.setenv("MAX_BATCH_PDF_PNG", "12")
    monkeypatch.setenv("MAX_BATCH_DOCX_XLSX", "50")
    assert (batch_limits.max_batch_size("pdf"), batch_limits.max_batch_size("docx")) == (12, 50)
    monkeypatch.setenv("MAX_BATCH_PDF_PNG", "100000")
    monkeypatch.setenv("MAX_BATCH_DOCX_XLSX", "100000")
    assert batch_limits.max_batch_size("png") == batch_limits.SLOW_CEILING
    assert batch_limits.max_batch_size("xlsx") == batch_limits.FAST_CEILING
    monkeypatch.setenv("MAX_BATCH_PDF_PNG", "many")
    assert batch_limits.max_batch_size("pdf") == 30  # garbage falls back rather than breaking every batch


def test_the_message_says_why_and_what_to_do():
    pdf = batch_limits.over_limit_message(200, "pdf")
    assert "200" in pdf and "30 pdf" in pdf and "2 s" in pdf and "several requests" in pdf
    assert "docx and xlsx batches are far cheaper" in pdf
    docx = batch_limits.over_limit_message(5000, "docx")
    assert "1,000 docx" in docx and "far cheaper" not in docx


def test_limits_endpoint_describes_every_format_and_is_not_mistaken_for_a_report_id():
    resp = client.get("/api/v1/reports/batch-limits")
    assert resp.status_code == 200, resp.text  # 404 here would mean /{report_id} swallowed it
    body = resp.json()
    assert set(body["max_records"]) == set(body["seconds_per_record"]) == {"pdf", "png", "docx", "xlsx"}
    assert body["max_records"]["pdf"] == 30 and body["max_records"]["docx"] == 1000
    assert body["seconds_per_record"]["pdf"] >= 50 * body["seconds_per_record"]["docx"]


def test_the_endpoint_reflects_the_settings(monkeypatch):
    monkeypatch.setenv("MAX_BATCH_PDF_PNG", "5")
    assert client.get("/api/v1/reports/batch-limits").json()["max_records"]["png"] == 5


def test_pdf_batch_over_its_own_limit_is_refused_before_anything_renders(auth_headers, monkeypatch):
    """The point of the small PDF cap: it must fail up front, never after a
    minute of LibreOffice work -- so no render is attempted at all."""
    from app.routers import reports as reports_router

    monkeypatch.setenv("MAX_BATCH_PDF_PNG", "2")
    rendered = []
    monkeypatch.setattr(reports_router, "_render_one", lambda *a, **k: rendered.append(1) or b"")
    report_id = _register(auth_headers)
    resp = client.post(f"/api/v1/reports/{report_id}/render/batch?format=pdf", json=[{}, {}, {}])
    assert resp.status_code == 400
    assert "2 pdf documents" in resp.json()["detail"]
    assert rendered == []


def test_the_same_number_of_docx_records_is_fine(auth_headers, monkeypatch):
    """...while docx isn't held to the PDF limit: 3 records is over the PDF cap of 2 but nowhere near docx's."""
    monkeypatch.setenv("MAX_BATCH_PDF_PNG", "2")
    report_id = _register(auth_headers)
    resp = client.post(f"/api/v1/reports/{report_id}/render/batch?format=docx", json=[{"customer_name": "a"}] * 3)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"


def test_docx_batch_over_its_own_limit_is_refused(auth_headers, monkeypatch):
    monkeypatch.setenv("MAX_BATCH_DOCX_XLSX", "2")
    report_id = _register(auth_headers)
    resp = client.post(f"/api/v1/reports/{report_id}/render/batch?format=docx", json=[{}, {}, {}])
    assert resp.status_code == 400
    assert "2 docx documents" in resp.json()["detail"]
