"""docx template -> docx / pdf / png, via docxtpl + LibreOffice headless.

This is the "docx is the source of truth" engine: correct dictionary-based
Khmer line-breaking and justify come from LibreOffice's Writer layout
engine itself (see docs/khmer-line-breaking.md), independent of whether the
segmentation step in doc_engine.segmentation ran or not.
"""
from __future__ import annotations

import io
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage

from .. import charts, fonts, images
from ..config import SOFFICE_BIN


class ConversionError(RuntimeError):
    """Raised when LibreOffice or pdftoppm fails to convert a file."""


def _resolve_media(value, tpl: DocxTemplate):
    """Recursively replace any chart-spec dict (charts.is_chart_spec) or
    already-resolved image reference (images.is_image_spec) with an
    InlineImage docxtpl can drop straight into a `{{ }}` placeholder —
    needs `tpl` itself, which is why this can't happen earlier in
    doc_engine.segmentation (that module has no DocxTemplate to attach
    the image to). A chart is rendered to PNG bytes right here, on the
    fly; an image's bytes already arrived pre-resolved (see images.py's
    module docstring for why doc_engine itself never fetches them).
    """
    if charts.is_chart_spec(value):
        png_bytes = charts.render_chart_png(value)
        width_mm = value.get("width_mm", charts.DEFAULT_WIDTH_MM)
        return InlineImage(tpl, io.BytesIO(png_bytes), width=Mm(width_mm))
    if images.is_image_spec(value):
        width_mm = value.get("width_mm", images.DEFAULT_WIDTH_MM)
        return InlineImage(tpl, io.BytesIO(value["image_bytes"]), width=Mm(width_mm))
    if isinstance(value, list):
        return [_resolve_media(v, tpl) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_media(v, tpl) for k, v in value.items()}
    return value


_CORE_PROPERTIES_REL = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
_WRONG_CORE_PROPERTIES_REL = re.compile(r'Type="[^"]*/metadata/core-properties"')


def _normalized_template(path: str | Path) -> io.BytesIO:
    """The template's bytes, with the one package quirk known to make a rendered file unreadable fixed.

    WPS Office writes the core-properties relationship in `_rels/.rels` with the wrong type URL
    (`.../officedocument/2006/...` instead of `.../package/2006/...`). python-docx then doesn't recognise
    the existing `docProps/core.xml`, makes a new default one on save, and the result has **two**
    `docProps/core.xml` entries -- which LibreOffice refuses to open ("source file could not be loaded"),
    for every run of the report, whatever the data. Pointing the relationship at the standard type up
    front means the file round-trips cleanly. A template that is already right is returned as it was."""
    raw = Path(path).read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as source:
            rels = source.read("_rels/.rels").decode("utf-8")
            fixed = _WRONG_CORE_PROPERTIES_REL.sub(f'Type="{_CORE_PROPERTIES_REL}"', rels)
            if fixed == rels:
                return io.BytesIO(raw)
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as target:
                for item in source.infolist():
                    data = fixed.encode("utf-8") if item.filename == "_rels/.rels" else source.read(item.filename)
                    target.writestr(item, data, compress_type=item.compress_type)
            out.seek(0)
            return out
    except (KeyError, zipfile.BadZipFile, UnicodeDecodeError):
        return io.BytesIO(raw)  # not a package we can adjust; let docxtpl report whatever is wrong with it


def _without_duplicate_entries(docx_bytes: bytes) -> bytes:
    """Keep the first of any zip entries that share a name. Two parts with one name is never valid in an
    Office package and LibreOffice refuses to load it; whichever tool produced the duplicate, the first
    copy is the one the document's own relationships point at."""
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as source:
        names = [item.filename for item in source.infolist()]
        if len(names) == len(set(names)):
            return docx_bytes
        out = io.BytesIO()
        seen: set[str] = set()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                if item.filename in seen:
                    continue
                seen.add(item.filename)
                target.writestr(item, source.read(item), compress_type=zipfile.ZIP_DEFLATED)
        return out.getvalue()


def render_docx(context: dict, template_path: str | Path) -> bytes:
    """Render a user-registered report template (see
    api/app/report_store.py) against `context`."""
    tpl = DocxTemplate(_normalized_template(template_path))
    # autoescape: a value is data, not markup. Without it a `&`, `<` or `>` in a value ("R&D", "a<b") is
    # written into the document's XML as-is, and everything from that character on is silently dropped
    # ("R&D Dept" prints as "R "). docxtpl's own objects (images, rich text, sub-documents) are exempt.
    tpl.render(_resolve_media(context, tpl), autoescape=True)
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "report.docx"
        tpl.save(str(out_path))
        return _without_duplicate_entries(out_path.read_bytes())


def _convert(docx_bytes: bytes, target_format: str) -> bytes:
    """Convert docx bytes to `target_format` via LibreOffice headless.

    Each call gets its own `-env:UserInstallation` profile dir so
    concurrent calls don't collide on LibreOffice's shared profile lock.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        docx_path = tmp_path / "report.docx"
        docx_path.write_bytes(docx_bytes)
        profile_dir = tmp_path / "lo_profile"
        # Fonts added at runtime (Resources > Fonts) go into this conversion's own profile: LibreOffice reads
        # <profile>/user/fonts when it starts, and it is started afresh for every conversion.
        fonts.install_into_profile(profile_dir)

        result = subprocess.run(
            [
                SOFFICE_BIN,
                f"-env:UserInstallation=file://{profile_dir}",
                "--headless",
                "--convert-to", target_format,
                "--outdir", str(tmp_path),
                str(docx_path),
            ],
            capture_output=True,
            text=True,
        )
        out_path = tmp_path / f"report.{target_format}"
        if result.returncode != 0 or not out_path.exists():
            raise ConversionError(
                f"soffice failed converting to {target_format}: {result.stderr}"
            )
        return out_path.read_bytes()


def render_pdf(context: dict, template_path: str | Path) -> bytes:
    return _convert(render_docx(context, template_path), "pdf")


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
