"""Spreadsheet builder — independent of both the docx and html engines."""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from xltpl.writerx import BookWriter


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
    writer = BookWriter(str(template_path))
    writer.render_book([context])
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / f"report-{uuid.uuid4().hex}.xlsx"
        writer.save(str(out_path))
        return out_path.read_bytes()
