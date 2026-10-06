"""A loud, specific message at startup when the database isn't at the schema this code expects.

Without it the symptom is a stack trace deep inside whichever request first touches a table that isn't there
(`no such table: auth_sessions` on the first sign-in). Docker deployments run `alembic upgrade head` before the
API starts, so this matters for a hand-run API (`uvicorn`) whose database was migrated by an older revision --
including the one-off case of the squashed migrations, where `alembic upgrade head` itself can't find the
revision the database names (docs/deployment.md, "Migrations were squashed").

Only logs; never stops the API. A database with no `alembic_version` table at all (built without Alembic, as the
test suite does) is left alone.
"""
from __future__ import annotations

import logging
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from . import db

_log = logging.getLogger("aksor_khmer_bi.schema")

_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def check_schema_version() -> str | None:
    """The problem found, as the message that was logged -- or None when the database is current (or can't be judged)."""
    try:
        head = ScriptDirectory(str(_MIGRATIONS)).get_current_head()
        with db.engine.connect() as conn:
            if "alembic_version" not in inspect(conn).get_table_names():
                return None
            current = MigrationContext.configure(conn).get_current_revision()
        known = {rev.revision for rev in ScriptDirectory(str(_MIGRATIONS)).walk_revisions()}
    except Exception:  # noqa: BLE001 -- a diagnostic must never be the reason the API doesn't start
        return None

    if current == head:
        return None
    if current is not None and current not in known:
        message = (
            f"The database is at migration {current!r}, which no longer exists (the migrations were squashed into "
            f"{head!r}), so `alembic upgrade head` can't run on it. From api/: "
            "`python -c \"from app import db; db.Base.metadata.create_all(db.engine)\"` then "
            f"`alembic stamp --purge {head}` -- see docs/deployment.md, \"Migrations were squashed\"."
        )
    else:
        message = f"The database is at migration {current!r} but this code expects {head!r} -- run `alembic upgrade head` (from api/)."
    _log.error("%s Requests that touch the missing tables will fail until then.", message)
    return message
