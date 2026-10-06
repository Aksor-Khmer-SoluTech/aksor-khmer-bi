"""JDBC drivers -- the vendor .jar files a JDBC connection can run on, for
engines the server has no built-in driver for (see app/jdbc.py and
app/jdbc_drivers.py for why a .jar is handled with care).

Uploading, downloading and deleting need `driver:manage`: a driver is code the
`jdbc-worker` service executes, so this is a deploy-level permission, narrower
than `connection:manage`. Listing the drivers and engines needs either, so a
connection author can pick a driver without being able to add one.
Scoped to the caller's own organization unless the caller is a superuser, the
same model as routers/connections.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit, db, jdbc, jdbc_drivers
from ..auth import ensure_org_scope, get_current_user, require_permission
from ..models import JdbcDriverOut, JdbcEngineOut
from ..rbac import ROOT_ORG_ID, AuthContext

router = APIRouter(prefix="/api/v1/jdbc", tags=["jdbc"])

_manage = require_permission("driver:manage")


def _require_view(context: AuthContext = Depends(get_current_user)) -> AuthContext:
    if context.has_permission("driver:manage") or context.has_permission("connection:manage"):
        return context
    raise HTTPException(status_code=403, detail="Missing required permission: driver:manage or connection:manage")


def _out(row: db.JdbcDriver, used_by: list[str]) -> JdbcDriverOut:
    return JdbcDriverOut(
        id=row.id, org_id=row.org_id, name=row.name, engine=row.engine, driver_class=row.driver_class,
        filename=row.filename, sha256=row.sha256, size_bytes=row.size_bytes, used_by=used_by, created_at=row.created_at,
    )


def _get_scoped(session, driver_id: str, context: AuthContext) -> db.JdbcDriver:
    row = session.get(db.JdbcDriver, driver_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Driver not found")
    ensure_org_scope(context, row.org_id)
    return row


@router.get("/engines", summary="The database engines a JDBC connection can use", response_model=list[JdbcEngineOut])
def list_engines(_: AuthContext = Depends(_require_view)) -> list[dict]:
    return jdbc.engine_catalog()


@router.get("/drivers", summary="List uploaded JDBC drivers", response_model=list[JdbcDriverOut])
def list_drivers(
    org_id: str | None = Query(None, description="Superusers may omit this to list every organization's drivers"),
    context: AuthContext = Depends(_require_view),
) -> list[JdbcDriverOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id
    with db.SessionLocal() as session:
        query = select(db.JdbcDriver).order_by(db.JdbcDriver.name)
        if org_id is not None:
            query = query.where(db.JdbcDriver.org_id == org_id)
        return [_out(row, jdbc_drivers.used_by(session, row.id)) for row in session.scalars(query)]


@router.post("/drivers", summary="Upload a JDBC driver (.jar)", response_model=JdbcDriverOut)
def upload_driver(
    request: Request,
    name: str = Form(..., description="What people pick it by, e.g. Oracle 23 (ojdbc11)"),
    engine: str = Form(...),
    driver_class: str | None = Form(None, description="Defaults to the engine's usual driver class"),
    org_id: str | None = Form(None),
    file: UploadFile = File(..., description="The vendor's JDBC driver .jar"),
    context: AuthContext = Depends(_manage),
) -> JdbcDriverOut:
    org = org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org)
    try:
        name, engine, driver_class = jdbc_drivers.validate_meta(name, engine, driver_class)
    except jdbc_drivers.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db.SessionLocal() as session:
        if session.get(db.Organization, org) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        row = db.JdbcDriver(
            org_id=org, name=name, engine=engine, driver_class=driver_class,
            filename=(file.filename or "driver.jar")[:200], sha256="", size_bytes=0,
            created_at=datetime.now(timezone.utc).isoformat(),
            created_by=context.user.id if context.user else None,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=f"A driver named {name!r} already exists in this organization") from exc
        try:
            row.sha256, row.size_bytes = jdbc_drivers.save_upload(row.id, file.file, driver_class)
        except jdbc_drivers.DataConfigError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            session.commit()
        except Exception:
            session.rollback()
            jdbc_drivers.remove_file(row.id)
            raise
        audit.record(
            audit.Actor.of(context, request), "jdbc_driver.upload", "jdbc_driver", row.id,
            label=row.name, org_id=row.org_id,
            summary=f"Uploaded JDBC driver {row.name} ({row.engine}, {row.driver_class})",
            details={"filename": row.filename, "sha256": row.sha256, "size_bytes": row.size_bytes},
        )
        return _out(row, [])


@router.get("/drivers/{driver_id}/download", summary="Download an uploaded driver's .jar")
def download_driver(driver_id: str, context: AuthContext = Depends(_manage)) -> FileResponse:
    with db.SessionLocal() as session:
        row = _get_scoped(session, driver_id, context)
        filename, path = row.filename, jdbc_drivers.path_for(row.id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="The driver's file is missing from the server")
    return FileResponse(path, media_type="application/java-archive", filename=filename)


@router.delete("/drivers/{driver_id}", status_code=204, summary="Delete a driver no connection uses")
def delete_driver(driver_id: str, request: Request, context: AuthContext = Depends(_manage)) -> None:
    with db.SessionLocal() as session:
        row = _get_scoped(session, driver_id, context)
        used = jdbc_drivers.used_by(session, row.id)
        if used:
            raise HTTPException(
                status_code=409,
                detail=f"{row.name!r} is still used by {', '.join(used[:5])} -- point those connections at another driver first",
            )
        name, org_id = row.name, row.org_id
        session.delete(row)
        session.commit()
    jdbc_drivers.remove_file(driver_id)
    audit.record(
        audit.Actor.of(context, request), "jdbc_driver.delete", "jdbc_driver", driver_id,
        label=name, org_id=org_id, summary=f"Deleted JDBC driver {name}",
    )
