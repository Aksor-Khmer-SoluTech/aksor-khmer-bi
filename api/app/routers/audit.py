"""The change audit trail, for admins: who changed what, when, from where,
and what the values were before and after (app/audit.py, app/db/audit.py).
Gated by `audit:view` -- the same permission as the security feed
(routers/security.py) -- so "can investigate" stays separate from "can
administer". Read-only by design: nothing here (or anywhere) edits or
deletes a row.

A report's own manager reads that report's slice of this through
GET /reports/{id}/changelog instead, which needs only manage access on
that one report.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import audit, db
from ..auth import ensure_org_scope, require_permission
from ..models import AuditPage
from ..rbac import AuthContext

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


def _as_utc_iso(value: str | None, name: str) -> str | None:
    """Validate and normalize a caller's timestamp to the exact string form
    stored in the table, so the comparison in SQL is a plain string one.
    A timestamp with no zone is taken as UTC."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"`{name}` must be an ISO 8601 timestamp") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


@router.get("", summary="Search the change audit trail, newest first", response_model=AuditPage)
def list_audit_events(
    entity_type: str | None = Query(None, description="e.g. report, user, role, ldap_config"),
    entity_id: str | None = Query(None, description="One specific thing's history"),
    action: str | None = Query(None, description="An exact action ('report.file_replace') or a prefix ('report')"),
    actor: str | None = Query(None, description="Substring of the username who made the change"),
    q: str | None = Query(None, description="Substring of the summary, the entity's name, or its id"),
    since: str | None = Query(None, description="ISO 8601; only events at or after this instant"),
    until: str | None = Query(None, description="ISO 8601; only events at or before this instant"),
    org_id: str | None = Query(None, description="Superusers may omit this to search every organization"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    context: AuthContext = Depends(require_permission("audit:view")),
) -> AuditPage:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        # No org to scope to must not fall through to "everything".
        if context.org_id is None:
            return AuditPage(items=[], total=0, limit=limit, offset=offset)
        org_id = context.org_id

    with db.SessionLocal() as session:
        items, total = audit.list_events(
            session,
            org_id=org_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            q=q,
            since=_as_utc_iso(since, "since"),
            until=_as_utc_iso(until, "until"),
            limit=limit,
            offset=offset,
        )
    return AuditPage(items=items, total=total, limit=limit, offset=offset)
