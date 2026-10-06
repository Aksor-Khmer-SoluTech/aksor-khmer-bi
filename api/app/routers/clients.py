"""API client management -- who (as a machine) may run which reports without a login.

Scoped to the caller's own organization unless the caller is a superuser, the
same model as routers/roles.py and routers/users.py. Design and security notes:
specs/api_clients_design.md.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit, clients, db
from ..auth import ensure_org_scope, require_permission
from ..models import ClientCreate, ClientOut, ClientReportRef, ClientReportsUpdate, ClientUpdate, ClientWithSecret
from ..rbac import ROOT_ORG_ID, AuthContext

router = APIRouter(prefix="/api/v1", tags=["clients"])

_manage = require_permission("client:manage")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reports_of(session, client_pk: str) -> list[ClientReportRef]:
    rows = session.execute(
        select(db.ReportRow.report_id, db.ReportRow.name, db.ReportRow.code)
        .join(db.ApiClientReport, db.ApiClientReport.report_id == db.ReportRow.report_id)
        .where(db.ApiClientReport.client_pk == client_pk)
        .order_by(db.ReportRow.name)
    ).all()
    return [ClientReportRef(report_id=r.report_id, name=r.name, code=r.code) for r in rows]


def _to_out(session, row: db.ApiClient) -> ClientOut:
    return ClientOut(
        id=row.id,
        org_id=row.org_id,
        client_id=row.client_id,
        name=row.name,
        description=row.description,
        is_active=row.is_active,
        secret_prefix=row.secret_prefix,
        created_at=row.created_at,
        secret_rotated_at=row.secret_rotated_at,
        last_used_at=row.last_used_at,
        reports=_reports_of(session, row.id),
    )


def _get_scoped(session, client_pk: str, context: AuthContext) -> db.ApiClient:
    row = session.get(db.ApiClient, client_pk)
    if row is None:
        raise HTTPException(status_code=404, detail="Client not found")
    ensure_org_scope(context, row.org_id)
    return row


def _validated_report_ids(session, org_id: str, report_ids: list[str]) -> list[str]:
    """The ids, de-duplicated in order, once each is known to be a report of `org_id`."""
    wanted = list(dict.fromkeys(report_ids))
    if not wanted:
        return []
    found = {
        r.report_id: r.org_id
        for r in session.execute(
            select(db.ReportRow.report_id, db.ReportRow.org_id).where(db.ReportRow.report_id.in_(wanted))
        ).all()
    }
    missing = [rid for rid in wanted if rid not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown report(s): {missing}")
    foreign = [rid for rid in wanted if (found[rid] or ROOT_ORG_ID) != org_id]
    if foreign:
        raise HTTPException(status_code=400, detail=f"Report(s) belong to another organization: {foreign}")
    return wanted


def _grant(session, client_pk: str, report_ids: list[str], context: AuthContext) -> None:
    now = _now()
    granted_by = context.user.id if context.user else None
    for report_id in report_ids:
        session.add(db.ApiClientReport(client_pk=client_pk, report_id=report_id, granted_at=now, granted_by=granted_by))


@router.post("/clients", summary="Create an API client", response_model=ClientWithSecret)
def create_client(body: ClientCreate, request: Request, context: AuthContext = Depends(_manage)) -> ClientWithSecret:
    org_id = body.org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org_id)
    secret, prefix, secret_hash = clients.new_secret()
    with db.SessionLocal() as session:
        if session.get(db.Organization, org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        report_ids = _validated_report_ids(session, org_id, body.report_ids)
        row = db.ApiClient(
            org_id=org_id,
            client_id=body.client_id,
            name=body.name,
            description=body.description,
            secret_hash=secret_hash,
            secret_prefix=prefix,
            is_active=True,
            created_at=_now(),
            created_by=context.user.id if context.user else None,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="A client with this client ID already exists") from exc
        _grant(session, row.id, report_ids, context)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "client.create", "api_client", row.id,
            label=row.name, org_id=row.org_id, summary=f"Created API client {row.name} ({row.client_id})",
            details={"client_id": row.client_id, "report_ids": report_ids},
        )
        return ClientWithSecret(client=_to_out(session, row), secret=secret)


@router.get("/clients", summary="List API clients", response_model=list[ClientOut])
def list_clients(
    org_id: str | None = Query(None, description="Superusers may omit this to list every organization's clients"),
    context: AuthContext = Depends(_manage),
) -> list[ClientOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    with db.SessionLocal() as session:
        query = select(db.ApiClient).order_by(db.ApiClient.name)
        if org_id is not None:
            query = query.where(db.ApiClient.org_id == org_id)
        return [_to_out(session, row) for row in session.execute(query).scalars().all()]


@router.get("/clients/{client_pk}", summary="Get one API client", response_model=ClientOut)
def get_client(client_pk: str, context: AuthContext = Depends(_manage)) -> ClientOut:
    with db.SessionLocal() as session:
        return _to_out(session, _get_scoped(session, client_pk, context))


@router.patch("/clients/{client_pk}", summary="Rename, describe, enable or disable an API client", response_model=ClientOut)
def update_client(
    client_pk: str, body: ClientUpdate, request: Request, context: AuthContext = Depends(_manage)
) -> ClientOut:
    with db.SessionLocal() as session:
        row = _get_scoped(session, client_pk, context)
        fields = ("name", "description", "is_active")
        before = {f: getattr(row, f) for f in fields}
        for field in fields:
            new = getattr(body, field)
            # `description` may be cleared with an explicit null; the others can't be null.
            if field in body.model_fields_set and (new is not None or field == "description"):
                setattr(row, field, new)
        after = {f: getattr(row, f) for f in fields}
        changes = audit.diff(before, after, fields)
        if changes:
            session.commit()
            changed = {c["field"] for c in changes}
            if changed == {"is_active"}:
                action, verb = ("client.enable", "Enabled") if row.is_active else ("client.disable", "Disabled")
            else:
                action, verb = "client.update", "Updated"
            audit.record(
                audit.Actor.of(context, request), action, "api_client", row.id,
                label=row.name, org_id=row.org_id, summary=f"{verb} API client {row.name}", changes=changes,
            )
        return _to_out(session, row)


@router.put("/clients/{client_pk}/reports", summary="Replace the reports an API client may run", response_model=ClientOut)
def set_client_reports(
    client_pk: str, body: ClientReportsUpdate, request: Request, context: AuthContext = Depends(_manage)
) -> ClientOut:
    with db.SessionLocal() as session:
        row = _get_scoped(session, client_pk, context)
        report_ids = _validated_report_ids(session, row.org_id, body.report_ids)
        before = sorted(ref.report_id for ref in _reports_of(session, row.id))
        session.execute(db.ApiClientReport.__table__.delete().where(db.ApiClientReport.client_pk == row.id))
        _grant(session, row.id, report_ids, context)
        session.commit()
        if before != sorted(report_ids):
            audit.record(
                audit.Actor.of(context, request), "client.reports_update", "api_client", row.id,
                label=row.name, org_id=row.org_id,
                summary=f"Changed the reports API client {row.name} may run ({len(before)} → {len(report_ids)})",
                changes=audit.diff({"reports": before}, {"reports": sorted(report_ids)}, ["reports"]),
            )
        return _to_out(session, row)


@router.post("/clients/{client_pk}/rotate-secret", summary="Issue a new secret (the old one stops working at once)", response_model=ClientWithSecret)
def rotate_secret(client_pk: str, request: Request, context: AuthContext = Depends(_manage)) -> ClientWithSecret:
    secret, prefix, secret_hash = clients.new_secret()
    with db.SessionLocal() as session:
        row = _get_scoped(session, client_pk, context)
        row.secret_hash = secret_hash
        row.secret_prefix = prefix
        row.secret_rotated_at = _now()
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "client.rotate_secret", "api_client", row.id,
            label=row.name, org_id=row.org_id, summary=f"Rotated the secret of API client {row.name}",
        )
        return ClientWithSecret(client=_to_out(session, row), secret=secret)


@router.delete("/clients/{client_pk}", summary="Delete an API client and its grants", status_code=204)
def delete_client(client_pk: str, request: Request, context: AuthContext = Depends(_manage)) -> None:
    with db.SessionLocal() as session:
        row = _get_scoped(session, client_pk, context)
        name, client_id, org_id = row.name, row.client_id, row.org_id
        session.execute(db.ApiClientReport.__table__.delete().where(db.ApiClientReport.client_pk == row.id))
        session.delete(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "client.delete", "api_client", client_pk,
            label=name, org_id=org_id, summary=f"Deleted API client {name} ({client_id})",
        )
