"""Datasets -- see app/datasets.py. Managing one needs dataset:manage; listing them (to build a report on one) is
open to report managers too, without the source's details."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit, connections, datasets, db, report_data, report_store, secrets
from ..auth import ensure_org_scope, get_current_user, require_permission
from ..models import (
    DatasetAccess,
    DatasetAccessMode,
    DatasetCreate,
    DatasetFromReport,
    DatasetGrantCreate,
    DatasetGrantOut,
    DatasetOptionsPreviewRequest,
    DatasetOut,
    DatasetPreview,
    DatasetPreviewRequest,
    DatasetSummary,
    DatasetWrite,
    OptionsPreview,
)
from ..rbac import ROOT_ORG_ID, AuthContext, has_report_access
from ..report_wizard import trim_sample

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])

_manage = require_permission("dataset:manage")
_PREVIEW_OPTIONS_SHOWN = 20


def _can_list(context: AuthContext = Depends(get_current_user)) -> AuthContext:
    if not (context.has_permission("dataset:manage") or context.has_permission("report:manage")):
        raise HTTPException(status_code=403, detail="You don't have permission to see datasets")
    return context


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _org_of(context: AuthContext, org_id: str | None) -> str:
    org = org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org)
    return org


def _check(org_id: str, body: DatasetWrite) -> tuple[list[dict], dict, list[dict], list[dict]]:
    """The dataset's settings, validated as a report's source and filters are -- a dataset can't be built on
    another dataset -- plus its fields and measures. Raises a 400 for the form."""
    if body.data_source.type == "dataset":
        raise HTTPException(status_code=400, detail="A dataset reads from a source -- a database, a REST API or sample data -- not from another dataset")
    try:
        parameters, source = report_data.validate_data_config(
            [p.model_dump() for p in body.parameters],
            body.data_source.model_dump(),
            connection_names=connections.names_for_org(org_id),
            secret_names=secrets.active_names_for_org(org_id),
            connection_kinds=connections.kinds_for_org(org_id),
            connection_routines=connections.routines_for_org(org_id),
        )
        fields = datasets.validate_fields([f.model_dump() for f in body.fields])
        measures = datasets.validate_measures([m.model_dump() for m in body.measures])
    except report_data.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return parameters, source, fields, measures


def _scoped(session, dataset_id: str, context: AuthContext) -> db.Dataset:
    row = session.get(db.Dataset, dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    ensure_org_scope(context, row.org_id)
    return row


def _out(session, row: db.Dataset) -> DatasetOut:
    return DatasetOut(**datasets.to_dict(row), reports=datasets.reports_using(session, row.org_id, row.name))


def _active_grants(session, dataset_id: str) -> list[db.DatasetAccessGrant]:
    from ..rbac import _not_expired_clause

    G = db.DatasetAccessGrant
    return list(session.scalars(
        select(G).where(G.dataset_id == dataset_id, G.is_active.is_(True), _not_expired_clause(G)).order_by(G.granted_at)
    ))


def _subject_name(session, subject_type: str, subject_id: str) -> str:
    row = session.get(db.User if subject_type == "user" else db.Role, subject_id)
    if row is None:
        return subject_id
    return (row.display_name or row.username) if subject_type == "user" else row.name


def _grant_out(session, g: db.DatasetAccessGrant) -> DatasetGrantOut:
    return DatasetGrantOut(
        id=g.id, subject_type=g.subject_type, subject_id=g.subject_id, subject_name=_subject_name(session, g.subject_type, g.subject_id),
        level=g.level, parameter_limits=g.parameter_limits, granted_at=g.granted_at, granted_by=g.granted_by,
        expires_at=g.expires_at, is_active=g.is_active,
    )


def _audit_fields(row: db.Dataset) -> dict:
    return {f: getattr(row, f) for f in ("title", "description", "parameters", "data_source", "fields", "measures")}


@router.get("", summary="List datasets (report managers too, to build a report on one)", response_model=list[DatasetSummary])
def list_datasets(org_id: str | None = Query(None), context: AuthContext = Depends(_can_list)) -> list[DatasetSummary]:
    with db.SessionLocal() as session:
        query = select(db.Dataset).order_by(db.Dataset.title)
        if org_id or not context.is_superuser:
            query = query.where(db.Dataset.org_id == _org_of(context, org_id))
        out = []
        for row in session.scalars(query):
            if not datasets.can_build(session, context, row):
                continue  # restricted, and the caller may not build on it: not theirs to pick
            source = row.data_source or {}
            out.append(DatasetSummary(
                id=row.id, org_id=row.org_id, name=row.name, title=row.title, description=row.description,
                source_type=source.get("type") or "rest", connection=source.get("connection"),
                parameter_count=len(row.parameters or []), field_count=len(row.fields or []),
                measure_count=len(row.measures or []), report_count=len(datasets.reports_using(session, row.org_id, row.name)),
                access_mode=row.access_mode or "open", grant_count=len(_active_grants(session, row.id)),
                updated_at=row.updated_at,
            ))
        return out


@router.post("", summary="Create a dataset", response_model=DatasetOut)
def create_dataset(body: DatasetCreate, request: Request, context: AuthContext = Depends(_manage)) -> DatasetOut:
    org_id = _org_of(context, body.org_id)
    try:
        name = datasets.validate_name(body.name)
    except report_data.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    parameters, source, fields, measures = _check(org_id, body)
    now = _now()
    with db.SessionLocal() as session:
        row = db.Dataset(
            org_id=org_id, name=name, title=body.title.strip(), description=(body.description or "").strip() or None,
            parameters=parameters, data_source=source, fields=fields, measures=measures,
            created_by=context.user.id if context.user else None, created_at=now, updated_at=now,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=f"A dataset named {name!r} already exists in this organization") from exc
        audit.record(
            audit.Actor.of(context, request), "dataset.create", "dataset", row.id, label=row.title, org_id=org_id,
            summary=f"Created dataset {row.title} ({len(fields)} fields, {len(measures)} measures)",
            details={"name": name, "source_type": source.get("type")},
        )
        return _out(session, row)


@router.post("/preview", summary="Run a dataset's source once -- saved or not -- and see its data, fields and measures", response_model=DatasetPreview)
def preview_dataset(body: DatasetPreviewRequest, context: AuthContext = Depends(_manage)) -> dict:
    """Makes the real query or request with the connection's credentials, in the caller's own organization; saves
    nothing. Answers with the data (lists cut short), every column found (merged with the fields already
    described, so labels survive a re-run), and each measure's value."""
    org_id = _org_of(context, body.org_id)
    if body.data_source.type == "dataset":
        raise HTTPException(status_code=400, detail="A dataset reads from a source, not from another dataset")
    defined = {p.name for p in body.parameters}
    added = [{"name": n, "label": n.replace("_", " ").capitalize(), "type": "text", "required": True}
             for n in report_data.source_parameter_names(body.data_source.model_dump()) if n not in defined]
    try:
        parameters, source = report_data.validate_data_config(
            [p.model_dump() for p in body.parameters] + added, body.data_source.model_dump(),
            connection_names=connections.names_for_org(org_id), secret_names=secrets.active_names_for_org(org_id),
            connection_kinds=connections.kinds_for_org(org_id),
            connection_routines=connections.routines_for_org(org_id),
        )
        fields = datasets.validate_fields([f.model_dump() for f in body.fields])
        measures = datasets.validate_measures([m.model_dump() for m in body.measures])
    except report_data.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    missing = [
        p["name"] for p in parameters
        if p.get("required", True) and not (body.values.get(p["name"]) or "").strip() and not p.get("default_value")
        and not p.get("options") and not p.get("options_source")
    ]
    if missing:
        return {"data": {}, "fields": fields, "measures": {}, "parameters": parameters, "missing": missing}
    try:
        definitions = report_data.resolve_parameter_definitions(parameters, materialize=lambda s: connections.materialize(s, org_id))
        values = report_data.resolve_run_parameters(definitions, {d["name"]: None for d in definitions}, body.values)
        started = time.monotonic()
        data = report_data.fetch_report_data(connections.materialize(source, org_id), values, {d["name"]: d.get("type") or "text" for d in parameters})
    except report_data.ParameterError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except report_data.DataSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    elapsed = int((time.monotonic() - started) * 1000)
    texts, numbers = datasets.compute_measures(measures, data) if measures else ({}, {})
    trimmed = trim_sample(data)
    return {
        "data": trimmed,
        "fields": datasets.detect_fields(data, fields),
        "measures": {k: {"text": texts[k], "value": numbers[k]} for k in texts},
        "parameters": parameters,
        "missing": [],
        "elapsed_ms": elapsed,
        "truncated": trimmed != data,
    }


