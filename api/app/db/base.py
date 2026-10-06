"""Engine/session/declarative base shared by every table module in this
package, plus `_gen_id` -- the one id-generation scheme every table uses.
"""
from __future__ import annotations

import os
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./aksor_khmer_bi.db")

# SQLite's default driver refuses to share a connection across threads;
# FastAPI's threadpool-backed sync routes need that, and a Session's
# connection is short-lived (one `with SessionLocal() as session:` block
# per report_store call) so there's no cross-thread sharing of state to
# worry about. Irrelevant for postgresql+psycopg, which doesn't have this
# restriction.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _gen_id() -> str:
    """Short opaque id, same style as report_store.create_report's
    `uuid.uuid4().hex[:12]` -- every entity in this schema is identified
    this way, not by a database-assigned autoincrement integer, so ids
    are stable/predictable across environments (a fixture-seeded id in
    tests looks like a real one) and never leak row-count information.
    """
    return uuid.uuid4().hex[:12]
