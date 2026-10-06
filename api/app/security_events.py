"""Best-effort access-denied event writer -- see app/db/security_events.py
for the table shape. Same never-block posture as app/render_log.py: a
write failure here must never interfere with the 403 it sits alongside.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import db

_log = logging.getLogger("aksor_khmer_bi.security_events")


def record_access_denied(
    username: str,
    org_id: str | None,
    user_id: str | None,
    permission_code: str,
    resource: str | None,
    ip_address: str | None,
    reason: str,
) -> None:
    try:
        with db.SessionLocal() as session:
            session.add(
                db.AccessDeniedEvent(
                    org_id=org_id,
                    user_id=user_id,
                    username=username,
                    permission_code=permission_code,
                    resource=resource,
                    ip_address=ip_address,
                    reason=reason,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            session.commit()
    except Exception:
        _log.exception("Failed to record access-denied event for username=%r permission=%r", username, permission_code)
