"""The JDBC driver service: runs one read-only query per request through a
vendor JDBC driver (.jar) an administrator uploaded to Aksor Khmer BI.

Why a separate service: a .jar is code, and loading it runs it. This container
is where that happens, and it is deliberately boring and powerless --

* it holds nothing worth stealing: no database access, no encryption key, no
  stored credentials. Each request carries the one connection's login for the
  one query, and nothing is kept;
* it is on its own network (`aksor-jdbc`), so a driver can't reach the
  platform's PostgreSQL or Redis;
* the filesystem is read-only, it runs as an unprivileged user with capped
  memory/CPU/processes (docker-compose.yml), and drivers are mounted read-only;
* every query runs in a fresh JVM that is killed at the timeout, so a driver
  can't keep state between queries or between organizations;
* a driver is loaded only if its SHA-256 still matches what was recorded at
  upload, so a file swapped on the volume afterwards is refused.

Requests are authenticated with a shared token (JDBC_WORKER_TOKEN) and nothing
here is published to the host. Errors are logged here in full and returned to
the API as a short `kind`, never as driver text.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

log = logging.getLogger("jdbc_worker")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

TOKEN = os.environ.get("JDBC_WORKER_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("JDBC_WORKER_TOKEN must be set -- the worker won't run unauthenticated")
if len(TOKEN) < 32:
    raise SystemExit("JDBC_WORKER_TOKEN is too short -- use at least 32 characters, e.g. `openssl rand -hex 32`")

DRIVER_DIR = Path(os.environ.get("JDBC_DRIVER_DIR", "/drivers"))
RUNNER = Path(__file__).with_name("runner.py")
FILE_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}\.jar$")
CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)+$")

app = FastAPI(title="Aksor Khmer BI JDBC driver service", docs_url=None, redoc_url=None, openapi_url=None)


class Query(BaseModel):
    driver_file: str
    driver_sha256: str = Field(..., min_length=64, max_length=64)
    driver_class: str
    jdbc_url: str = Field(..., max_length=1000)
    username: str
    password: str
    sql: str = Field(..., max_length=20_000)
    args: list[str] = Field(default_factory=list, max_length=200)
    timeout_seconds: float = Field(30, gt=0, le=300)
    max_rows: int = Field(20000, gt=0, le=1_000_000)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fail(kind: str, detail: str, password: str) -> JSONResponse:
    log.warning("query failed (%s): %s", kind, detail.replace(password, "***") if password else detail)
    return JSONResponse(status_code=500, content={"kind": kind})


@app.post("/query")
def query(body: Query, x_worker_token: str = Header("")) -> JSONResponse:
    if not hmac.compare_digest(x_worker_token.encode(), TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not FILE_RE.match(body.driver_file) or not CLASS_RE.match(body.driver_class):
        raise HTTPException(status_code=400, detail="Invalid driver")
    jar = DRIVER_DIR / body.driver_file
    if not jar.is_file() or jar.resolve().parent != DRIVER_DIR.resolve():
        return _fail("driver", f"driver file {body.driver_file} not found", body.password)
    if not hmac.compare_digest(_sha256(jar), body.driver_sha256):
        return _fail("driver", f"driver file {body.driver_file} doesn't match its recorded SHA-256", body.password)

    job = {
        "jar": str(jar), "class": body.driver_class, "url": body.jdbc_url, "user": body.username, "password": body.password,
        "sql": body.sql, "args": body.args, "max_rows": body.max_rows,
    }
    # A minimal environment: nothing of this service's own reaches the driver's JVM.
    env = {"PATH": os.environ.get("PATH", ""), "HOME": "/tmp", "LANG": "C.UTF-8", "JAVA_TOOL_OPTIONS": "-Xmx384m"}
    if os.environ.get("JAVA_HOME"):
        env["JAVA_HOME"] = os.environ["JAVA_HOME"]
    try:
        done = subprocess.run(
            [sys.executable, str(RUNNER)], input=json.dumps(job), capture_output=True, text=True,
            timeout=body.timeout_seconds + 10, env=env, cwd="/tmp",
        )
    except subprocess.TimeoutExpired:
        return _fail("timeout", "the query ran past its time limit and was stopped", body.password)

    try:
        result = json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return _fail("query", f"runner exited {done.returncode}: {done.stderr[-800:]}", body.password)
    if "error" in result:
        return _fail(result["error"], result.get("detail", ""), body.password)
    return JSONResponse(content=result)
