#!/usr/bin/env python3
"""Render report_templates/invoice.docx and invoice.xlsx from one dataset
via doc_engine.render()'s template_path — the docx path produces
docx/pdf, the xlsx path produces xlsx, demonstrating both custom-template
mechanisms (docxtpl and xltpl) side by side on the same kind of document.
"""
from pathlib import Path
from doc_engine import render

TEMPLATE_DIR = Path(__file__).parent / "report_templates"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

items = [
    {"label": "សេវាកម្មប្រឹក្សាព័ត៌មានវិទ្យា", "qty": 5, "unit_price": 100_000},
    {"label": "ថ្លៃដំឡើងប្រព័ន្ធ", "qty": 1, "unit_price": 250_000},
]
for item in items:
    item["line_total"] = item["qty"] * item["unit_price"]
grand_total = sum(item["line_total"] for item in items)

data = {
    "business_name": "ក្រុមហ៊ុន គំរូ ចម្រុះកិច្ច",
    "business_address": "ផ្ទះលេខ 22 ផ្លូវ 271 សង្កាត់ទឹកល្អក់ ខណ្ឌទួលគោក រាជធានីភ្នំពេញ",
    "invoice_no": "INV-0001",
    "invoice_date": "១ តុលា ២០២៦",
    "customer_name": "សុខ សុភា",
    "due_date": "១៥ តុលា ២០២៦",
    "items": items,
    "grand_total": grand_total,
}

docx_template = TEMPLATE_DIR / "invoice.docx"
(OUTPUT_DIR / "invoice.docx").write_bytes(render(data, "docx", template_path=docx_template))
print(f"Wrote {OUTPUT_DIR / 'invoice.docx'}")

(OUTPUT_DIR / "invoice.pdf").write_bytes(render(data, "pdf", template_path=docx_template))
print(f"Wrote {OUTPUT_DIR / 'invoice.pdf'}")

xlsx_template = TEMPLATE_DIR / "invoice.xlsx"
(OUTPUT_DIR / "invoice.xlsx").write_bytes(render(data, "xlsx", template_path=xlsx_template))
print(f"Wrote {OUTPUT_DIR / 'invoice.xlsx'}")
