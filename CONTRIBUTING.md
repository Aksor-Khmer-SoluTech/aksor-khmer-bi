# Contributing

Thanks for considering a contribution. This project has three independent
Python packages, each pip-installable on its own:

- `packages/aksor_khmer_ocr_segmenter` — OCR + ICU word segmentation, no dependency on the other two
- `packages/doc_engine` — depends on `aksor_khmer_ocr_segmenter`
- `api` — depends on `doc_engine`; kept at the repo root, structurally separate from `packages/`, since it's the deployable service (Dockerfile, docker-compose.yml target it directly) rather than an installable library

## Dev setup

```bash
python3 -m venv venv
source venv/bin/activate

# System dependencies (macOS/Homebrew — see packages/aksor_khmer_ocr_segmenter/scripts/setup_env.sh)
brew install tesseract icu4c
# + the Khmer trained-data file and PyICU build steps in that script
# + LibreOffice (for the "libreoffice" rendering backend): brew install --cask libreoffice

# Install packages in dependency order, editable
pip install -e packages/aksor_khmer_ocr_segmenter
pip install -e packages/doc_engine
pip install -r api/requirements.txt
```

## Running tests

Each package's tests can run independently:

```bash
cd packages/aksor_khmer_ocr_segmenter && python -m pytest tests/ -v
cd packages/doc_engine && python -m pytest tests/ -v
cd api && python -m pytest tests/ -v
```

CI (`.github/workflows/ci.yml`) runs all three on every PR.

## Where things live

- `templates/fonts/` — Khmer fonts used during rendering (docx→pdf/png conversion, chart labels). Report templates themselves live under `examples/report_templates/` or wherever `/api/v1/reports` stores an uploaded one (`api/data/report_templates/`) — placeholders are Jinja2 (`{{ field }}`, `{% for %}`).
- `api/` — the FastAPI service; see `api/README.md`.
- `portal/` — the management UI's static HTML/CSS/JS, a separate deployable service from `api/` (see `portal/README.md`); its `config.js` points it at wherever `api` runs.
- `examples/` — standalone scripts showing each pipeline in isolation, useful for debugging without spinning up the API, plus `examples/report_templates/` — real `.docx`/`.xlsx` templates to register via `/api/v1/reports`.
- `docs/` — see `docs/getting-started.md` for the full map; `architecture.md` (why two rendering engines), `khmer-line-breaking.md` (the underlying research), `building-a-report.md` (how to build your own template), `deployment.md`, `protected-terms-guide.md`, `why-aksor-khmer-bi.md`.
- `specs/` — local technical design notes for individual features (e.g. `specs/template_portal_design.md`), written before implementation. Gitignored: kept on a maintainer's disk, not in the repo.

## Before opening a PR

- Add or update tests for any behavior change — this project has near-zero
  tolerance for "looks right in one screenshot" without a test backing it up
  (see how every rendering claim in `docs/` was verified against real output,
  not assumed).
- If you touch Khmer text handling specifically, include a test case with
  unspaced Khmer text — that's the scenario that silently breaks most
  Latin-first tooling.
- Keep the three packages independently installable — don't add a hard
  import from `aksor_khmer_ocr_segmenter` or `doc_engine` into code that doesn't
  need it.

## Reporting issues

Please include: which package, which format/backend, the actual vs
expected output, and — for Khmer rendering issues — the specific text that
misbehaves (screenshots alone are hard to debug against).
