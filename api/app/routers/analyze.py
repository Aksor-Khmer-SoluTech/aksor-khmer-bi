"""Analyze -- see app/analyze.py. Everything here needs `analyze:use`; a restricted dataset also needs one of its
grants, and only gives that grant's filter values. A dataset the caller may not analyze is a 404: whether it exists
isn't theirs to learn. Saved views are their owner's alone."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from .. import analyze, analyze_export, audit, datasets, db
from ..auth import ensure_org_scope, require_permission
from ..models import AnalysisOut, AnalysisWrite, AnalyzeDataset, ExportRequest, PivotRequest
from ..rbac import ROOT_ORG_ID, AuthContext
from ..report_data import DataConfigError, DataSourceError, ParameterError

router = APIRouter(prefix="/api/v1/analyze", tags=["analyze"])

_use = require_permission("analyze:use")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _org(context: AuthContext, org_id: str | None) -> str:
    org = org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org)
    return org


def _dataset(session, context: AuthContext, org_id: str, name: str) -> db.Dataset:
    row = datasets.row_by_name(session, org_id, name)
    if row is None or not analyze.can_use(session, context, row):
        raise HTTPException(status_code=404, detail="Dataset not found")
    return row


def _errors(exc: Exception) -> HTTPException:
    if isinstance(exc, analyze.AnalyzeDenied):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ParameterError):
        return HTTPException(status_code=exc.status, detail=str(exc))
    if isinstance(exc, DataConfigError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/datasets", summary="The datasets the caller may analyze", response_model=list[AnalyzeDataset])
def list_datasets(org_id: str | None = Query(None), context: AuthContext = Depends(_use)) -> list[AnalyzeDataset]:
    with db.SessionLocal() as session:
        return [
            AnalyzeDataset(
                name=r.name, title=r.title, description=r.description, access_mode=r.access_mode or "open",
                field_count=len([f for f in r.fields or [] if not f.get("hidden")]), measure_count=len(r.measures or []),
            )
            for r in analyze.usable(session, context, _org(context, org_id))
        ]


@router.get("/datasets/{name}", summary="One dataset, set up for Analyze: filters narrowed to the caller's values, fields, measures")
def dataset_form(name: str, org_id: str | None = Query(None), context: AuthContext = Depends(_use)) -> dict:
    with db.SessionLocal() as session:
        row = _dataset(session, context, _org(context, org_id), name)
        try:
            return analyze.form(session, context, row)
        except (analyze.AnalyzeDenied, DataSourceError) as exc:
            raise _errors(exc) from exc


@router.post("/pivot", summary="Pivot a dataset: rows x columns, each cell the values asked for, with totals")
def pivot(body: PivotRequest, context: AuthContext = Depends(_use)) -> dict:
    """The caller's filter values are checked against their access before anything is fetched -- the same order as a
    report run. The fetched data is kept a few minutes, so a new arrangement of the same data answers at once."""
    with db.SessionLocal() as session:
        row = _dataset(session, context, _org(context, body.org_id), body.dataset)
        try:
            return analyze.run(session, context, row, body.values, body.layout.model_dump())
        except (analyze.AnalyzeDenied, ParameterError, DataConfigError, DataSourceError) as exc:
            raise _errors(exc) from exc


@router.post("/export", summary="A pivot as a file: PDF, Word or Excel, Khmer included", response_class=Response)
def export(body: ExportRequest, request: Request, context: AuthContext = Depends(_use)) -> Response:
    """Data leaving the server, so it's in the audit log: which dataset, which filter values, which format."""
    with db.SessionLocal() as session:
        row = _dataset(session, context, _org(context, body.org_id), body.dataset)
        try:
            result = analyze.run(session, context, row, body.values, body.layout.model_dump())
            form = analyze.form(session, context, row)
        except (analyze.AnalyzeDenied, ParameterError, DataConfigError, DataSourceError) as exc:
            raise _errors(exc) from exc
        filters = []
        for p in form["parameters"]:
            value = result["values_used"].get(p["name"])
            if value in (None, ""):
                continue
            label = next((o.get("label") for o in p.get("options") or [] if o["value"] == value), None)
            filters.append({"label": p.get("label") or p["name"], "value": f"{label} ({value})" if label else value})
        title = (body.title or "").strip() or row.title
        meta = {"title": title, "dataset_title": row.title, "filters": filters, "who": context.username}
        if body.format == "pdf":
            content = analyze_export.to_pdf(result, meta, body.chart)
        elif body.format == "docx":
            content = analyze_export.to_docx(result, meta, body.chart)
        else:
            content = analyze_export.to_xlsx(result, meta, {m["key"]: m.get("format") for m in row.measures or []})
        dataset_name, org_id, dataset_id = row.name, row.org_id, row.id
    audit.record(
        audit.Actor.of(context, request), "analyze.export", "dataset", dataset_id, label=title, org_id=org_id,
        summary=f"Exported an analysis of {dataset_name} as {body.format.upper()} ({result['row_count']:,} rows)",
        details={"dataset": dataset_name, "values": result["values_used"], "layout": result["layout"], "format": body.format},
    )
    filename = f"{dataset_name}-analysis.{body.format}"
    return Response(
        content=content,
        media_type=analyze_export.CONTENT_TYPES[body.format],
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"},
    )