@router.post("/preview-options", summary="Try a filter's REST-backed choice list, for a dataset's filters", response_model=OptionsPreview)
def preview_options(body: DatasetOptionsPreviewRequest, context: AuthContext = Depends(_manage)) -> dict:
    org_id = _org_of(context, body.org_id)
    try:
        source = report_data.validate_options_source(
            body.options_source.model_dump(), "this choice list", connections.names_for_org(org_id),
            secrets.active_names_for_org(org_id), connections.kinds_for_org(org_id),
        )
        options = report_data.fetch_parameter_options(connections.materialize(source, org_id))
    except report_data.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except report_data.DataSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"total": len(options), "options": options[:_PREVIEW_OPTIONS_SHOWN]}


@router.post("/from-report", summary="Make a dataset of a report's own data source and filters, and build the report on it", response_model=DatasetOut)
def dataset_from_report(body: DatasetFromReport, request: Request, context: AuthContext = Depends(_manage)) -> DatasetOut:
    """The way in for reports made before datasets: their source and filters become the dataset's, and the report
    is switched to it -- so it runs exactly as before, and the next report can share it."""
    try:
        report = report_store.get_report_raw(report_store.resolve_ref(body.report_id))
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found") from None
    org_id = report["org_id"] or ROOT_ORG_ID
    ensure_org_scope(context, org_id)
    with db.SessionLocal() as session:
        if not (context.is_superuser or has_report_access(session, context, report["report_id"], "manage")):
            raise HTTPException(status_code=404, detail="Report not found")
    source = report.get("data_source")
    if not source or source.get("type") == "dataset":
        raise HTTPException(status_code=400, detail="This report has no data source of its own to make a dataset of")
    created = create_dataset(
        DatasetCreate(org_id=org_id, name=body.name, title=body.title, parameters=report.get("parameters") or [], data_source=source),
        request, context,
    )
    report_store.update_data_config(report["report_id"], [], {"type": "dataset", "dataset": created.name})
    audit.record(
        audit.Actor.of(context, request), "report.data_config_update", "report", report["report_id"], label=report["name"],
        org_id=org_id, summary=f"Built on the new dataset {created.title}",
        changes=[{"field": "data_source", "before": source.get("type"), "after": f"dataset {created.name}"}],
    )
    with db.SessionLocal() as session:
        return _out(session, session.get(db.Dataset, created.id))


