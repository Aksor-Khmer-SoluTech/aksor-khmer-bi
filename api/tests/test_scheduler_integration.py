"""Real end-to-end verification of the scheduler/worker split
(app/scheduler.py decides *when*; app/celery_app.py's `run_job` task,
consumed by a real Celery worker, decides *how*) -- actual subprocesses
for both, a real Redis broker, a real shared SQLite database file (the
same DATABASE_URL dialect both processes would use in production, just
not Postgres -- no need for that here since nothing in this test
exercises Postgres-specific behavior).

This caught two real bugs while first being written, not hypothetical
ones: APScheduler's SQLAlchemyJobStore refusing to pickle a scheduler
instance passed as a job argument, and a naive reconcile loop resetting
an unchanged job's `next_run_time` on every poll (so a 10s-interval job
polled every 5s never actually reached its fire time). Both are exactly
the kind of thing a unit test that calls `reconcile()` once, in-process,
would never catch -- only running the real poll loop across real wall-
clock time does. Kept as a permanent test for that reason, not just a
one-off manual check.

Skipped (not failed) if no Redis is reachable on REDIS_TEST_URL, same
pattern as test_auth_ldap.py's OpenLDAP dependency.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, Job, JobRun
from app.rbac import ROOT_ORG_ID, seed_defaults

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://localhost:6379/0")
_API_DIR = str(Path(__file__).resolve().parents[1])


def _redis_reachable() -> bool:
    parsed = urlparse(REDIS_TEST_URL)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 6379), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _redis_reachable(), reason=f"No Redis reachable at {REDIS_TEST_URL} -- see module docstring")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def shared_db(tmp_path):
    """A real file-backed SQLite database, shared by this test process
    and the worker/scheduler subprocesses via DATABASE_URL -- unlike the
    rest of this test suite (api/tests/conftest.py monkeypatches
    `db.SessionLocal` in-process), a subprocess re-imports app.db fresh
    and needs an actual env var to find the same database.
    """
    database_url = f"sqlite:///{tmp_path / 'scheduler_integration.db'}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        seed_defaults(session)
        session.commit()
    return database_url, session_factory


@pytest.fixture
def worker_and_scheduler(shared_db):
    database_url, _ = shared_db
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "REDIS_URL": REDIS_TEST_URL,
        "SCHEDULER_RECONCILE_INTERVAL_SECONDS": "2",
        "PYTHONUNBUFFERED": "1",
    }

    worker = subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "app.celery_app", "worker", "--loglevel=info", "--concurrency=1"],
        cwd=_API_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    scheduler = subprocess.Popen(
        [sys.executable, "-m", "app.scheduler"],
        cwd=_API_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    deadline = time.time() + 30
    ready = False
    while time.time() < deadline:
        line = worker.stdout.readline()
        if not line:
            break
        if "ready" in line.lower():
            ready = True
            break

    try:
        assert ready, "celery worker did not report ready in time"
        yield
    finally:
        worker.terminate()
        scheduler.terminate()
        try:
            worker.wait(timeout=10)
            scheduler.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            scheduler.kill()


def test_interval_job_fires_on_its_own_without_manual_triggering(shared_db, worker_and_scheduler, tmp_path):
    _, session_factory = shared_db
    output_file = tmp_path / "fired.txt"

    with session_factory() as session:
        job = Job(
            org_id=ROOT_ORG_ID,
            name="scheduler integration test",
            job_type="file_output",
            config={"destination_path": str(output_file), "source": "static", "content": "fired"},
            trigger_type="interval",
            interval_seconds=3,
            is_enabled=True,
            max_retries=0,
            retry_backoff_seconds=5,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    deadline = time.time() + 30
    while not output_file.exists() and time.time() < deadline:
        time.sleep(1)

    assert output_file.exists(), "job never fired on its own within the deadline"
    assert output_file.read_text() == "fired"

    with session_factory() as session:
        runs = session.query(JobRun).filter(JobRun.job_id == job_id).all()
    assert len(runs) >= 1
    assert runs[0].status == "success"
    assert runs[0].triggered_by == "schedule"


def test_retryable_failure_retries_then_fails_permanently(shared_db, worker_and_scheduler):
    """The job itself is never actually fired by the scheduler (run_at
    far in the future) -- triggered directly by inserting a JobRun and
    calling the Celery task the same way POST /jobs/{id}/run does, to
    keep this test's timing independent of the scheduler's poll interval.
    """
    database_url, session_factory = shared_db

    with session_factory() as session:
        job = Job(
            org_id=ROOT_ORG_ID,
            name="retry integration test",
            job_type="rest_call",
            config={"url": "http://127.0.0.1:1/unreachable", "method": "POST"},
            trigger_type="one_off",
            run_at="2099-01-01T00:00:00+00:00",
            is_enabled=True,
            max_retries=2,
            retry_backoff_seconds=2,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        session.add(job)
        session.flush()
        run = JobRun(job_id=job.id, triggered_by="manual", status="queued", attempt_number=1, created_at=_now_iso())
        session.add(run)
        session.commit()
        job_id, run_id = job.id, run.id

    env = {**os.environ, "DATABASE_URL": database_url, "REDIS_URL": REDIS_TEST_URL}
    subprocess.run(
        [sys.executable, "-c", f"from app.celery_app import celery_app; celery_app.send_task('run_job', args=['{job_id}', '{run_id}'])"],
        cwd=_API_DIR,
        env=env,
        check=True,
    )

    deadline = time.time() + 30
    final_status = None
    while time.time() < deadline:
        with session_factory() as session:
            run_row = session.get(JobRun, run_id)
            final_status = run_row.status
            attempt_number = run_row.attempt_number
            result_summary = run_row.result_summary
        if final_status == "failed":
            break
        time.sleep(1)

    assert final_status == "failed"
    assert attempt_number == 3  # 1 initial attempt + 2 retries
    assert "Exhausted 2 retries" in (result_summary or "")
