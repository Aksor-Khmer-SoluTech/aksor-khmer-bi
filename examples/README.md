# Examples

Standalone scripts exercising each pipeline directly, without the API —
useful for debugging a rendering issue without spinning up uvicorn.

| Script | What it shows |
|---|---|
| `build_weasyprint_playground.py` | Renders `weasyprint_playground.html` — the original Khmer/WeasyPrint quirks demo (justify with/without spaces, `word-break: break-all`, columns) that first surfaced the Khmer line-breaking gap. |
| `build_receipt.py` | `doc_engine.render(data, fmt, template_path=...)` against `report_templates/receipt.docx` — the same mechanism `/api/v1/reports` uses, via the LibreOffice backend. |
| `build_invoice.py` | Same, against `report_templates/invoice.docx` (docx/pdf) and `invoice.xlsx` (xlsx via xltpl) from one dataset — shows both custom-template engines side by side. |

`report_templates/` holds the actual `.docx`/`.xlsx` template files these
two scripts render — worked examples of what you'd build yourself to
register via `/api/v1/reports` (see `docs/building-a-report.md`).

Run any of them from the repo root with the venv active:

```bash
source venv/bin/activate
python examples/build_receipt.py
```

Output lands in `../output/` (gitignored).
