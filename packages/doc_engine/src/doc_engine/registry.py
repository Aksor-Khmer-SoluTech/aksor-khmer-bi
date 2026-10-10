"""Format -> engine routing.

This module *is* the decision table from docs/architecture.md, as code:

    docx  -> only one possible path: LibreOffice (docx is the source)
    xlsx  -> only one possible path: openpyxl, independent of both
    html  -> only one possible path: WeasyPrint, pdf/png only (see
             weasyprint_engine.py's `template_path` handling)
    pdf   -> either engine; default LibreOffice (matches the docx template
             as source of truth); pass backend="weasyprint" for the
             HTML/CSS-templated, no-LibreOffice-dependency path
    png   -> same choice as pdf (both engines rasterize their own pdf output)
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from .engines import excel_engine, libreoffice_engine, weasyprint_engine
from .segmentation import segment_generic

Format = Literal["docx", "pdf", "png", "xlsx"]
Backend = Literal["libreoffice", "weasyprint"]

ConversionError = libreoffice_engine.ConversionError


def render(
    context: dict,
    fmt: Format,
    backend: Backend = "libreoffice",
    *,
    template_path: str | Path,
    extra_terms: Sequence[str] | None = None,
    exclude_terms: Sequence[str] | None = None,
) -> bytes:
    """Render `context` (a plain dict) against `template_path` — a
    user-supplied template (docx via docxtpl, xlsx via xltpl, or html via
    Jinja2+WeasyPrint — picked by `fmt` and `backend`) — to `fmt`, applying
    Khmer word-segmentation first. See api/app/report_store.py for how a
    template gets registered.

    `backend` only matters for fmt in {"pdf", "png"}; it's ignored for
    "docx" (always LibreOffice, the only possible path) and "xlsx" (always
    xltpl, unrelated to either layout engine).

    An html template only supports "pdf"/"png", and only with
    backend="weasyprint" (there's no LibreOffice path for it); a docx
    template's "pdf"/"png" only support backend="libreoffice" (WeasyPrint
    has no notion of a custom *docx* template). There's no fixed field
    list to allowlist from, so every string in `context` is segmented -- every one that contains Khmer, that is:
    aksor_khmer_ocr_segmenter.process_text leaves text without it (dates, amounts, IDs) exactly as it is.

    `extra_terms`/`exclude_terms` are a per-render protected-terms layer
    on top of aksor_khmer_ocr_segmenter's own deployment-wide default
    (see segmentation.segment_generic) -- api/app/routers/reports.py
    resolves a report's own configured terms and passes them here.
    """
    if fmt in ("pdf", "png") and backend == "weasyprint" and str(template_path).endswith((".docx",)):
        raise ValueError("a custom docx template_path only supports the libreoffice backend")
    if fmt in ("pdf", "png") and backend == "libreoffice" and str(template_path).endswith(".html"):
        raise ValueError("a custom html template_path only supports the weasyprint backend")
    segmented = segment_generic(context, extra_terms=extra_terms, exclude_terms=exclude_terms)

    if fmt == "docx":
        return libreoffice_engine.render_docx(segmented, template_path)

    if fmt == "xlsx":
        return excel_engine.render_xlsx_template(segmented, template_path)

    if fmt == "pdf":
        if backend == "weasyprint":
            return weasyprint_engine.render_pdf(segmented, template_path)
        return libreoffice_engine.render_pdf(segmented, template_path)

    if fmt == "png":
        if backend == "weasyprint":
            return weasyprint_engine.render_png(segmented, template_path)
        return libreoffice_engine.render_png(segmented, template_path)

    raise ValueError(f"Unknown format: {fmt!r}")
