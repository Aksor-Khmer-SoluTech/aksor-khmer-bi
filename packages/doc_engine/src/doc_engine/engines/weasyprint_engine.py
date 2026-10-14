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
from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import URLFetcher

from .. import codes, fonts

_USER_TEMPLATE_FETCHER = URLFetcher(allowed_protocols={"data"}, fail_on_errors=True)


class ConversionError(RuntimeError):
    """Raised when pdftoppm fails to rasterize the generated PDF."""


def _qrcode(value, width_mm=None, level="M") -> str:
    """`<img src="{{ qrcode(value) }}">`: the code as an SVG data: URI -- sharp at any size; size it with CSS.
    (`width_mm` is accepted so one call reads the same in every kind of template; in HTML the CSS decides.)"""
    return codes.svg_data_uri(codes.qr_svg(value, level))


def _barcode(value, type="code128", width_mm=None, text=False, height_mm=None) -> str:  # noqa: A002 -- the template's word for it
    return codes.svg_data_uri(codes.barcode_svg(value, type, text))


def _render_html(context: dict, template_path: str | Path) -> str:
    env = Environment(autoescape=True)
    template = env.from_string(Path(template_path).read_text(encoding="utf-8"))
    return template.render(**codes.with_functions(context, {"qrcode": _qrcode, "barcode": _barcode}))


def render_pdf(context: dict, template_path: str | Path) -> bytes:
    html = _render_html(context, template_path)
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "report.pdf"
        # Fonts added at runtime (Resources > Fonts) that this HTML names, inlined as data: URLs -- the only kind of
        # URL the template's fetcher may load.
        face_css = fonts.font_face_css(html)
        font_config = FontConfiguration()
        stylesheets = (
            [CSS(string=face_css, font_config=font_config, url_fetcher=_USER_TEMPLATE_FETCHER)] if face_css else None
        )
        HTML(string=html, base_url=None, url_fetcher=_USER_TEMPLATE_FETCHER).write_pdf(
            str(out_path), stylesheets=stylesheets, font_config=font_config
        )
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
