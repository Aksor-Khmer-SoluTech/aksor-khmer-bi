"""The `/api/v1/examples/revenue-comparison` sample data source: the whole render
context for the Revenue Comparison layout, with the period labels, printed date and
signature following the query.

Also pins the other half of what makes that layout runnable: a report registered
*without* a data config has no filters on the Run page and renders against an empty
context, which is why a report with a data source needs one.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


PERIODS = {
    "period1FromDate": "2026-08-01",
    "period1ToDate": "2026-08-31",
    "period2FromDate": "2026-09-01",
    "period2ToDate": "2026-09-30",
}


# --- the endpoint --------------------------------------------------------


def test_revenue_comparison_returns_the_full_template_context():
    resp = client.get("/api/v1/examples/revenue-comparison", params={**PERIODS, "signed_by": "Sok Sophea"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert {"issuer", "addressLine", "period1", "period2", "total", "groups", "preparedDate", "signatureName"} <= set(body)
    assert body["period1"] == {"label": "01/08/2026", "sublabel": "31/08/2026"}
    assert body["period2"] == {"label": "01/09/2026", "sublabel": "30/09/2026"}
    assert body["signatureName"] == "Sok Sophea"

    groups = body["groups"]
    assert body["total"]["amount1"] == sum(g["amount1"] for g in groups)
    assert body["total"]["diffAmount"] == body["total"]["amount2"] - body["total"]["amount1"]
    assert all(g["children"] for g in groups)


def test_signed_by_is_optional():
    resp = client.get("/api/v1/examples/revenue-comparison", params=PERIODS)
    assert resp.status_code == 200
    assert resp.json()["signatureName"] == ""


@pytest.mark.parametrize("period", ["period1", "period2"])
def test_a_period_that_ends_before_it_starts_is_rejected(period):
    params = {**PERIODS, f"{period}FromDate": "2026-09-30", f"{period}ToDate": "2026-09-01"}
    resp = client.get("/api/v1/examples/revenue-comparison", params=params)
    assert resp.status_code == 400
    assert "ends before it starts" in resp.json()["detail"]


# --- a report with no data config ---------------------------------------


@pytest.fixture
def revenue_report(auth_headers) -> str:
    from io import BytesIO

    from docx import Document

    template = Document()  # the shipped sample template was removed; any docx with a placeholder will do
    template.add_paragraph("Revenue {{ current_period_label }}")
    buf = BytesIO()
    template.save(buf)
    resp = client.post(
        "/api/v1/reports",
        files={"file": ("revenue-comparison.docx", buf.getvalue(), "application/octet-stream")},
        data={"name": "Revenue Comparison"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


def test_without_a_data_config_the_report_has_no_filters(auth_headers, revenue_report):
    """Without a data config there is nothing for the Run page to show: no filters, and the
    template would render against an empty context."""
    form = client.get(f"/api/v1/reports/{revenue_report}/run-form", headers=auth_headers).json()
    assert form["parameters"] == []
