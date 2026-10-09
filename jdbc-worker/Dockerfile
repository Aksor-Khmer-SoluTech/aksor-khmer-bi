# The JDBC driver service (jdbc-worker/app.py): a JRE, JayDeBeApi, and nothing
# else. Built only when the `jdbc` compose profile is used, so deployments that
# don't upload vendor drivers never carry a JVM.
# Pinned to a Debian release -- see the main Dockerfile.
FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Where apt and pip download from while the image is built. The defaults are the public ones; a maintainer behind a
# slow or filtered network can point them at mirrors (APT_MIRROR / APT_SCHEME / PIP_INDEX_URL in the environment of
# scripts/publish-images.sh, which passes them through).
ARG APT_MIRROR=deb.debian.org
ARG APT_SCHEME=http
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN for f in /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list; do \
      [ -f "$f" ] && sed -i -e "s#https\?://deb\.debian\.org#${APT_SCHEME}://${APT_MIRROR}#g" -e "s#deb\.debian\.org#${APT_MIRROR}#g" "$f"; \
    done; true

RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --no-create-home --uid 10001 jdbc

WORKDIR /app
COPY jdbc-worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY jdbc-worker/app.py jdbc-worker/runner.py ./

USER jdbc
EXPOSE 9000
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9000"]
