"""Dashboards -- see app/dashboards.py. Anyone signed in lists and opens the dashboards they own or that are shared
with one of their roles; making one needs `analyze:use`; only its owner changes or shares it. A dashboard the caller
may not see is a 404."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from .. import analyze, audit, dashboards, db
from ..auth import ensure_org_scope, get_current_user, require_permission
from ..models import DashboardCreate, DashboardOut, DashboardSharing, DashboardSummary, DashboardUpdate, TileRun
from ..rbac import ROOT_ORG_ID, AuthContext
from ..report_data import DataConfigError, DataSourceError, ParameterError

router = APIRouter(prefix="/api/v1/dashboards", tags=["dashboards"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _org(context: AuthContext, org_id: str | None = None) -> str:
    org = org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org)
    return org


def _owner_name(session, user_id: str) -> str:
    user = session.get(db.User, user_id)
    return (user.display_name or user.username) if user else "—"


def _visible(session, context: AuthContext, dashboard_id: str) -> db.Dashboard:
    row = session.get(db.Dashboard, dashboard_id)
    if row is None or not dashboards.can_view(session, context, row):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return row


def _editable(session, context: AuthContext, dashboard_id: str) -> db.Dashboard:
    row = _visible(session, context, dashboard_id)
    if not dashboards.can_edit(context, row):
        raise HTTPException(status_code=403, detail="Only its owner can change this dashboard")
    return row


def _out(session, context: AuthContext, row: db.Dashboard, with_filters: bool = True) -> DashboardOut:
    return DashboardOut(
        id=row.id, org_id=row.org_id, title=row.title, description=row.description, tiles=row.tiles or [],
        filters=row.filters or {}, shared_role_ids=row.shared_role_ids or [], owner=_owner_name(session, row.owner_id),
        can_edit=dashboards.can_edit(context, row),
        filter_bar=dashboards.filter_bar(session, context, row) if with_filters else [],
        created_at=row.created_at, updated_at=row.updated_at,
    )


@router.get("", summary="The dashboards you own or that are shared with you", response_model=list[DashboardSummary])
def list_dashboards(context: AuthContext = Depends(get_current_user)) -> list[DashboardSummary]:
    with db.SessionLocal() as session:
        mine = context.user.id if context.user else None
        return [
            DashboardSummary(
                id=r.id, title=r.title, description=r.description, tile_count=len(r.tiles or []),
                owner=_owner_name(session, r.owner_id), mine=r.owner_id == mine, shared=bool(r.shared_role_ids),
                updated_at=r.updated_at,
            )
            for r in dashboards.visible(session, context, _org(context))
        ]


@router.post("", summary="Make a dashboard (add tiles from Analyze)", response_model=DashboardOut)
def create_dashboard(body: DashboardCreate, request: Request, context: AuthContext = Depends(require_permission("analyze:use"))) -> DashboardOut:
    if context.user is None:
        raise HTTPException(status_code=400, detail="A dashboard needs your own account, not the break-glass sign-in")
    with db.SessionLocal() as session:
        now = _now()
        row = db.Dashboard(org_id=_org(context, body.org_id), owner_id=context.user.id, title=body.title.strip(),
                           description=(body.description or "").strip() or None, tiles=[], filters={}, shared_role_ids=[],
                           created_at=now, updated_at=now)
        session.add(row)
        session.commit()
        audit.record(audit.Actor.of(context, request), "dashboard.create", "dashboard", row.id, label=row.title, org_id=row.org_id,
                     summary=f"Created dashboard {row.title}")
        return _out(session, context, row)


@router.get("/{dashboard_id}", summary="One dashboard, with its shared filters narrowed to your values", response_model=DashboardOut)
def get_dashboard(dashboard_id: str, context: AuthContext = Depends(get_current_user)) -> DashboardOut:
    with db.SessionLocal() as session:
        return _out(session, context, _visible(session, context, dashboard_id))


@router.put("/{dashboard_id}", summary="Change a dashboard's title, tiles and shared filters (its owner)", response_model=DashboardOut)
def update_dashboard(dashboard_id: str, body: DashboardUpdate, request: Request, context: AuthContext = Depends(get_current_user)) -> DashboardOut:
    with db.SessionLocal() as session:
        row = _editable(session, context, dashboard_id)
        try:
            tiles = dashboards.check_tiles(session, context, row.org_id, [t.model_dump() for t in body.tiles])
            filters = dashboards.check_filters(body.filters)
        except DataConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        before = {"title": row.title, "tiles": [t["id"] for t in row.tiles or []]}
        row.title, row.description = body.title.strip(), (body.description or "").strip() or None
        row.tiles, row.filters, row.updated_at = tiles, filters, _now()
        session.commit()
        if before != {"title": row.title, "tiles": [t["id"] for t in tiles]}:
            audit.record(audit.Actor.of(context, request), "dashboard.update", "dashboard", row.id, label=row.title, org_id=row.org_id,
                         summary=f"Updated dashboard {row.title} ({len(tiles)} tile{'s' if len(tiles) != 1 else ''})")
        return _out(session, context, row)


@router.put("/{dashboard_id}/sharing", summary="Share a dashboard with roles (its owner)", response_model=DashboardOut)
def share_dashboard(dashboard_id: str, body: DashboardSharing, request: Request, context: AuthContext = Depends(get_current_user)) -> DashboardOut:
    """Viewers see each tile with their own access: a restricted dataset still only gives them their values."""
    with db.SessionLocal() as session:
        row = _editable(session, context, dashboard_id)
        names = []
        for role_id in body.role_ids:
            role = session.get(db.Role, role_id)
            if role is None or role.org_id not in (row.org_id, None):
                raise HTTPException(status_code=400, detail="Share it with roles of the dashboard's own organization")
            names.append(role.name)
        before = sorted(row.shared_role_ids or [])
        row.shared_role_ids, row.updated_at = sorted(set(body.role_ids)), _now()
        session.commit()
        if before != row.shared_role_ids:
            audit.record(audit.Actor.of(context, request), "dashboard.share", "dashboard", row.id, label=row.title, org_id=row.org_id,
                         summary=f"Shared dashboard {row.title} with {', '.join(sorted(names))}" if names else f"Made dashboard {row.title} private",
                         changes=[{"field": "shared_role_ids", "before": before, "after": row.shared_role_ids}])
        return _out(session, context, row)


@router.delete("/{dashboard_id}", status_code=204, summary="Delete a dashboard (its owner)")
def delete_dashboard(dashboard_id: str, request: Request, context: AuthContext = Depends(get_current_user)) -> None:
    with db.SessionLocal() as session:
        row = _editable(session, context, dashboard_id)
        title, org_id = row.title, row.org_id
        session.delete(row)
        session.commit()
    audit.record(audit.Actor.of(context, request), "dashboard.delete", "dashboard", dashboard_id, label=title, org_id=org_id,
                 summary=f"Deleted dashboard {title}")


@router.post("/{dashboard_id}/tiles/{tile_id}/run", summary="One tile's data, with your access and the page's filters")
def run_tile(dashboard_id: str, tile_id: str, body: TileRun, context: AuthContext = Depends(get_current_user)) -> dict:
    with db.SessionLocal() as session:
        row = _visible(session, context, dashboard_id)
        try:
            return dashboards.run_tile(session, context, row, tile_id, body.filters)
        except LookupError:
            raise HTTPException(status_code=404, detail="Tile not found") from None
        except analyze.AnalyzeDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ParameterError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        except DataConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DataSourceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
