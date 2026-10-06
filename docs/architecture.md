# Architecture: which engine renders which format

There are two rendering engines in this project, and they don't compete
across all four output formats — each format has at most one or two real
paths, encoded directly in `packages/doc_engine/src/doc_engine/registry.py`.

| Format | LibreOffice engine (docx source) | WeasyPrint engine (HTML source) |
|--------|-----------------------------------|----------------------------------|
| `docx` | ✅ native — the only possible path (the `.docx` *is* the source) | ❌ not possible — WeasyPrint has no Word output |
| `xlsx` | N/A — built independently via `openpyxl`, unrelated to either engine | N/A |
| `pdf`  | `.docx` → `soffice --convert-to pdf` | HTML/CSS → PDF directly (Pango/Cairo) |
| `png`  | same PDF → `pdftoppm` | same PDF → `pdftoppm` (identical last step either way) |

So the only place a real choice exists is **pdf/png**, exposed as the
`backend` parameter on `doc_engine.render()` and the API's `backend` query
param.

## Choosing a backend for pdf/png

**`libreoffice` (default).** Use when:
- The docx template is the actual source of truth (what a human edits in Word).
- Khmer justify quality matters and you don't want to rely on the
  segmentation step alone — LibreOffice's Writer engine does dictionary-based
  Khmer line-breaking natively (see `khmer-line-breaking.md`).
- You need the PDF/PNG to visually match the DOCX output exactly (same
  template, same conversion path).

Cost: LibreOffice headless is a large dependency (~1-2GB), slower per call
(spins up a process), and needs the per-request `-env:UserInstallation`
profile-dir isolation already built into `libreoffice_engine.py` to avoid
concurrent requests colliding on LibreOffice's shared profile lock.

**`weasyprint`.** Use when:
- The template is HTML/CSS-designed and you want fine-grained print-CSS
  control (`@page`, running headers/footers, CSS Grid, etc.) that a docx
  template can't express.
- You want a lightweight, pure-Python rendering path with no external
  process — better fit for constrained containers or serverless.
- Text has already passed through `aksor_khmer_ocr_segmenter.process_text()` (this
  is unconditional in `doc_engine.segmentation.segment_context()`, so it's
  automatic) — without that step, WeasyPrint cannot line-break unspaced
  Khmer at all.

## Why segmentation runs unconditionally, regardless of backend

`doc_engine.registry.render()` always calls `segment_context()` before
handing data to either engine. For the `libreoffice` backend this is
"insurance" — ICU-based justify distribution across more break points, and
forward-compatibility if the same data is ever re-rendered through
`weasyprint`. For the `weasyprint` backend it's load-bearing — without it,
unspaced Khmer simply doesn't wrap.

## Adding a third engine or format

The registry function is the one place format/engine decisions are made.
To add a new output format: add an `engines/<name>_engine.py` module with a
`render_<format>()` function, then add one branch to `registry.render()`.
To add a new pdf/png backend: add the engine module (must expose
`render_pdf`/`render_png`) and extend the `Backend` literal + the two
branches that dispatch on it.
