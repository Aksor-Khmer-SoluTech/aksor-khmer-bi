"""The order of a report's filter parameters is part of its configuration: the order a manager saves them in is the order
the person running the report sees them in (the portal's run page, the Preview tab's live run), and reordering is a
save like any other."""
from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.main import app

http = TestClient(app)


def _param(name, label=None):
    return {"name": name, "label": label or name.title(), "type": "text", "required": False}


@pytest.fixture
def report_id(auth_headers) -> str:
    doc = Document()
    doc.add_paragraph("x")
    buf = BytesIO()
    doc.save(buf)
    resp = http.post(
        "/api/v1/reports",
        files={"file": ("t.docx", buf.getvalue(), "application/octet-stream")},
        data={"name": "Ordered"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


def _save(headers, rid, names):
    resp = http.put(f"/api/v1/reports/{rid}/data-config", json={"parameters": [_param(n) for n in names], "data_source": None}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _names(payload) -> list[str]:
    return [p["name"] for p in payload["parameters"]]


def test_the_saved_order_is_what_the_run_form_shows(auth_headers, report_id):
    saved = _save(auth_headers, report_id, ["to_date", "branch", "from_date", "signed_by"])
    assert _names(saved) == ["to_date", "branch", "from_date", "signed_by"]
    assert _names(http.get(f"/api/v1/reports/{report_id}/data-config", headers=auth_headers).json()) == ["to_date", "branch", "from_date", "signed_by"]
    assert _names(http.get(f"/api/v1/reports/{report_id}/run-form", headers=auth_headers).json()) == ["to_date", "branch", "from_date", "signed_by"]


def test_reordering_is_just_saving_the_same_parameters_in_another_order(auth_headers, report_id):
    _save(auth_headers, report_id, ["a", "b", "c"])
    _save(auth_headers, report_id, ["c", "a", "b"])
    assert _names(http.get(f"/api/v1/reports/{report_id}/run-form", headers=auth_headers).json()) == ["c", "a", "b"]
    _save(auth_headers, report_id, ["b", "c", "a"])
    assert _names(http.get(f"/api/v1/reports/{report_id}/data-config", headers=auth_headers).json()) == ["b", "c", "a"]
