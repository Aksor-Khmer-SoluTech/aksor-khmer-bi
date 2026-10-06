#!/usr/bin/env python3
"""Render report_templates/receipt.docx (a generic payment receipt) via
doc_engine.render()'s template_path, the same mechanism the
/api/v1/reports API uses. Shows the engine working on a template a
developer wrote themselves.
"""
from pathlib import Path
from doc_engine import render

TEMPLATE = Path(__file__).parent / "report_templates" / "receipt.docx"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

data = {
    "receipt_no": "R-0001",
    "date": "១ តុលា ២០២៦",
    "payer_name": "សុខ សុភា",
    "received_by": "ជា សុវណ្ណ",
    "items": [
        {"label": "ថ្លៃជួលបន្ទប់ខែតុលា", "amount": 350_000},
        {"label": "ថ្លៃទឹកភ្លើង", "amount": 45_000},
    ],
}

(OUTPUT_DIR / "receipt.docx").write_bytes(render(data, "docx", template_path=TEMPLATE))
print(f"Wrote {OUTPUT_DIR / 'receipt.docx'}")

(OUTPUT_DIR / "receipt.pdf").write_bytes(render(data, "pdf", template_path=TEMPLATE))
print(f"Wrote {OUTPUT_DIR / 'receipt.pdf'}")
