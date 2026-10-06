#!/bin/sh
# Applies pending Alembic migrations (api/migrations/) against whatever
# DATABASE_URL points at, then execs the real command (see Dockerfile's
# CMD) -- so the schema is always current before uvicorn starts accepting
# requests, with no separate manual migration step for a fresh deploy.
# Safe to run every container start: a fully-migrated database is a no-op.
set -e

alembic upgrade head

exec "$@"
