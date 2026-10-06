"""Cross-user security visibility for admins: merges login failures
(app/db/auth_events.py's AuthEvent) and access-denied events
(app/db/security_events.py's AccessDeniedEvent) into one chronological
feed. Gated by `audit:view` -- deliberately narrower than `user:manage`,
so granting "can see security activity" doesn't also grant "can create/
deactivate users." Backs the admin dashboard's security panel; see
specs/admin_dashboard_design.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from .. import db
from ..auth import ensure_org_scope, require_permission
from ..models import SecurityActivityItem
from ..rbac import AuthContext

router = APIRouter(prefix="/api/v1/security", tags=["security"])

# A login_failed row is flagged "unusual" if it's one of at least this
# many failures for the same username within this trailing window --
# visibility only (see the route's own docstring): nothing here
# throttles or locks out a login because of the flag.
_UNUSUAL_WINDOW = timedelta(minutes=15)
_UNUSUAL_THRESHOLD = 3


@router.get(
    "/activity",
    summary="Recent failed logins and access-denied events, merged and sorted",
    response_model=list[SecurityActivityItem],
)
def get_security_activity(
    since_hours: int = Query(24, ge=1, le=24 * 30, description="How far back to look, in hours"),
    limit: int = Query(100, ge=1, le=500),
    org_id: str | None = Query(None, description="Superusers may omit this to see every org's activity"),
    context: AuthContext = Depends(require_permission("audit:view")),
) -> list[SecurityActivityItem]:
    """The `unusual` flag is computed here, over this page's own rows,
    not stored anywhere -- a row is unusual if it's one of >= _UNUSUAL_THRESHOLD
    login_failed events for the same username within a trailing
    _UNUSUAL_WINDOW. This is a read-only signal for a human reviewing
    the dashboard; it never blocks a login or triggers a lockout itself,
    so it can't become a denial-of-service vector (e.g. someone
    deliberately failing logins as a target user to flag/lock them out).
    """
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    with db.SessionLocal() as session:
        login_query = select(db.AuthEvent).where(db.AuthEvent.success.is_(False), db.AuthEvent.created_at >= since)
        if org_id is not None:
            # A failed login never resolved to a user, so AuthEvent.org_id
            # is null for every such row (see app/routers/auth.py's
            # _log_failure) -- org-scoping by strict equality would hide
            # *every* failed login from a non-superuser, since none of
            # them ever carry an org_id. Include the org-unknown rows too
            # (a failed attempt against an unresolved username could well
            # be targeting one of this org's own accounts) rather than
            # excluding this whole event kind for anyone but a superuser.
            login_query = login_query.where((db.AuthEvent.org_id == org_id) | (db.AuthEvent.org_id.is_(None)))
        failed_logins = session.execute(login_query).scalars().all()

        denied_query = select(db.AccessDeniedEvent).where(db.AccessDeniedEvent.created_at >= since)
        if org_id is not None:
            denied_query = denied_query.where(db.AccessDeniedEvent.org_id == org_id)
        denied = session.execute(denied_query).scalars().all()

    login_times: dict[str, list[datetime]] = {}
    for event in failed_logins:
        login_times.setdefault(event.username, []).append(datetime.fromisoformat(event.created_at))

    def _is_unusual(username: str, at: datetime) -> bool:
        nearby = [t for t in login_times.get(username, []) if abs((t - at)) <= _UNUSUAL_WINDOW]
        return len(nearby) >= _UNUSUAL_THRESHOLD

    items = [
        SecurityActivityItem(
            kind="login_failed",
            username=event.username,
            ip_address=event.ip_address,
            detail="Failed login attempt",
            created_at=event.created_at,
            unusual=_is_unusual(event.username, datetime.fromisoformat(event.created_at)),
        )
        for event in failed_logins
    ] + [
        SecurityActivityItem(
            kind="access_denied",
            username=event.username,
            ip_address=event.ip_address,
            detail=f"{event.permission_code} on {event.resource}" if event.resource else event.permission_code,
            created_at=event.created_at,
            unusual=False,
        )
        for event in denied
    ]
    items.sort(key=lambda item: item.created_at, reverse=True)
    return items[:limit]
