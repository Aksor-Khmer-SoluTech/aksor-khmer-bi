"""Best-effort per-render telemetry writer -- see app/db/render_events.py
for the table shape and why it exists. A write failure here must never
turn a successful render into a 500 or mask a real rendering error, so
this is always called from inside the exact success/failure branches
routers/reports.py's `_render_one` already has, and any exception raised
while writing is caught and logged, never propagated.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import db

_log = logging.getLogger("aksor_khmer_bi.render_log")


def record_render_event(
    report_id: str,
    org_id: str | None,
    fmt: str,
    backend: str | None,
    status: str,
    duration_ms: int | None,
    triggered_by: str,
    user_id: str | None,
) -> None:
    try:
        with db.SessionLocal() as session:
            session.add(
                db.RenderEvent(
                    report_id=report_id,
                    org_id=org_id,
                    format=fmt,
                    backend=backend,
                    status=status,
                    duration_ms=duration_ms,
                    triggered_by=triggered_by,
                    user_id=user_id,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            session.commit()
    except Exception:
        _log.exception("Failed to record render event for report_id=%r -- the render itself was not affected", report_id)