@router.get("/{dataset_id}", summary="One dataset, with the reports built on it", response_model=DatasetOut)
def get_dataset(dataset_id: str, context: AuthContext = Depends(_manage)) -> DatasetOut:
    with db.SessionLocal() as session:
        return _out(session, _scoped(session, dataset_id, context))


@router.put("/{dataset_id}", summary="Replace a dataset's settings (its name is fixed -- reports refer to it)", response_model=DatasetOut)
def update_dataset(dataset_id: str, body: DatasetWrite, request: Request, context: AuthContext = Depends(_manage)) -> DatasetOut:
    """Takes effect for every report built on it on their next run -- which is the point -- so the before/after is
    what the audit trail keeps."""
    with db.SessionLocal() as session:
        row = _scoped(session, dataset_id, context)
        parameters, source, fields, measures = _check(row.org_id, body)
        before = _audit_fields(row)
        row.title, row.description = body.title.strip(), (body.description or "").strip() or None
        row.parameters, row.data_source, row.fields, row.measures = parameters, source, fields, measures
        row.updated_at = _now()
        changes = audit.diff(before, _audit_fields(row), ["title", "description", "parameters", "data_source", "fields", "measures"])
        session.commit()
        if changes:
            used = datasets.reports_using(session, row.org_id, row.name)
            audit.record(
                audit.Actor.of(context, request), "dataset.update", "dataset", row.id, label=row.title, org_id=row.org_id,
                summary=f"Updated dataset {row.title}" + (f" (used by {len(used)} report{'s' if len(used) != 1 else ''})" if used else ""),
                changes=changes,
            )
        return _out(session, row)


@router.delete("/{dataset_id}", status_code=204, summary="Delete a dataset no report is built on")
def delete_dataset(dataset_id: str, request: Request, context: AuthContext = Depends(_manage)) -> None:
    with db.SessionLocal() as session:
        row = _scoped(session, dataset_id, context)
        used = datasets.reports_using(session, row.org_id, row.name)
        if used:
            names = ", ".join(r["name"] for r in used[:5]) + (f" and {len(used) - 5} more" if len(used) > 5 else "")
            raise HTTPException(status_code=409, detail=f"{len(used)} report{'s are' if len(used) != 1 else ' is'} built on it ({names}) -- move them to another source first")
        title, org_id = row.title, row.org_id
        for grant in session.scalars(select(db.DatasetAccessGrant).where(db.DatasetAccessGrant.dataset_id == row.id)):
            session.delete(grant)
        session.delete(row)
        session.commit()
    audit.record(audit.Actor.of(context, request), "dataset.delete", "dataset", dataset_id, label=title, org_id=org_id, summary=f"Deleted dataset {title}")


# --- access (row-level) -------------------------------------------------------------------------------------------


