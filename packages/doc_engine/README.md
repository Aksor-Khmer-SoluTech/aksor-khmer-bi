# doc_engine

Format-routed document rendering: one `render(context, fmt, backend=...)`
call produces `docx`, `pdf`, `png`, or `xlsx` from a plain dict of fields.

```python
from doc_engine import render

context = {
    "taxpayer_name": "សុខ សុភា",
    "pin": "PIN-SAMPLE-0000001",
    ...
    "banks": ["ធនាគារ ក", "ធនាគារ ខ", ...],
    "tax_items": [{"label": "...", "amount": 1_250_000}],
}

pdf_bytes = render(context, "pdf")                       # LibreOffice engine (default)
pdf_bytes = render(context, "pdf", backend="weasyprint")  # WeasyPrint engine
docx_bytes = render(context, "docx")                      # always LibreOffice — only possible path
xlsx_bytes = render(context, "xlsx")                      # always openpyxl — unrelated to either engine
```

See `../../docs/architecture.md` for why the routing table looks the way it
does, and `../../docs/khmer-line-breaking.md` for the underlying Khmer
text-layout findings that drove the two-engine split.

Every free-text field is passed through `aksor_khmer_ocr_segmenter` (ICU word
segmentation) before rendering, regardless of backend — see
`src/doc_engine/segmentation.py`.
