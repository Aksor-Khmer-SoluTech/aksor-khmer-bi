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

The code functions every template kind has -- `qrcode(...)`, `barcode(...)` (doc_engine/codes.py) -- aren't fields
the caller supplies, so a name used only as such a call is left out; a field that happens to be named `barcode`
(`{{ barcode }}`, `{{ barcode.x }}`) is still listed.
"""
from __future__ import annotations

import io
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
# The value a code is drawn from: `{{ qrcode(invoice_no) }}` needs `invoice_no` (the regex scan only sees the first
# name inside the braces otherwise).
_CODE_ARGUMENT_RE = re.compile(r"\b(?:qrcode|barcode)\(\s*([A-Za-z_][A-Za-z0-9_]*)")

# "for"/"endfor" are Jinja keywords the regex can pick up from a loop
# marker cell's raw text (e.g. "{% for item in items %}"), not fields.
_JINJA_KEYWORDS = {"for", "endfor", "if", "endif", "else", "elif"}

CODE_FUNCTIONS = ("qrcode", "barcode")
# Functions the renderer provides rather than fields the caller supplies: the codes, and (Word) a library image.
TEMPLATE_FUNCTIONS = (*CODE_FUNCTIONS, "resource")
_XML_TAG_RE = re.compile(r"<[^>]+>")
# `{{ resource('ministry-logo', width_mm=52) }}` in a Word template -- the literal name, as html_template finds it.
_DOCX_RESOURCE_RE = re.compile(r"""\bresource\(\s*(?:'([^'{}]+)'|"([^"{}]+)")""")


def called_only(name: str, text: str) -> bool:
    """Every use of `name` in `text` is a call, `name(` -- so it's the template function, not a field."""
    uses = list(re.finditer(rf"(?<![\w.]){name}\b", text))
    return bool(uses) and all(re.match(r"\s*\(", text[m.end():]) for m in uses)


def _without_functions(names: set[str], text: str) -> set[str]:
    return {n for n in names if not (n in TEMPLATE_FUNCTIONS and called_only(n, text))}


def _package_text(path: Path | io.BytesIO) -> str:
    """The text of every XML part, tags taken out -- so a placeholder Word split across runs reads whole."""
    with zipfile.ZipFile(path) as zf:
        return " ".join(_XML_TAG_RE.sub("", zf.read(n).decode("utf-8", errors="ignore")) for n in zf.namelist() if n.endswith(".xml"))


def docx_resource_names(content: bytes) -> list[str]:
    """The library images a Word template places with `{{ resource('name') }}` -- in the body, headers and footers
    alike -- sorted. Each must be mapped to an image when the template is registered (html_template's bindings).
    Word's curly quotes (‘name’, “name”) count too: autocorrect turns typed quotes into them."""
    text = _package_text(io.BytesIO(content)).translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})
    return sorted({a or b for a, b in _DOCX_RESOURCE_RE.findall(text)})

# Which engine produced the answer, per template type -- what the schema
# route reports back alongside the field list.
ENGINE_BY_EXT = {"docx": "docxtpl", "html": "jinja2-ast", "xlsx": "regex-scan"}


def detect_fields(template_path: str | Path, template_ext: str) -> list[str]:
    """Sorted placeholder names in the file at `template_path`. Raises
    whatever the underlying parser raises on a malformed template; callers
    that must not fail because of that (a version snapshot) catch it."""
    path = Path(template_path)
    if template_ext == "docx":
        return sorted(_without_functions(set(DocxTemplate(str(path)).get_undeclared_template_variables()), _package_text(path)))
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
            names.update(_CODE_ARGUMENT_RE.findall(text))
    return sorted(_without_functions(names - _JINJA_KEYWORDS, _package_text(path)))
