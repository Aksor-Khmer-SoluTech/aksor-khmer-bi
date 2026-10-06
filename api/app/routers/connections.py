"""Connections -- reusable base URLs (with their headers and authentication)
that reports fetch their data and choice lists through. See
app/connections.py for what a connection is and how a report uses one.

Scoped to the caller's own organization unless the caller is a superuser, the
same model as routers/clients.py. Writing needs `connection:manage` -- narrower
than `report:manage`, because a connection decides where the server sends
requests and which credential it attaches, for every report that uses it.
Naming a Secret in that credential is a `connection:manage` action; creating,
rotating or revoking the Secret itself needs `secret:manage` (routers/secrets.py).
Reading the list needs `connection:manage` or `report:manage`: a report author
has to see which connections exist to pick one, but the list carries no
header values.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit, connections, db, jdbc, jdbc_drivers, secrets
from ..auth import ensure_org_scope, get_current_user, require_permission
from ..models import (
    ConnectionCreate,
    ConnectionOut,
    ConnectionReportRef,
    ConnectionSummary,
    ConnectionTest,
    ConnectionTestResult,
    ConnectionUpdate,
    JdbcConnectionConfig,
    RestConnectionConfig,
)
from ..rbac import ROOT_ORG_ID, AuthContext

router = APIRouter(prefix="/api/v1/connections", tags=["connections"])

_manage = require_permission("connection:manage")


def _require_view(context: AuthContext = Depends(get_current_user)) -> AuthContext:
    if context.has_permission("connection:manage") or context.has_permission("report:manage"):
        return context
    raise HTTPException(status_code=403, detail="Missing required permission: connection:manage or report:manage")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_scoped(session, connection_id: str, context: AuthContext) -> db.DataConnection:
    row = session.get(db.DataConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    ensure_org_scope(context, row.org_id)
    return row


def _location(row: db.DataConnection) -> str:
    """Where a connection points, for lists and the audit trail: a REST base URL or a JDBC URL (neither holds a credential)."""
    config = row.config or {}
    return jdbc.display_url(config) if row.kind == "jdbc" else config.get("base_url", "")


def _summary(row: db.DataConnection, report_count: int) -> ConnectionSummary:
    config = row.config or {}
    auth = config.get("auth")
    secret_name = connections.secret_names_in_use(auth)
    return ConnectionSummary(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        kind=row.kind,
        description=row.description,
        base_url=_location(row),
        engine=config.get("engine") if row.kind == "jdbc" else None,
        auth_type=(auth or {}).get("type", "none"),
        credential="none" if not auth else "secret" if secret_name else "env",
        secret_name=secret_name,
        header_names=sorted((config.get("headers") or {}).keys(), key=str.lower),
        report_count=report_count,
        updated_at=row.updated_at,
    )


def _out(row: db.DataConnection, reports: list[dict]) -> ConnectionOut:
    return ConnectionOut(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        kind=row.kind,
        description=row.description,
        config=JdbcConnectionConfig(**row.config) if row.kind == "jdbc" else RestConnectionConfig(**row.config),
        reports=[ConnectionReportRef(**r) for r in reports],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _audit_fields(row: db.DataConnection) -> dict:
    return {"description": row.description, "config": row.config}


@router.post("", summary="Create a connection", response_model=ConnectionOut)
def create_connection(body: ConnectionCreate, request: Request, context: AuthContext = Depends(_manage)) -> ConnectionOut:
    org_id = body.org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org_id)
    try:
        name = connections.validate_name(body.name)
        config = connections.validate_config(
            body.kind, body.config.model_dump(), secrets.active_names_for_org(org_id), jdbc_drivers.engines_by_id(org_id)
        )
    except connections.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = _now()
    with db.SessionLocal() as session:
        if session.get(db.Organization, org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        row = db.DataConnection(
            org_id=org_id,
            name=name,
            kind=body.kind,
            description=(body.description or "").strip() or None,
            config=config,
            created_at=now,
            updated_at=now,
            created_by=context.user.id if context.user else None,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=f"A connection named {name!r} already exists in this organization") from exc
        audit.record(
            audit.Actor.of(context, request), "connection.create", "connection", row.id,
            label=row.name, org_id=row.org_id, summary=f"Created connection {row.name} ({_location(row)})",
            details={"kind": row.kind, "location": _location(row), "auth": (config["auth"] or {}).get("type", "none")},
        )
        return _out(row, [])


@router.post(
    "/test",
    summary="Try a database connection's settings without saving them",
    response_model=ConnectionTestResult,
)
def test_connection(body: ConnectionTest, request: Request, context: AuthContext = Depends(_manage)) -> ConnectionTestResult:
    """Logs in with the settings given -- the password is the named Secret's, resolved on
    the server -- and runs the engine's trivial statement. Nothing is saved. The answer says
    only whether it worked and, if not, a message that is safe to show: the driver's own
    error (which can name hosts and users) goes to the server log."""
    org_id = body.org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org_id)
    try:
        config = connections.validate_config(
            "jdbc", body.config.model_dump(), secrets.active_names_for_org(org_id), jdbc_drivers.engines_by_id(org_id)
        )
    except connections.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    started = time.monotonic()
    try:
        jdbc.check_login(connections.resolve_jdbc(config, org_id, where="Connection test"))
        result = ConnectionTestResult(ok=True, message="Connected", elapsed_ms=int((time.monotonic() - started) * 1000))
    except connections.DataSourceError as exc:
        # The driver's own message (which can name hosts and users) stays in the API log; point the admin to it.
        hint = "" if isinstance(exc, jdbc.WorkerNotConfigured) else " (the driver's own message is in the API log)"
        result = ConnectionTestResult(ok=False, message=f"{exc}{hint}")
    audit.record(
        audit.Actor.of(context, request), "connection.test", "connection", "test",
        label=f"{config['engine']} {config['host']}:{config['port']}", org_id=org_id,
        summary=f"Tested a {config['engine']} connection to {config['host']}:{config['port']}: {'connected' if result.ok else 'failed'}",
    )
    return result


@router.get("", summary="List connections visible to the caller", response_model=list[ConnectionSummary])
def list_connections(
    org_id: str | None = Query(None, description="Superusers may omit this to list every organization's connections"),
    context: AuthContext = Depends(_require_view),
) -> list[ConnectionSummary]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    with db.SessionLocal() as session:
        query = select(db.DataConnection).order_by(db.DataConnection.name)
        if org_id is not None:
            query = query.where(db.DataConnection.org_id == org_id)
        rows = session.scalars(query).all()
        usage = {org: connections.reports_using(session, org) for org in {row.org_id for row in rows}}
        return [_summary(row, len(usage[row.org_id].get(row.name, []))) for row in rows]


@router.get("/{connection_id}", summary="Get one connection, with its headers and the reports using it", response_model=ConnectionOut)
def get_connection(connection_id: str, context: AuthContext = Depends(_manage)) -> ConnectionOut:
    with db.SessionLocal() as session:
        row = _get_scoped(session, connection_id, context)
        return _out(row, connections.reports_using(session, row.org_id).get(row.name, []))


@router.put("/{connection_id}", summary="Replace a connection's description and settings", response_model=ConnectionOut)
def update_connection(
    connection_id: str, body: ConnectionUpdate, request: Request, context: AuthContext = Depends(_manage)
) -> ConnectionOut:
    """Takes effect for every report using it on their next run -- which is the
    point -- so the before/after of what changed is what the audit trail keeps."""
    with db.SessionLocal() as session:
        row = _get_scoped(session, connection_id, context)
        try:
            config = connections.validate_config(
                row.kind, body.config.model_dump(), secrets.active_names_for_org(row.org_id),
                jdbc_drivers.engines_by_id(row.org_id),
            )
        except connections.DataConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        before = _audit_fields(row)
        row.description = (body.description or "").strip() or None
        row.config = config
        row.updated_at = _now()
        after = _audit_fields(row)
        changes = audit.diff(before, after, ["description", "config"])
        session.commit()
        if changes:
            used_by = connections.reports_using(session, row.org_id).get(row.name, [])
            audit.record(
                audit.Actor.of(context, request), "connection.update", "connection", row.id,
                label=row.name, org_id=row.org_id,
                summary=f"Updated connection {row.name}" + (f" (used by {len(used_by)} report{'s' if len(used_by) != 1 else ''})" if used_by else ""),
                changes=changes,
            )
        return _out(row, connections.reports_using(session, row.org_id).get(row.name, []))


@router.delete("/{connection_id}", status_code=204, summary="Delete a connection nothing uses")
def delete_connection(connection_id: str, request: Request, context: AuthContext = Depends(_manage)) -> None:
    """Refused while a report still goes through it: deleting it would break
    every one of those runs, so they have to be pointed elsewhere first."""
    with db.SessionLocal() as session:
        row = _get_scoped(session, connection_id, context)
        used_by = connections.reports_using(session, row.org_id).get(row.name, [])
        if used_by:
            names = ", ".join(r["name"] for r in used_by[:5]) + (f" and {len(used_by) - 5} more" if len(used_by) > 5 else "")
            raise HTTPException(
                status_code=409,
                detail=f"{row.name!r} is still used by {len(used_by)} report{'s' if len(used_by) != 1 else ''} ({names}) -- point them at another connection first",
            )
        name, org_id, base_url = row.name, row.org_id, _location(row)
        session.delete(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "connection.delete", "connection", connection_id,
            label=name, org_id=org_id, summary=f"Deleted connection {name} ({base_url})",
        )
