"""html template -> pdf / png, via Jinja2 + WeasyPrint.

Lighter footprint than the LibreOffice engine (pure Python + Cairo, no
external process), at the cost of needing the caller to have already run
text through doc_engine.segmentation.segment_generic() — WeasyPrint's
Pango layout has no dictionary-based Khmer line breaking of its own (see
docs/khmer-line-breaking.md). Use this engine when the template is
HTML/CSS-designed and you want print-CSS control; use libreoffice_engine
when the docx template is the source of truth.

`template_path` renders a *user-uploaded* HTML template
(api/app/report_store.py's template_ext="html") — api/app/html_template.py
is the validation/resource-binding layer in front of this; this module
only renders. Since that template's source is untrusted (registered by
any report:manage caller, not shipped with the backend):
  - `autoescape=True` — arbitrary org data reaches the template as
    `context`, so a field value containing `<`/`&` must not be able to
    corrupt the surrounding markup.
  - `base_url=None` plus a WeasyPrint URLFetcher restricted to the
    `data:` scheme — the template gets no filesystem base to resolve
    relative paths against and can't reach any http(s)/file URL either;
    the only sanctioned way to pull in an asset is the `resource`
    callable already bound into `context` by
    html_template.build_resource_resolver, which returns a self-
    contained `data:` URI needing no fetch at all. See html_template.py's
    module docstring for the full two-layer rationale.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment
from weasyprint import HTML
from weasyprint.urls import URLFetcher

_USER_TEMPLATE_FETCHER = URLFetcher(allowed_protocols={"data"}, fail_on_errors=True)


class ConversionError(RuntimeError):
    """Raised when pdftoppm fails to rasterize the generated PDF."""


def _render_html(context: dict, template_path: str | Path) -> str:
    env = Environment(autoescape=True)
    template = env.from_string(Path(template_path).read_text(encoding="utf-8"))
    return template.render(**context)


def render_pdf(context: dict, template_path: str | Path) -> bytes:
    html = _render_html(context, template_path)
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "report.pdf"
        HTML(string=html, base_url=None, url_fetcher=_USER_TEMPLATE_FETCHER).write_pdf(str(out_path))
        return out_path.read_bytes()


def render_png(context: dict, template_path: str | Path) -> bytes:
    pdf_bytes = render_pdf(context, template_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pdf_path = tmp_path / "report.pdf"
        pdf_path.write_bytes(pdf_bytes)
        out_prefix = tmp_path / "page"

        result = subprocess.run(
            ["pdftoppm", "-r", "150", "-png", "-f", "1", "-l", "1",
             str(pdf_path), str(out_prefix)],
            capture_output=True,
            text=True,
        )
        png_path = tmp_path / "page-1.png"
        if result.returncode != 0 or not png_path.exists():
            raise ConversionError(f"pdftoppm failed: {result.stderr}")
        return png_path.read_bytes()
