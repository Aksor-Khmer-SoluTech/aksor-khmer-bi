"""Plain CRUD for ProtectedTermSet -- pure DB rows, no file-on-disk half
(unlike image_store.py/report_store.py, a term set is just JSON, nothing
binary to keep alongside it). Same "no caching, fresh SessionLocal() per
call" posture as image_store.py. See specs/protected_terms_design.md.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from . import db
from .db import ProtectedTermSet


class ProtectedTermSetNotFoundError(Exception):
    """Raised when `set_id` has no matching row."""


def _row_to_dict(row: ProtectedTermSet) -> dict:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "name": row.name,
        "description": row.description,
        "terms": row.terms,
        "exclude_terms": row.exclude_terms,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def create_set(
    org_id: str,
    name: str,
    description: str | None,
    terms: list[str],
    exclude_terms: list[str],
    created_by: str | None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    row = ProtectedTermSet(
        id=db._gen_id(),
        org_id=org_id,
        name=name,
        description=description,
        terms=terms,
        exclude_terms=exclude_terms,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    with db.SessionLocal() as session:
        session.add(row)
        session.commit()
        return _row_to_dict(row)


def get_set(set_id: str) -> dict:
    with db.SessionLocal() as session:
        row = session.get(ProtectedTermSet, set_id)
        if row is None:
            raise ProtectedTermSetNotFoundError(set_id)
        return _row_to_dict(row)


def list_sets(org_id: str | None = None) -> list[dict]:
    with db.SessionLocal() as session:
        query = select(ProtectedTermSet).order_by(ProtectedTermSet.name)
        if org_id is not None:
            query = query.where(ProtectedTermSet.org_id == org_id)
        rows = session.execute(query).scalars().all()
        return [_row_to_dict(row) for row in rows]


def update_set(set_id: str, name: str, description: str | None, terms: list[str], exclude_terms: list[str]) -> dict:
    """Replace wholesale (name/description/terms/exclude_terms together)
    -- same "one dedicated update function, no general partial-patch"
    posture report_store.update_data_config uses for parameters/
    data_source."""
    with db.SessionLocal() as session:
        row = session.get(ProtectedTermSet, set_id)
        if row is None:
            raise ProtectedTermSetNotFoundError(set_id)
        row.name = name
        row.description = description
        row.terms = terms
        row.exclude_terms = exclude_terms
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _row_to_dict(row)


def delete_set(set_id: str) -> None:
    with db.SessionLocal() as session:
        row = session.get(ProtectedTermSet, set_id)
        if row is None:
            raise ProtectedTermSetNotFoundError(set_id)
        session.delete(row)
        session.commit()
