"""What the signed-in person has been doing -- the data behind the portal's Home page.

Read from the audit trail's `report.run` / `report.run_failed` rows (routers/reports.py writes one per run), so
it counts runs, not rendered parts, and knows how many parameters were chosen. It only ever returns the caller's
own rows: there is no way to ask for someone else's, and it needs no permission beyond being signed in, since
it reveals nothing the person didn't do themselves. It starts from when run auditing began -- earlier runs aren't
in it.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select

from .. import db
from ..auth import get_current_user
from ..models import MyDashboard, MyDay, MyRun, MyTopReport
from ..rbac import AuthContext

router = APIRouter(prefix="/api/v1/me", tags=["me"])

_RECENT = 8
_TOP = 5


@router.get("/dashboard", summary="The signed-in user's own recent report activity", response_model=MyDashboard)
def my_dashboard(context: AuthContext = Depends(get_current_user)) -> MyDashboard:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30)).isoformat()
    week = (now - timedelta(days=7)).isoformat()

    mine = db.AuditEvent.actor_user_id == context.user.id if context.user else db.AuditEvent.actor_username == context.username
    with db.SessionLocal() as session:
        rows = (
            session.execute(
                select(db.AuditEvent)
                .where(mine, db.AuditEvent.action.in_(("report.run", "report.run_failed")), db.AuditEvent.created_at >= since)
                .order_by(db.AuditEvent.created_at.desc())
                .limit(2000)
            )
            .scalars()
            .all()
        )

    names: dict[str, str | None] = {}
    runs_by_report: Counter[str] = Counter()
    recent: list[MyRun] = []
    for row in rows:
        names.setdefault(row.entity_id, row.entity_label)
        if row.action == "report.run":
            runs_by_report[row.entity_id] += 1
        if len(recent) < _RECENT:
            details = row.details or {}
            recent.append(
                MyRun(
                    report_id=row.entity_id,
                    name=row.entity_label,
                    at=row.created_at,
                    via=details.get("via"),
                    format=details.get("format"),
                    parameters_selected=details.get("parameters_selected"),
                    ok=row.action == "report.run",
                    reason=None if row.action == "report.run" else details.get("reason"),
                )
            )

    succeeded = [r for r in rows if r.action == "report.run"]
    ok_by_day: Counter[str] = Counter(r.created_at[:10] for r in succeeded)
    failed_by_day: Counter[str] = Counter(r.created_at[:10] for r in rows if r.action != "report.run")
    days = [(now - timedelta(days=offset)).date().isoformat() for offset in range(29, -1, -1)]
    return MyDashboard(
        since=since,
        runs_7d=sum(1 for r in succeeded if r.created_at >= week),
        runs_30d=len(succeeded),
        failed_30d=len(rows) - len(succeeded),
        last_run_at=rows[0].created_at if rows else None,
        recent=recent,
        daily=[MyDay(date=d, runs=ok_by_day[d], failed=failed_by_day[d]) for d in days],
        top_reports=[MyTopReport(report_id=rid, name=names.get(rid), runs=n) for rid, n in runs_by_report.most_common(_TOP)],
    )
