"""The New report wizard: start from the data, then design the template against it.

The register-a-file route (`POST /reports`) asks for a finished template before anything else -- the placeholders
in it are typed blind, before anyone has seen what the data source returns. The wizard runs in the other order:

1. `POST /reports/data-preview` -- run a data source once, unsaved, and see what it returns (and its fields). The
   filters it uses (`:month` in SQL, `{{ month }}` in a URL) become filter parameters by themselves.
2. `POST /reports/drafts` -- create the report as a **draft**: the data source and filters saved, the run's data
   kept as its sample, and a generated **starter template** with every field already placed as its first version.
   Re-made in another file type with `POST /reports/{id}/starter`.
3. The designed template is uploaded as the next version (`PUT /reports/{id}/file`, as for any report), and
   `GET /reports/{id}/template-check` compares its placeholders with the data: typos (with the nearest real name)
   and fields it never uses.
4. Preview with a normal run (`POST /reports/{id}/run`), then `POST /reports/{id}/publish`.

Until it's published, a draft is listed for and runnable by only the people who manage it (routers/reports.py).
See app/report_wizard.py for the fields, the starter files and the check.
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import audit, connections, rbac, report_data, report_ref, report_store, secrets
from ..auth import require_permission, require_report_permission
from ..models import DataPreview, DataPreviewRequest, DraftCreate, ReportMeta, StarterRequest, TemplateCheck
from ..rbac import AuthContext
from ..report_wizard import check_template, data_fields, starter_template, trim_sample
from .reports import _CODE_TAKEN, _check_destination_folder, _require_report_in_callers_org

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

# The sample a draft keeps is stored with the report; the same ceiling as a report's own sample data.
_MAX_SAMPLE_BYTES = report_data.MAX_STATIC_BYTES


def _org(context: AuthContext) -> str:
    # Break-glass has no org of its own: like registering, its reports land in the root org.
    return context.org_id or rbac.ROOT_ORG_ID


def _label(name: str) -> str:
    text = name.replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else name


def _resolve_config(parameters: list[dict], data_source: dict | None, org_id: str) -> tuple[list[dict], dict | None]:
    """The given filters plus one for every filter the source uses that isn't defined yet, then the same validation
    a saved data config gets. Raises DataConfigError."""
    defined = {p["name"] for p in parameters}
    added = [
        {"name": name, "label": _label(name), "type": "text", "required": True}
        for name in report_data.source_parameter_names(data_source)
        if name not in defined
    ]
    return report_data.validate_data_config(
        parameters + added,
        data_source,
        connection_names=connections.names_for_org(org_id),
        secret_names=secrets.active_names_for_org(org_id),
        connection_kinds=connections.kinds_for_org(org_id),
    )


@router.post(
    "/data-preview",
    summary="Run a data source once, unsaved, and see what it returns -- the first step of a new report",
    response_model=DataPreview,
)
def data_preview(body: DataPreviewRequest, context: AuthContext = Depends(require_permission("report:manage"))) -> dict:
    """Makes the real request or query (with the connection's credentials) in the caller's own organization, so a
    manager can only reach their own organization's connections. Answers with the data -- lists cut to their first
    rows -- and its fields; nothing is stored."""
    org_id = _org(context)
    try:
        parameters, source = _resolve_config([p.model_dump() for p in body.parameters], body.data_source.model_dump(), org_id)
    except report_data.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # A filter the source needs, with no test value yet: say which, rather than run it with nothing.
    missing = [
        p["name"] for p in parameters
        if p.get("required", True) and not (body.values.get(p["name"]) or "").strip() and not p.get("default_value")
        and not p.get("options") and not p.get("options_source")
    ]
    if missing:
        return {"data": {}, "fields": [], "parameters": parameters, "elapsed_ms": 0, "truncated": False, "missing": missing}
    try:
        definitions = report_data.resolve_parameter_definitions(
            parameters, materialize=lambda s: connections.materialize(s, org_id)
        )
        values = report_data.resolve_run_parameters(definitions, {d["name"]: None for d in definitions}, body.values)
        started = time.monotonic()
        data = report_data.fetch_report_data(
            connections.materialize(source, org_id), values, {d["name"]: d.get("type") or "text" for d in parameters}
        )
    except report_data.ParameterError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except report_data.DataSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)
    trimmed = trim_sample(data)
    return {
        "data": trimmed,
        "fields": data_fields(trimmed),
        "parameters": parameters,
        "elapsed_ms": elapsed_ms,
        "truncated": trimmed != data,
        "missing": [],
    }


@router.post(
    "/drafts",
    summary="Create a draft report from its data: the data source saved, and a starter template with every field placed",
    response_model=ReportMeta,
)
def create_draft(body: DraftCreate, request: Request, context: AuthContext = Depends(require_permission("report:manage"))) -> dict:
    org_id = _org(context)
    folder_id = (body.folder_id or "").strip() or None
    if folder_id is not None:
        _check_destination_folder(context, folder_id, org_id)

    source = body.data_source.model_dump() if body.data_source else {"type": "static", "static_data": body.sample}
    try:
        parameters, source = _resolve_config([p.model_dump() for p in body.parameters], source, org_id)
    except report_data.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    names = [p["name"] for p in parameters]
    data = trim_sample(body.sample)
    # The sample a preview renders with: the data plus the filters' test values, the way a run combines them.
    sample = {**data, **{k: v for k, v in body.values.items() if k in names}}
    if len(json.dumps(sample, ensure_ascii=False).encode("utf-8")) > _MAX_SAMPLE_BYTES:
        raise HTTPException(status_code=400, detail="The data is too large to keep as a sample -- narrow the query or the test values")

    content = starter_template(body.name, data, body.format, names)
    actor = audit.Actor.of(context, request)
    try:
        created = report_store.create_report(
            name=body.name.strip(), content=content, template_ext=body.format, description=(body.description or "").strip() or None,
            org_id=org_id, code=body.code, folder_id=folder_id, actor=actor,
            note="Starter template, generated from the data", original_filename=f"starter.{body.format}",
            is_draft=True, sample_context=sample, parameters=parameters, data_source=source,
        )
    except report_ref.InvalidCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except report_store.CodeTakenError as exc:
        raise HTTPException(status_code=409, detail=_CODE_TAKEN) from exc
    version = report_store.list_versions(created["report_id"])[0]
    audit.record(
        actor, "report.create", "report", created["report_id"],
        label=created["name"], org_id=created["org_id"],
        summary=f'Started draft report "{created["name"]}" from its data (.{created["template_ext"]} starter)',
        details={"version": 1, "sha256": version["sha256"], "size_bytes": version["size_bytes"], "draft": True,
                 "data_source": source.get("type") if source else None, "parameters": names,
                 "code": created["code"], "folder_id": created["folder_id"]},
    )
    return created


def _managed_report(report_id: str, context: AuthContext) -> dict:
    try:
        meta = report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    _require_report_in_callers_org(context, meta)
    return meta


def _sample_and_parameters(meta: dict) -> tuple[dict | None, list[str]]:
    names = [p["name"] for p in meta.get("parameters") or []]
    sample = meta.get("sample_context")
    if not sample and (meta.get("data_source") or {}).get("type") == "static":
        sample = meta["data_source"].get("static_data")
    return sample, names


@router.post(
    "/{report_id}/starter",
    summary="Replace the template with a freshly generated starter, in any file type",
    response_model=ReportMeta,
)
def regenerate_starter(
    report_id: str, body: StarterRequest, request: Request, context: AuthContext = Depends(require_report_permission("manage"))
) -> dict:
    """Built from the report's sample data. A new version like any other upload, so the one it replaces stays in
    the history."""
    meta = _managed_report(report_id, context)
    sample, names = _sample_and_parameters(meta)
    if not sample:
        raise HTTPException(status_code=400, detail="This report has no sample data to build a starter from")
    data = {k: v for k, v in sample.items() if k not in names}
    content = starter_template(meta["name"], data, body.format, names)
    actor = audit.Actor.of(context, request)
    replaced = report_store.replace_report_file(
        report_id, content, body.format, actor=actor,
        note=f"Starter template (.{body.format}), generated from the data", original_filename=f"starter.{body.format}",
    )
    version = report_store.list_versions(report_id)[0]
    audit.record(
        actor, "report.file_replace", "report", report_id,
        label=replaced["name"], org_id=replaced["org_id"],
        summary=f'Generated a .{body.format} starter template (v{replaced["version"] - 1} → v{replaced["version"]})',
        details={"version": replaced["version"], "from_version": replaced["version"] - 1, "sha256": version["sha256"],
                 "size_bytes": version["size_bytes"], "original_filename": f"starter.{body.format}", "starter": True},
    )
    return replaced


@router.get(
    "/{report_id}/template-check",
    summary="Compare the template's placeholders with the report's sample data",
    response_model=TemplateCheck,
)
def template_check(report_id: str, context: AuthContext = Depends(require_report_permission("manage"))) -> dict:
    """Placeholders naming nothing in the data (they would print empty), each with the nearest real field; and the
    data's fields the template never shows. Best-effort, like the Placeholders tab, but it follows loops."""
    meta = _managed_report(report_id, context)
    sample, names = _sample_and_parameters(meta)
    if not sample:
        return {"checked": False, "reason": "There's no sample data to compare with -- run the data source and save its result as the sample"}
    result = check_template(report_store.get_template_path(report_id), meta["template_ext"], sample, names)
    result["fields"] = data_fields({k: v for k, v in sample.items() if k not in names})
    return result


@router.post("/{report_id}/publish", summary="Publish a draft report: everyone with access can find and run it", response_model=ReportMeta)
def publish_report(report_id: str, request: Request, context: AuthContext = Depends(require_report_permission("manage"))) -> dict:
    meta = _managed_report(report_id, context)
    if not meta.get("is_draft"):
        return meta
    updated = report_store.update_report_meta(report_id, is_draft=False)
    audit.record(
        audit.Actor.of(context, request), "report.publish", "report", report_id,
        label=updated["name"], org_id=updated["org_id"], summary=f'Published "{updated["name"]}"',
    )
    return updated
