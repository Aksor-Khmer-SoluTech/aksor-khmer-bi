"""Spreadsheet builder — independent of both the docx and html engines."""
from __future__ import annotations

import io
import re
import tempfile
import uuid
from pathlib import Path

from xltpl.writerx import BookWriter

from .. import codes

# A cell that asked for a QR code or barcode holds this marker until the sheet is written; then the marker goes and
# the picture is anchored at that cell. (Invisible separators, so a marker can't be mistaken for data.)
_MARKER = re.compile("⁣aksor-code:(\\d+)⁣")
_PX_PER_MM = 96 / 25.4  # openpyxl sizes pictures in pixels at 96 dpi


class _Codes:
    """The codes one render asks for, in order: [(png, width_mm)]."""

    def __init__(self) -> None:
        self.drawn: list[tuple[bytes, float]] = []

    def _mark(self, png: bytes, width_mm: float) -> str:
        self.drawn.append((png, float(width_mm)))
        return f"⁣aksor-code:{len(self.drawn) - 1}⁣"

    def qrcode(self, value, width_mm=codes.DEFAULT_QR_WIDTH_MM, level="M") -> str:
        return self._mark(codes.qr_png(value, level), width_mm)

    def barcode(self, value, type="code128", width_mm=codes.DEFAULT_BARCODE_WIDTH_MM, text=False, height_mm=None) -> str:  # noqa: A002
        return self._mark(codes.barcode_png(value, type, text, float(width_mm), height_mm), width_mm)

    def specs(self, value):
        """A QR or barcode spec in the data ({"qr": …} / {"barcode": …, "value": …}) as a marker, like the
        functions; everything else as it was."""
        if codes.is_code_spec(value):
            return self._mark(*codes.spec_png(value))
        if isinstance(value, list):
            return [self.specs(v) for v in value]
        if isinstance(value, dict):
            return {k: self.specs(v) for k, v in value.items()}
        return value

    def place(self, workbook) -> None:
        """Each marked cell: the marker taken out, the picture anchored at the cell's top-left corner, at its width
        (its height follows). A cell holding only the marker is left empty."""
        if not self.drawn:
            return
        from openpyxl.drawing.image import Image
        from PIL import Image as PILImage

        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if not isinstance(cell.value, str) or "⁣aksor-code:" not in cell.value:
                        continue
                    found = [int(n) for n in _MARKER.findall(cell.value)]
                    rest = _MARKER.sub("", cell.value).strip()
                    cell.value = rest or None
                    for offset, index in enumerate(found):
                        png, width_mm = self.drawn[index]
                        with PILImage.open(io.BytesIO(png)) as probe:
                            ratio = probe.height / probe.width
                        picture = Image(io.BytesIO(png))
                        picture.width = round(width_mm * _PX_PER_MM)
                        picture.height = round(width_mm * ratio * _PX_PER_MM)
                        # Two codes in one cell sit side by side rather than on top of each other.
                        if offset:
                            from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
                            from openpyxl.drawing.xdr import XDRPositiveSize2D
                            from openpyxl.utils.units import pixels_to_EMU

                            start = AnchorMarker(col=cell.column - 1, row=cell.row - 1, colOff=pixels_to_EMU(offset * (picture.width + 8)))
                            picture.anchor = OneCellAnchor(_from=start, ext=XDRPositiveSize2D(pixels_to_EMU(picture.width), pixels_to_EMU(picture.height)))
                        else:
                            picture.anchor = cell.coordinate
                        sheet.add_image(picture)


def render_xlsx_template(context: dict, template_path: str | Path) -> bytes:
    """Render a user-supplied .xlsx template (via xltpl) — used for
    user-registered report templates (see api/app/report_store.py).

    Template authoring, verified empirically (xltpl's own docs are thin
    and its whitespace-trim `{%-` tag variant does NOT behave as a plain
    `{{ }}`-scoped for-loop for per-row data — confirmed by direct testing,
    not assumed):
      - `{{ field }}` placeholders go directly in cells, same as docxtpl.
      - A repeating line-item row needs THREE rows: a row containing only
        `{% for item in items %}`, the body row with `{{ item.field }}`
        cells, and a row containing only `{% endfor %}` — plain `{%`, not
        `{%-`. The for/endfor rows are real rows in the output (not
        stripped), so mark them hidden with a 1pt height in the template
        (`ws.row_dimensions[n].hidden = True`) to avoid a visible blank
        line between each repeated row and after the last one.
      - `{{ qrcode(value) }}` / `{{ barcode(value, "ean13") }}` in a cell, or a code spec in the data, puts the code
        there as a picture (codes.py) -- anchored at the cell's corner; size the row and column to fit it.

    Known limitation (verified empirically, isolated with ASCII-vs-Khmer
    and with/without segmentation A/B tests): LibreOffice Calc's headless
    PDF export (`soffice --convert-to pdf`) renders Khmer text in cells as
    garbled/overlapping glyphs, regardless of font or ZWSP — Writer/docx
    has no such issue anywhere else in this codebase. This is specific to
    Calc's PDF *export* renderer; the .xlsx file's cell data itself is
    correct (confirmed via openpyxl read-back), and this render path never
    goes through Calc/PDF in the first place — it returns the raw .xlsx
    bytes xltpl produces. Not independently confirmed how real Excel or
    Google Sheets render the output; treat that as untested.
    """
    drawn = _Codes()
    writer = BookWriter(str(template_path))
    writer.render_book([codes.with_functions(drawn.specs(context), {"qrcode": drawn.qrcode, "barcode": drawn.barcode})])
    drawn.place(writer.workbook)
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / f"report-{uuid.uuid4().hex}.xlsx"
        writer.save(str(out_path))
        return out_path.read_bytes()
