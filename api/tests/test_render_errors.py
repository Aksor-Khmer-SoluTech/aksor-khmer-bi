"""A report that fails to render says why -- to whoever manages it. Everyone else gets a plain
message and a reference that matches the server log."""
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from app.main import app

http = TestClient(app, raise_server_exceptions=False)


def _docx(*paragraphs: str) -> bytes:
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _register(headers, *paragraphs, name="Broken") -> str:
    resp = http.post(
        "/api/v1/reports", files={"file": ("t.docx", _docx(*paragraphs), "application/octet-stream")}, data={"name": name}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report_id"]


UNCLOSED = ("{% for r in rows %}", "{{ r }}", "{% endfor %}", "{% endfor %}")


def _run(headers, report_id):
    return http.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {}, "format": "docx"}, headers=headers)


def test_a_manager_sees_the_engines_own_error(auth_headers):
    report_id = _register(auth_headers, *UNCLOSED)
    resp = _run(auth_headers, report_id)
    assert resp.status_code == 422
    body = resp.json()
    assert "unknown tag 'endfor'" in body["detail"]
    info = body["render_error"]
    assert info["stage"] == "template" and info["type"] == "TemplateSyntaxError"
    assert "unknown tag 'endfor'" in info["message"]
    assert info["tag_counts"] == {"for": 1, "endfor": 2, "if": 0, "endif": 0}
    assert "1 `for` and 2 `endfor`" in info["hint"]
    assert any(line["hit"] for line in info["context"])
    assert "TemplateSyntaxError" in info["traceback"] and "<repo>" in info["traceback"]  # paths are shortened


def test_a_missing_field_gets_a_hint(auth_headers):
    report_id = _register(auth_headers, "{{ rows[0].name }}")
    info = _run(auth_headers, report_id).json()["render_error"]
    assert info["stage"] == "template" and "doesn't have" in info["hint"]


def test_others_get_a_plain_message_and_a_reference(auth_headers, make_local_user):
    report_id = _register(auth_headers, *UNCLOSED)
    _, runner = make_local_user("runner", "pw-runner-1", ("ROLE_REPORT_VIEWER",))
    resp = _run(runner, report_id)
    assert resp.status_code in (422, 403), resp.text
    if resp.status_code == 422:
        body = resp.json()
        assert "endfor" not in resp.text and "traceback" not in body["render_error"]
        assert body["render_error"]["reference"] in body["detail"]


def test_a_public_render_is_generic_unless_the_caller_manages_the_report(auth_headers):
    report_id = _register(auth_headers, *UNCLOSED)
    anonymous = http.post(f"/api/v1/reports/{report_id}/render?format=docx", json={"rows": [1]})
    assert anonymous.status_code == 422
    assert "endfor" not in anonymous.text and "traceback" not in anonymous.json()["render_error"]

    manager = http.post(f"/api/v1/reports/{report_id}/render?format=docx", json={"rows": [1]}, headers=auth_headers)
    assert manager.status_code == 422 and "unknown tag 'endfor'" in manager.json()["detail"]

    wrong = http.post(
        f"/api/v1/reports/{report_id}/render?format=docx", json={"rows": [1]}, headers={"Authorization": "Basic Zm9vOmJhcg=="}
    )
    assert wrong.status_code == 422 and "endfor" not in wrong.text


def test_a_good_template_is_unaffected(auth_headers):
    report_id = _register(auth_headers, "{% for r in rows %}", "{{ r }}", "{% endfor %}")
    ok = http.post(f"/api/v1/reports/{report_id}/render?format=docx", json={"rows": ["a", "b"]})
    assert ok.status_code == 200


def test_both_block_tags_in_one_paragraph_is_diagnosed_even_when_the_counts_balance(auth_headers):
    report_id = _register(auth_headers, "{%p for r in rows %} {{ r.card_number }} {%p endfor %}")
    info = _run(auth_headers, report_id).json()["render_error"]
    assert info["tag_counts"] == {"for": 1, "endfor": 1, "if": 0, "endif": 0}
    assert info["shared_tags"] == [
        {"where": "the body", "paragraph": 1, "text": "{%p for r in rows %} {{ r.card_number }} {%p endfor %}"}
    ]
    assert "alone in its own paragraph" in info["hint"]


def test_block_tags_each_alone_are_not_flagged(auth_headers):
    report_id = _register(auth_headers, "{%p for r in rows %}", "{{ r }}", "{%p endfor %}", "{% endfor %}")
    info = _run(auth_headers, report_id).json()["render_error"]
    assert info["shared_tags"] is None


def test_a_converter_failure_is_shown_to_managers_and_hidden_from_others(auth_headers, monkeypatch):
    from app.routers import reports as reports_router
    from doc_engine.engines.libreoffice_engine import ConversionError

    def boom(*args, **kwargs):
        raise ConversionError("soffice failed converting to pdf: Error: source file could not be loaded\n2026 Task policy set failed")

    monkeypatch.setattr(reports_router, "doc_render", boom)
    report_id = _register(auth_headers, "{{ x }}")
    manager = http.post(f"/api/v1/reports/{report_id}/render?format=pdf", json={"x": 1}, headers=auth_headers)
    assert manager.status_code == 500
    info = manager.json()["render_error"]
    assert info["stage"] == "render" and info["type"] == "ConversionError" and "re-saving the template" in info["hint"]

    anonymous = http.post(f"/api/v1/reports/{report_id}/render?format=pdf", json={"x": 1})
    assert anonymous.status_code == 500 and "soffice" not in anonymous.text