# --- saved views ---------------------------------------------------------------------------------------------------


def _view_out(row: db.Analysis) -> AnalysisOut:
    return AnalysisOut(id=row.id, org_id=row.org_id, title=row.title, dataset=row.dataset, config=row.config,
                       created_at=row.created_at, updated_at=row.updated_at)


def _owner(context: AuthContext) -> str:
    if context.user is None:
        raise HTTPException(status_code=400, detail="Saving a view needs your own account, not the break-glass sign-in")
    return context.user.id


def _own_view(session, context: AuthContext, view_id: str) -> db.Analysis:
    row = session.get(db.Analysis, view_id)
    if row is None or context.user is None or row.owner_id != context.user.id:
        raise HTTPException(status_code=404, detail="View not found")
    return row


@router.get("/views", summary="Your saved views", response_model=list[AnalysisOut])
def list_views(context: AuthContext = Depends(_use)) -> list[AnalysisOut]:
    if context.user is None:
        return []
    with db.SessionLocal() as session:
        rows = session.scalars(select(db.Analysis).where(db.Analysis.owner_id == context.user.id).order_by(db.Analysis.updated_at.desc()))
        return [_view_out(r) for r in rows]


@router.post("/views", summary="Save a view", response_model=AnalysisOut)
def create_view(body: AnalysisWrite, context: AuthContext = Depends(_use)) -> AnalysisOut:
    owner = _owner(context)
    with db.SessionLocal() as session:
        org_id = _org(context, None)
        dataset = _dataset(session, context, org_id, body.dataset)
        try:
            analyze.check_layout(body.config.layout.model_dump(), dataset.fields or [], dataset.measures or [])
        except DataConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = _now()
        row = db.Analysis(org_id=org_id, owner_id=owner, title=body.title.strip(), dataset=body.dataset,
                          config=body.config.model_dump(), created_at=now, updated_at=now)
        session.add(row)
        session.commit()
        return _view_out(row)


@router.get("/views/{view_id}", summary="One of your saved views", response_model=AnalysisOut)
def get_view(view_id: str, context: AuthContext = Depends(_use)) -> AnalysisOut:
    with db.SessionLocal() as session:
        return _view_out(_own_view(session, context, view_id))


@router.put("/views/{view_id}", summary="Update one of your saved views", response_model=AnalysisOut)
def update_view(view_id: str, body: AnalysisWrite, context: AuthContext = Depends(_use)) -> AnalysisOut:
    with db.SessionLocal() as session:
        row = _own_view(session, context, view_id)
        dataset = _dataset(session, context, row.org_id, body.dataset)
        try:
            analyze.check_layout(body.config.layout.model_dump(), dataset.fields or [], dataset.measures or [])
        except DataConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row.title, row.dataset, row.config, row.updated_at = body.title.strip(), body.dataset, body.config.model_dump(), _now()
        session.commit()
        return _view_out(row)


@router.delete("/views/{view_id}", status_code=204, summary="Delete one of your saved views")
def delete_view(view_id: str, context: AuthContext = Depends(_use)) -> None:
    with db.SessionLocal() as session:
        session.delete(_own_view(session, context, view_id))
        session.commit()
