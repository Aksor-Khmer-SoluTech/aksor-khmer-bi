# aksor-khmer-bi

**Open-source, self-hostable document generation for Khmer-language
documents** — receipts, invoices, notices, certificates, whatever your
own use case is. Fill a template once, get **PDF, PNG, DOCX, or XLSX**
out, with correct Khmer line-breaking and justify — including for
unspaced Khmer text, which most web/PDF renderers get wrong by default
(see [`docs/khmer-line-breaking.md`](docs/khmer-line-breaking.md)).

[អាន​ជា​ភាសាខ្មែរ / Read this in Khmer →](README.km.md)

*"Aksor" (អក្សរ) is Khmer for script/letters — the name points at the
actual hard problem this project solves: rendering Khmer script correctly.*

Built and verified incrementally: every claim in the docs below was checked
against actual rendered output, not assumed. See
[`docs/why-aksor-khmer-bi.md`](docs/why-aksor-khmer-bi.md) for the full
case for using this — and an honest list of what it deliberately isn't
(it's not a BI/analytics platform, has no data connectors — see that doc
for the details).

## Support the project

Free and open source (MIT) — free to use, for anyone, with nothing held back. It's funded by
**donations**, optional **support subscriptions** (per user or per organisation) and **collaboration**;
see [`SUPPORT.md`](SUPPORT.md). Security issues: [`SECURITY.md`](SECURITY.md).

## Features

| | |
|---|---|
| **Khmer-correct line-breaking** | Dictionary-based (ICU, the same mechanism LibreOffice/Word use), not guessed — verified against real unspaced sentences |
| **Four export formats** | PDF, PNG, DOCX, XLSX from one JSON payload |
| **Bring your own template** | `/api/v1/reports` — register any `.docx`/`.xlsx` with Jinja2 placeholders, render it against arbitrary JSON, no fixed schema |
| **Charts in documents** | Bar/line/pie charts embedded as images in a docx template — Khmer + Latin mixed text handled correctly (see [`building-a-report.md`](docs/building-a-report.md#charts-docx-templates-only)) |
| **Standard sign-in** | Short-lived JWT access tokens + rotating refresh tokens (HttpOnly cookie, reuse detection), revocable sessions, optional TOTP 2FA, LDAP/AD, per-organization roles — see [`docs/authentication.md`](docs/authentication.md) |
| **Management portal** | A small, separately-deployable web UI ([`portal/`](portal)) to register/preview/edit/delete templates, no `curl` required — plus an Admin mode (users, dynamic per-org roles, organizations, an embedded API explorer, live host resource monitoring, a reserved plugins page) for anyone holding the right permissions, and white-label branding config so the portal isn't hard-wired to this project's own name |
| **Two rendering engines** | LibreOffice (native justify, docx-sourced) or WeasyPrint (HTML/CSS-templated, lighter) — pick per request |
| **OCR + segmentation, usable standalone** | The Khmer word-segmentation package has no dependency on the rest of this repo — `pip install` it alone for unrelated Khmer text work |
| **Self-hostable** | MIT-licensed, Docker-ready, no external service dependency — matters for financial/legal documents where data locality is a real requirement |

## What's in here

| Package | What it does |
|---|---|
| [`packages/aksor_khmer_ocr_segmenter`](packages/aksor_khmer_ocr_segmenter) | OCR (Tesseract) + ICU dictionary-based Khmer word segmentation. Inserts invisible break points into unspaced Khmer text. |
| [`packages/doc_engine`](packages/doc_engine) | `render(context, format, backend, template_path=...)` — routes each format to the right engine (LibreOffice for docx/native-justify pdf/png, WeasyPrint for HTML/CSS-templated pdf/png, xltpl for xlsx) and renders your template against `context`. |
| [`api`](api) | FastAPI service: the generic report registry (`/api/v1/reports`) — Swagger/OpenAPI docs at `/docs`. |
| [`portal`](portal) | Static HTML/CSS/JS management UI for `/api/v1/reports` — a separate, independently deployable service (no LibreOffice/Python), points at `api` via `portal/config.js`. |

Worked example templates live in
[`examples/report_templates/`](examples/report_templates) (`receipt.docx`,
`invoice.docx`/`.xlsx` — for the generic `/api/v1/reports` path).
Standalone example scripts are in [`examples/`](examples). Fonts used for
Khmer rendering live in [`templates/fonts`](templates/fonts).

## Why two rendering engines

Short version: WeasyPrint can't produce `.docx`, and neither engine
produces `.xlsx` — so most formats have exactly one possible path. The only
real choice is PDF/PNG, where LibreOffice gets Khmer justify right natively
and WeasyPrint needs the segmentation step first but has a lighter
footprint. Full writeup: [`docs/architecture.md`](docs/architecture.md).

## Quickstart

```bash
./deployment.sh init   # once: network + .env with generated secrets
./deployment.sh up     # postgres + redis, then the app
# open http://localhost:8000/docs (API reference) or http://localhost:8080 (template manager)
```

See [`docs/getting-started.md`](docs/getting-started.md) for the full
walkthrough (Docker and local-venv paths, registering and rendering your
own template) — or the short version:

```bash
python3 -m venv venv
source venv/bin/activate

# System deps (macOS/Homebrew) — see packages/aksor_khmer_ocr_segmenter/scripts/setup_env.sh
./packages/aksor_khmer_ocr_segmenter/scripts/setup_env.sh
brew install --cask libreoffice   # for the "libreoffice" backend

pip install -e packages/aksor_khmer_ocr_segmenter
pip install -e packages/doc_engine
pip install -r api/requirements.txt

cd api
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000/docs
```

Or skip the API entirely and call the library directly against your own
template (see [`examples/build_receipt.py`](examples/build_receipt.py)
for a full worked example):

```python
from doc_engine import render

data = {"customer_name": "សុខ សុភា", ...}  # whatever your template's placeholders are
pdf_bytes = render(data, "pdf", template_path="my_template.docx")                      # LibreOffice backend (default)
pdf_bytes = render(data, "pdf", backend="weasyprint", template_path="my_template.html") # WeasyPrint backend
docx_bytes = render(data, "docx", template_path="my_template.docx")
xlsx_bytes = render(data, "xlsx", template_path="my_template.xlsx")
```

## Documentation

- [`docs/getting-started.md`](docs/getting-started.md) — install and run (Docker or local dev)
- [`docs/building-a-report.md`](docs/building-a-report.md) — build your own receipt/invoice/certificate template
- [`docs/deployment.md`](docs/deployment.md) — Docker, env vars, volumes, TLS
- [`docs/architecture.md`](docs/architecture.md) — engine-selection decision table
- [`docs/khmer-line-breaking.md`](docs/khmer-line-breaking.md) — the underlying research
- [`docs/protected-terms-guide.md`](docs/protected-terms-guide.md) — known ICU mis-splits (names, brands, loanwords) and how to add more
- [`docs/why-aksor-khmer-bi.md`](docs/why-aksor-khmer-bi.md) — the case for using this, and what it isn't

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). This is a community project —
issues and PRs welcome, especially real-world Khmer text cases that expose
edge cases the current segmentation/justify logic doesn't handle yet.

## License

[MIT](LICENSE).
