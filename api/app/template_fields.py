"""Best-effort detection of the Jinja2 placeholder names a template file
expects -- shared by GET /reports/{id}/schema (what the portal's
Parameters tab shows) and by report_store's per-version snapshots (what the
changelog compares to say "this version added {{ branch }}").

Not a guaranteed-complete schema, a cheap honest scan (same spirit as
report_store.is_valid_office_file's "cheap sanity check"):

- docx: docxtpl's `get_undeclared_template_variables()`, which walks the
  compiled Jinja2 AST -- reliable for top-level names, but a loop
  variable (`{%tr for item in items %}` ... `{{ item.label }}`) surfaces
  as `item`/`items`, not the nested `item.label` path.
- xlsx: xltpl has no equivalent introspection API, so a plain regex scan
  of the workbook's XML for `{{ name` patterns and `{% for x in coll %}`
  loop markers -- cruder, good enough to seed a starter payload.
- html: the same Jinja2 AST walk POST /reports/parse-template runs at
  register time (html_template.py), re-run fresh off the stored file.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from docxtpl import DocxTemplate

from .html_template import parse_html_template

# {{ name ... }} value placeholders, and the collection name out of a
# {% for item in collection %} loop marker row (the loop variable itself,
# e.g. "item", isn't a top-level field the caller supplies -- "collection"
# is). Two separate patterns rather than one, since xltpl loop markers use
# `{%`, not `{{` -- see excel_engine.render_xlsx_template's docstring.
_VALUE_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)")
_FOR_LOOP_RE = re.compile(r"\{%\s*for\s+\w+\s+in\s+([A-Za-z_][A-Za-z0-9_]*)")

# "for"/"endfor" are Jinja keywords the regex can pick up from a loop
# marker cell's raw text (e.g. "{% for item in items %}"), not fields.
_JINJA_KEYWORDS = {"for", "endfor", "if", "endif", "else", "elif"}

# Which engine produced the answer, per template type -- what the schema
# route reports back alongside the field list.
ENGINE_BY_EXT = {"docx": "docxtpl", "html": "jinja2-ast", "xlsx": "regex-scan"}


def detect_fields(template_path: str | Path, template_ext: str) -> list[str]:
    """Sorted placeholder names in the file at `template_path`. Raises
    whatever the underlying parser raises on a malformed template; callers
    that must not fail because of that (a version snapshot) catch it."""
    path = Path(template_path)
    if template_ext == "docx":
        return sorted(DocxTemplate(str(path)).get_undeclared_template_variables())
    if template_ext == "html":
        return list(parse_html_template(path.read_text(encoding="utf-8")).fields)

    names: set[str] = set()
    with zipfile.ZipFile(path) as zf:
        for entry in zf.namelist():
            if not entry.endswith(".xml"):
                continue
            text = zf.read(entry).decode("utf-8", errors="ignore")
            names.update(_VALUE_PLACEHOLDER_RE.findall(text))
            names.update(_FOR_LOOP_RE.findall(text))
    return sorted(names - _JINJA_KEYWORDS)
