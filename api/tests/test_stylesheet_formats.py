"""Stylesheets in CSS, SCSS, Sass and Less (app/style_compile.py, stylesheet_store, routers/stylesheets.py): compiled
on upload, the source kept and served, errors that say where, imports refused (they would read the server's disk),
an html template using one, a replacement in another format, and a project carrying the source to another server."""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import db, projects, stylesheet_store
from app.main import app
from app.rbac import ROOT_ORG_ID

client = TestClient(app)

SCSS = b"$brand: #06519e;\n.receipt {\n  h1 { color: $brand; }\n  &:hover { color: darken($brand, 10%); }\n}\n"
SASS = b"$brand: #06519e\n.receipt\n  h1\n    color: $brand\n"
LESS = b"@brand: #06519e;\n.pad(@n) { padding: @n; }\n.receipt { h1 { color: @brand; .pad(4px); } }\n"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(stylesheet_store, "STORE_DIR", tmp_path / "styles")
    monkeypatch.setattr(projects, "IMPORT_DIR", tmp_path / "imports")


def upload(headers, filename, content, name="theme", expect=200, **data):
    resp = client.post("/api/v1/stylesheets", files={"file": (filename, content, "text/plain")},
                       data={"name": name, "org_id": ROOT_ORG_ID, **data}, headers=headers)
    assert resp.status_code == expect, resp.text
    return resp.json()


@pytest.mark.parametrize("filename, content, fmt", [("theme.scss", SCSS, "scss"), ("theme.sass", SASS, "sass"), ("theme.less", LESS, "less")])
def test_each_format_compiles_and_keeps_its_source(auth_headers, filename, content, fmt):
    sheet = upload(auth_headers, filename, content)
    assert sheet["source_format"] == fmt
    css = client.get(f"/api/v1/stylesheets/{sheet['id']}/file", headers=auth_headers).text
    assert ".receipt h1" in css and "#06519e" in css and "$brand" not in css and "@brand" not in css
    source = client.get(f"/api/v1/stylesheets/{sheet['id']}/source", headers=auth_headers)
    assert source.content == content and f"theme.{fmt}" in source.headers["content-disposition"]


def test_plain_css_is_as_it_was(auth_headers):
    sheet = upload(auth_headers, "theme.css", b"h1 { color: red; }")
    assert sheet["source_format"] == "css"
    assert client.get(f"/api/v1/stylesheets/{sheet['id']}/source", headers=auth_headers).content == b"h1 { color: red; }"


def test_the_format_can_be_said_rather_than_guessed(auth_headers):
    assert upload(auth_headers, "theme.txt", SCSS, source_format="scss")["source_format"] == "scss"


@pytest.mark.parametrize("filename, content, fragment", [
    ("a.scss", b".a { color: $nope; }", 'Undefined variable: "$nope". (line 1, column 13)'),
    ("a.sass", b".a\n  color: $nope\n", "(line 2,"),
    ("a.less", b".a { color: @nope; }", "Unknown variable @nope"),
    ("a.scss", b"$only: 1px;", "compiles to no CSS"),
    ("a.styl", b"a\n  color red", "Stylus isn't supported"),
])
def test_an_error_says_what_and_where(auth_headers, filename, content, fragment):
    assert fragment in upload(auth_headers, filename, content, expect=400)["detail"]


@pytest.mark.parametrize("filename, content", [
    ("a.scss", b'@import "/etc/hosts";\n.a { color: red; }'),
    ("a.scss", b"@use 'sass:math';\n.a { width: math.div(10px, 2); }"),
    ("a.sass", b'@import "/etc/hosts"\n.a\n  color: red'),
    ("a.less", b'@import "/etc/hosts";\n.a { color: red; }'),
])
def test_imports_are_refused_they_would_read_the_servers_disk(auth_headers, filename, content):
    detail = upload(auth_headers, filename, content, expect=400)["detail"]
    assert "isn't allowed" in detail and "localhost" not in detail


def test_replacing_in_another_format(auth_headers):
    sheet = upload(auth_headers, "theme.css", b"h1 { color: red; }")
    resp = client.put(f"/api/v1/stylesheets/{sheet['id']}/file", files={"file": ("theme.less", LESS, "text/plain")}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["source_format"] == "less" and resp.json()["id"] == sheet["id"]
    assert "padding: 4px" in client.get(f"/api/v1/stylesheets/{sheet['id']}/file", headers=auth_headers).text
    bad = client.put(f"/api/v1/stylesheets/{sheet['id']}/file", files={"file": ("x.scss", b".a { color: $x; }", "text/plain")}, headers=auth_headers)
    assert bad.status_code == 400 and client.get(f"/api/v1/stylesheets/{sheet['id']}", headers=auth_headers).json()["source_format"] == "less"
    with db.SessionLocal() as session:
        assert session.query(db.AuditEvent).filter(db.AuditEvent.action == "stylesheet.replace").one().summary == 'Replaced stylesheet "theme" (Less)'


def test_an_html_template_uses_the_compiled_css(auth_headers):
    sheet = upload(auth_headers, "theme.scss", SCSS)
    html = b'<link rel="stylesheet" href="{{ resource(\'theme\') }}"><div class="receipt"><h1>{{ title }}</h1></div>'
    report = client.post("/api/v1/reports", files={"file": ("r.html", html, "text/html")}, headers=auth_headers,
                         data={"name": "Styled", "resource_bindings": json.dumps({"theme": {"kind": "stylesheet", "id": sheet["id"]}})}).json()
    pdf = client.post(f"/api/v1/reports/{report['report_id']}/render?format=pdf", json={"title": "វិក្កយបត្រ"}, headers=auth_headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_the_same_scss_uploaded_twice_is_noticed(auth_headers):
    first = upload(auth_headers, "theme.scss", SCSS)
    assert [d["id"] for d in upload(auth_headers, "copy.scss", SCSS, name="copy")["duplicates"]] == [first["id"]]


def test_a_project_carries_the_source(auth_headers):
    client.post("/api/v1/organizations", json={"id": "acme", "name": "Acme"}, headers=auth_headers)
    root = client.post("/api/v1/folders", json={"org_id": ROOT_ORG_ID, "name": "Styled"}, headers=auth_headers).json()
    client.patch(f"/api/v1/folders/{root['id']}", json={"is_project": True}, headers=auth_headers)
    upload(auth_headers, "theme.scss", SCSS, folder_id=root["id"])
    package = client.post(f"/api/v1/projects/{root['id']}/export", json={}, headers=auth_headers).content
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(package)).read("manifest.json"))
    (res,) = manifest["resources"]
    assert res["ext"] == "scss" and zipfile.ZipFile(io.BytesIO(package)).read(res["file"]) == SCSS
    plan = client.post("/api/v1/projects/import/preview", files={"file": ("p.zip", package, "application/zip")},
                       data={"org_id": "acme"}, headers=auth_headers).json()
    client.post(f"/api/v1/projects/import/{plan['token']}", json={"decisions": {}}, headers=auth_headers).raise_for_status()
    with db.SessionLocal() as session:
        imported = session.query(db.StylesheetResource).filter(db.StylesheetResource.org_id == "acme").one()
    assert imported.source_format == "scss"
    assert stylesheet_store.get_stylesheet_source(imported.id) == (SCSS, "scss")
    assert b".receipt h1" in stylesheet_store.get_stylesheet_bytes(imported.id)
