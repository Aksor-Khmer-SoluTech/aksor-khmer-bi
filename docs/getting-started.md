# Install and run

Two paths: Docker (fastest, recommended) or a local Python venv (if
you're actively developing this codebase). Either way, by the end
you'll have registered and rendered your own template.

## Path A: Docker

```bash
git clone --depth 1 https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi.git   # public: no login needed
cd aksor-khmer-bi
./deployment.sh init   # once: creates the shared network and a .env with generated secrets
./deployment.sh up     # starts postgres + redis, then api / scheduler / worker / portal
```

Open http://localhost:8000/docs — that's the full interactive API
reference (Swagger UI), generated from the actual code, not hand-written
and liable to drift.

### Register and render your own template

```bash
# PORTAL_USERNAME / PORTAL_PASSWORD are in .env (./deployment.sh init generated them);
# after editing .env: ./deployment.sh up

# Sign in once -- the answer holds a 15-minute access token (see docs/authentication.md).
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "pick something real"}' | jq -r .access_token)

curl -X POST http://localhost:8000/api/v1/reports \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@examples/report_templates/receipt.docx" \
  -F "name=Receipt"
# -> {"report_id": "...", ...} — save the report_id
# (For a quick one-off, `curl -u admin:'pick something real' …` works too — HTTP Basic is still accepted.)

curl -X POST "http://localhost:8000/api/v1/reports/<report_id>/render?format=pdf" \
  -H "Content-Type: application/json" \
  -d '{"receipt_no": "R-0001", "date": "១ តុលា ២០២៦", "payer_name": "សុខ សុភា", "received_by": "ជា សុវណ្ណ", "items": [{"label": "ថ្លៃជួលបន្ទប់", "amount": 350000}]}' \
  -o receipt.pdf
```

Or skip `curl` and use the management portal at http://localhost:8080
(a separate, independently deployable service from the API — see
[`deployment.md`](deployment.md)) for the same thing with a UI — upload,
preview, edit, and delete templates there instead. See
[`building-a-report.md`](building-a-report.md) for how to build a
template like `receipt.docx` from scratch, and
[`deployment.md`](deployment.md) for what those env vars actually gate.

## Path B: local Python venv

For developing the codebase itself — running tests, editing the
packages directly:

```bash
python3 -m venv venv
source venv/bin/activate

# macOS/Homebrew system deps
./packages/aksor_khmer_ocr_segmenter/scripts/setup_env.sh
brew install --cask libreoffice

pip install -e packages/aksor_khmer_ocr_segmenter
pip install -e packages/doc_engine
pip install -r api/requirements.txt

cd api
export PORTAL_USERNAME=admin PORTAL_PASSWORD='pick something real'
export CORS_ALLOWED_ORIGINS=http://localhost:8080
uvicorn app.main:app --reload --port 8000

# separately, in another terminal:
cd portal && python3 -m http.server 8080
```

Same endpoints, same `/docs` — just running directly on your machine
instead of in a container; the portal is its own static-file process
now too, not something the API serves. On Linux, see
[`deployment.md`](deployment.md#without-docker) for the apt package list
instead of the Homebrew one above.

### Running the test suite

```bash
cd packages/aksor_khmer_ocr_segmenter && python -m pytest tests/ -v
cd packages/doc_engine && python -m pytest tests/ -v
cd api && python -m pytest tests/ -v
```

Or skip the API/venv entirely and call the rendering library directly —
see the root [README](../README.md#quickstart) for that path, if you
just want `doc_engine.render()` in a Python script with no HTTP layer at
all.

## Where to go next

- [`building-a-report.md`](building-a-report.md) — build your own
  receipt/invoice/certificate/whatever template
- [`deployment.md`](deployment.md) — env vars, volumes, TLS, what's in
  the Docker image and why
- [`architecture.md`](architecture.md) — why there are two rendering
  engines and which one a given format uses
- [`why-aksor-khmer-bi.md`](why-aksor-khmer-bi.md) — the problem this
  solves and what it deliberately doesn't try to be
