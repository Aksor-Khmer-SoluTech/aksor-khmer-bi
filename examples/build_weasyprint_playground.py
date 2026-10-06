#!/usr/bin/env python3
"""Render weasyprint_playground.html (the original Khmer/WeasyPrint quirks
demo: justify with/without spaces, word-break, columns, etc.) to a PDF.

Fonts live in templates/fonts/, not next to this HTML file, so base_url
points at templates/ rather than this examples/ directory.
"""
from pathlib import Path
from weasyprint import HTML

BASE_DIR = Path(__file__).parent
REPO_ROOT = BASE_DIR.parent
HTML_FILE = BASE_DIR / "weasyprint_playground.html"
FONTS_BASE = REPO_ROOT / "templates"
OUTPUT_FILE = REPO_ROOT / "output" / "weasyprint_playground.pdf"

OUTPUT_FILE.parent.mkdir(exist_ok=True)
HTML(filename=str(HTML_FILE), base_url=str(FONTS_BASE)).write_pdf(str(OUTPUT_FILE))
print(f"Wrote {OUTPUT_FILE}")