@router.get("/{dataset_id}/access", summary="Who may use a dataset, and with which filter values", response_model=DatasetAccess)
def get_access(dataset_id: str, context: AuthContext = Depends(_manage)) -> DatasetAccess:
    with db.SessionLocal() as session:
        row = _scoped(session, dataset_id, context)
        return DatasetAccess(mode=row.access_mode or "open", grants=[_grant_out(session, g) for g in _active_grants(session, row.id)])


@router.put("/{dataset_id}/access/mode", summary="Open a dataset to every report's runners, or restrict it to its grants", response_model=DatasetAccess)
def set_access_mode(dataset_id: str, body: DatasetAccessMode, request: Request, context: AuthContext = Depends(_manage)) -> DatasetAccess:
    with db.SessionLocal() as session:
        row = _scoped(session, dataset_id, context)
        before = row.access_mode or "open"
        if before != body.mode:
            row.access_mode = body.mode
            row.updated_at = _now()
            session.commit()
            grants = len(_active_grants(session, row.id))
            audit.record(
                audit.Actor.of(context, request), "dataset.access_mode", "dataset", row.id, label=row.title, org_id=row.org_id,
                summary=f"Restricted dataset {row.title} to its {grants} grant{'s' if grants != 1 else ''}" if body.mode == "restricted"
                else f"Opened dataset {row.title} to everyone who may run a report on it",
                changes=[{"field": "access_mode", "before": before, "after": body.mode}],
            )
        return get_access(dataset_id, context)


@router.post("/{dataset_id}/access", summary="Let a user or role use a dataset, optionally only with some filter values", response_model=DatasetGrantOut)
def grant_access(dataset_id: str, body: DatasetGrantCreate, request: Request, context: AuthContext = Depends(_manage)) -> DatasetGrantOut:
    with db.SessionLocal() as session:
        row = _scoped(session, dataset_id, context)
        subject = session.get(db.User if body.subject_type == "user" else db.Role, body.subject_id)
        if subject is None:
            raise HTTPException(status_code=404, detail="User not found" if body.subject_type == "user" else "Role not found")
        if subject.org_id != row.org_id:
            raise HTTPException(status_code=400, detail="That user or role belongs to another organization than the dataset")
        if body.expires_at is not None and body.expires_at <= _now():
            raise HTTPException(status_code=400, detail="The expiry is already in the past")
        try:
            limits = datasets.validate_limits(row.parameters or [], body.parameter_limits)
        except report_data.DataConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        grant = db.DatasetAccessGrant(
            dataset_id=row.id, subject_type=body.subject_type, subject_id=body.subject_id, level=body.level,
            parameter_limits=limits or None, granted_at=_now(), granted_by=context.user.id if context.user else None,
            expires_at=body.expires_at, is_active=True,
        )
        session.add(grant)
        session.commit()
        who = _subject_name(session, body.subject_type, body.subject_id)
        limited = "; ".join(f"{k}: {', '.join(v)}" for k, v in limits.items())
        audit.record(
            audit.Actor.of(context, request), "dataset.access_grant", "dataset", row.id, label=row.title, org_id=row.org_id,
            summary=f"Granted {'build & run' if body.level == 'build' else 'run'} on dataset {row.title} to {body.subject_type} {who}"
            + (f" ({limited})" if limited else "") + (f" until {body.expires_at}" if body.expires_at else ""),
            details={"grant_id": grant.id, "subject_type": grant.subject_type, "subject_id": grant.subject_id, "subject_name": who,
                     "level": grant.level, "parameter_limits": grant.parameter_limits, "expires_at": grant.expires_at},
        )
        return _grant_out(session, grant)


@router.delete("/{dataset_id}/access/{grant_id}", status_code=204, summary="Revoke a dataset grant")
def revoke_access(dataset_id: str, grant_id: str, request: Request, context: AuthContext = Depends(_manage)) -> None:
    with db.SessionLocal() as session:
        row = _scoped(session, dataset_id, context)
        grant = session.get(db.DatasetAccessGrant, grant_id)
        if grant is None or grant.dataset_id != row.id:
            raise HTTPException(status_code=404, detail="Grant not found")
        if not grant.is_active:
            return
        grant.is_active = False
        session.commit()
        who = _subject_name(session, grant.subject_type, grant.subject_id)
        audit.record(
            audit.Actor.of(context, request), "dataset.access_revoke", "dataset", row.id, label=row.title, org_id=row.org_id,
            summary=f"Revoked {grant.subject_type} {who}'s access to dataset {row.title}",
            details={"grant_id": grant.id, "subject_type": grant.subject_type, "subject_id": grant.subject_id, "subject_name": who},
        )
