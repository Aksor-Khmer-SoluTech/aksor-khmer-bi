#!/bin/sh
# Like docker-entrypoint.sh but skips `alembic upgrade head` -- used by
# the `scheduler`/`worker` services (docker-compose.yml), which
# `depends_on: api: condition: service_healthy` specifically so the
# schema is already guaranteed current by the time either of them starts
# querying it. Running migrations from three processes at once on every
# `docker compose up` isn't a risk worth taking just to make each
# service independently self-sufficient -- `api` is the one place that
# happens, once.
set -e

exec "$@"
