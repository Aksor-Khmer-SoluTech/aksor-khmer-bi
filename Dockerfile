# Pinned to a Debian release (not the floating `3.12-slim`): when `slim` moves to the next Debian, package names
# change (as in the 64-bit-time transition) and a build that worked yesterday stops working.
FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Where apt, pip and npm download from. The defaults are the public ones; on a server that can't reach them,
# point these (APT_MIRROR / PIP_INDEX_URL / NPM_REGISTRY in .env) at an internal mirror -- see docs/deployment.md ("Get Docker ready").
ARG APT_MIRROR=deb.debian.org
ARG APT_SCHEME=http
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN for f in /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list; do \
      [ -f "$f" ] && sed -i -e "s#https\?://deb\.debian\.org#${APT_SCHEME}://${APT_MIRROR}#g" -e "s#deb\.debian\.org#${APT_MIRROR}#g" "$f"; \
    done; true

# Mirrors .github/workflows/ci.yml's apt list (tesseract/ICU/LibreOffice/poppler),
# plus the runtime libs WeasyPrint needs that CI's ubuntu-latest image ships
# with by default.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libicu-dev \
    tesseract-ocr \
    tesseract-ocr-khm \
    libreoffice \
    poppler-utils \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# doc_engine.config.REPO_ROOT is derived from this package's on-disk depth
# (packages/doc_engine/src/doc_engine/config.py -> 4 parents up), so the
# packages/ and templates/ layout below must be preserved as-is under /app.
# api/ lives at the repo root, alongside packages/ and templates/, not
# under packages/ — it's the deployable service, not an installable
# library, so it's kept structurally separate.
# templates/ is copied further down, after the pip installs: editing the
# document templates is common and shouldn't bust the (much more expensive)
# dependency-install layer cache.
COPY packages/aksor_khmer_ocr_segmenter packages/aksor_khmer_ocr_segmenter
COPY packages/doc_engine packages/doc_engine
COPY api api

RUN pip install --no-cache-dir -e packages/aksor_khmer_ocr_segmenter \
    && pip install --no-cache-dir -e packages/doc_engine \
    && pip install --no-cache-dir -r api/requirements.txt

COPY templates templates

# Report templates reference these font families by name ("Khmer OS
# Siemreap" / "Khmer OS Muol Light"); WeasyPrint loads the .ttf files
# directly via @font-face, but LibreOffice needs them registered as
# system fonts to find them by name during docx->pdf/png conversion.
RUN mkdir -p /usr/share/fonts/truetype/aksor-khmer \
    && cp templates/fonts/*.ttf /usr/share/fonts/truetype/aksor-khmer/ \
    && fc-cache -f

WORKDIR /app/api

EXPOSE 8000

# Applies pending Alembic migrations (migrations/, DATABASE_URL) before
# starting uvicorn -- see docker-entrypoint.sh.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
