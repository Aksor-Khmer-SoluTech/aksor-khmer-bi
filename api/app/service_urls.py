"""The addresses of the database and Redis, built from their parts.

`DATABASE_URL` / `REDIS_URL` win when set -- a managed database, a local run against SQLite, tests. Otherwise (the
Docker install, docker-compose.yml) the address is assembled here from `POSTGRES_HOST`, `POSTGRES_PASSWORD`, … and
`REDIS_HOST`, `REDIS_PASSWORD`, with the password escaped the way URLs require. That is what lets a password hold any
character -- `@ # / % ? : ! $` and spaces included: pasted into a URL by the compose file, `@` would end the password
and `#` would cut off the rest of the address. The database and Redis client libraries decode the escaped password
back to the exact original.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import quote

from sqlalchemy.engine import URL

SQLITE_DEFAULT = "sqlite:///./aksor_khmer_bi.db"
REDIS_DEFAULT = "redis://localhost:6379/0"


def database_url(environ: Mapping[str, str] = os.environ) -> str:
    if environ.get("DATABASE_URL"):
        return environ["DATABASE_URL"]
    host = environ.get("POSTGRES_HOST")
    if not host:
        return SQLITE_DEFAULT
    return URL.create(
        "postgresql+psycopg",
        username=environ.get("POSTGRES_USER") or "aksor",
        password=environ.get("POSTGRES_PASSWORD") or "aksor",
        host=host,
        port=int(environ.get("POSTGRES_PORT") or 5432),
        database=environ.get("POSTGRES_DB") or "aksor_khmer_bi",
    ).render_as_string(hide_password=False)


def redis_url(environ: Mapping[str, str] = os.environ) -> str:
    if environ.get("REDIS_URL"):
        return environ["REDIS_URL"]
    host = environ.get("REDIS_HOST")
    if not host:
        return REDIS_DEFAULT
    password = environ.get("REDIS_PASSWORD")
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{host}:{environ.get('REDIS_PORT') or 6379}/0"
