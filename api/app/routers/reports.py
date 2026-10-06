"""Generic report templates: register any .docx (Jinja2 via docxtpl),
.xlsx (Jinja2 via xltpl — see excel_engine.render_xlsx_template's
docstring for the row-loop authoring recipe), or .html (Jinja2 via
WeasyPrint, see ../html_template.py) and render it against arbitrary JSON
data, no fixed schema required.

A docx template supports docx/pdf/png (via the libreoffice backend only
— WeasyPrint has no notion of a user-supplied *docx* template); an xlsx
template only supports xlsx — LibreOffice could convert it to pdf/png
too, but that path isn't wired up (out of scope for now, see the project
plan). An html template supports pdf/png only (via weasyprint), and may
reference an uploaded image/stylesheet resource via `{{ resource('name')
}}` in an href/src — ../html_template.py validates that at register time
and resolves it to real bytes at render time.

Auth (see ../auth.py, ../rbac.py): reading (list/get) and rendering stay
public — that's the "any developer can just curl this" design the rest
of this API was built around. Only the administrative actions (create,
update, replace the file, delete — i.e. deciding which templates exist
at all) require the `report:manage` permission, held via a role
(app/rbac.py) or the break-glass PORTAL_USERNAME/PORTAL_PASSWORD
superuser — since those are exactly what the template management portal
(../../portal/, a separate deployable service — see CORSMiddleware in
main.py) exists to gate. Update/replace-file/delete additionally accept
a report-specific `manage`-level grant (app/db.py's ReportAccessGrant)
as an alternative to holding `report:manage` globally.
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import case, func, select

from doc_engine import ConversionError
from doc_engine import render as doc_render

from .. import audit, batch_limits, clients, connections, db, embed_tickets, rbac, render_errors, report_data, report_ref, report_split, report_store, secrets, template_fields
from ..auth import ensure_org_scope, get_current_user, optional_auth_context, require_permission, require_report_permission
from ..auth_events import client_ip
from ..context_media import ImageResolutionError, resolve_image_refs
from ..html_template import ResourceBindingError, build_resource_resolver, parse_html_template, validate_resource_bindings
from ..models import (
    AccessibleReport,
    BatchLimits,
    DataConfig,
    EmbedRunRequest,
    OptionsPreview,
    OptionsPreviewRequest,
    ParsedTemplate,
    ProtectedTermsConfig,
    ReportChangelog,
    ReportMeta,
    ReportRenderStats,
    ReportSchema,
    ReportVersionOut,
    VersionUpdate,
    ReportUpdate,
    RunForm,
    RunRequest,
)
from ..protected_terms_config import ProtectedTermsConfigError, resolve_protected_terms, validate_protected_terms_config
from ..rbac import AuthContext, effective_parameter_limits, has_folder_access, has_report_access
from ..render_log import record_render_event
from ..template_fields import detect_fields
from ..security_events import record_access_denied

_log = logging.getLogger("aksor_khmer_bi.reports")

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

Format = Literal["docx", "pdf", "png", "xlsx"]

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Which render formats a template's own file type can produce.
_ALLOWED_FORMATS = {
    "docx": {"docx", "pdf", "png"},
    "xlsx": {"xlsx"},
    "html": {"pdf", "png"},
}

_EXT_BY_FILENAME = {".docx": "docx", ".xlsx": "xlsx", ".html": "html", ".htm": "html"}


def _template_ext_for(filename: str) -> str | None:
    lower = filename.lower()
    for suffix, ext in _EXT_BY_FILENAME.items():
        if lower.endswith(suffix):
            return ext
    return None

# How many records one batch-render request may hold is a *time* bound, and it
# differs by output format (pdf/png ~2 s a record because each is a LibreOffice
# conversion; docx/xlsx ~0.01 s) -- see batch_limits.py, which owns the numbers.


@router.post(
    "/parse-template",
    summary="Pre-flight parse of an HTML template, before registering it",
    response_model=ParsedTemplate,
    dependencies=[Depends(require_permission("report:manage"))],
)
async def parse_template(
    file: UploadFile = File(..., description="A .html template with Jinja2 placeholders and resource() references"),
) -> dict:
    """Lets the register dialog show detected fields, resource() names to
    map, and any syntax errors *before* the caller commits to registering
    the template — POST /reports (below) re-validates all of this anyway
    at register time, so this endpoint persists nothing; it's purely a
    preview. docx/xlsx have no equivalent pre-flight step (their own
    "cheap sanity check" is fast enough to just run inline in POST
    /reports — see is_valid_office_file) -- html's is worth splitting out
    because unlike those, its validation result (resource names) drives
    an extra interactive step (the mapping UI) the caller needs before
    they even have a resource_bindings value to submit.
    """
    filename = (file.filename or "").lower()
    if _template_ext_for(filename) != "html":
        raise HTTPException(status_code=400, detail="Template file must be a .html or .htm")
    content = await file.read()
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Template is not valid UTF-8 text: {exc}") from exc
    parsed = parse_html_template(source)
    return {
        "fields": parsed.fields,
        "resources": parsed.resources,
        "errors": [{"message": e.message, "line": e.line, "column": e.column} for e in parsed.errors],
    }


@router.post(
    "",
    summary="Register a new report template",
    response_model=ReportMeta,
)
async def create_report(
    request: Request,
    file: UploadFile = File(..., description="A .docx, .xlsx, or .html template with Jinja2 placeholders"),
    name: str = Form(..., description="Display name for this report"),
    description: str | None = Form(None),
    resource_bindings: str | None = Form(
        None, description="html templates only — JSON object mapping each resource() name to {kind, id}"
    ),
    note: str | None = Form(None, description="Optional note recorded against this first version in the changelog"),
    code: str | None = Form(
        None,
        description="Optional code to address this report by instead of its id "
        "(lowercase letters, digits, single hyphens; 3-64; globally unique)",
    ),
    context: AuthContext = Depends(require_permission("report:manage")),
) -> dict:
    actor = audit.Actor.of(context, request)
    filename = file.filename or ""
    template_ext = _template_ext_for(filename)
    if template_ext is None:
        raise HTTPException(status_code=400, detail="Template file must be a .docx, .xlsx, or .html")
    content = await file.read()

    # Break-glass has no org of its own -- new reports it creates land in
    # the root org, same as every other org-less thing this deployment
    # has before any real tenant is set up.
    org_id = context.org_id or rbac.ROOT_ORG_ID

    if template_ext == "html":
        try:
            source = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Template is not valid UTF-8 text: {exc}") from exc
        parsed = parse_html_template(source)
        if parsed.errors:
            raise HTTPException(status_code=400, detail="; ".join(e.message for e in parsed.errors))

        bindings: dict = {}
        if resource_bindings:
            try:
                bindings = json.loads(resource_bindings)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"resource_bindings is not valid JSON: {exc}") from exc
        binding_errors = validate_resource_bindings(set(parsed.resources), bindings, org_id)
        if binding_errors:
            raise HTTPException(status_code=400, detail="; ".join(binding_errors))

        return _register(
            actor, filename, note,
            name=name, content=content, template_ext=template_ext, description=description,
            org_id=org_id, resource_bindings=bindings or None, code=code,
        )

    if not report_store.is_valid_office_file(content, template_ext):
        raise HTTPException(status_code=400, detail=f"Uploaded file is not a valid .{template_ext}")
    return _register(
        actor, filename, note,
        name=name, content=content, template_ext=template_ext, description=description, org_id=org_id, code=code,
    )


_CODE_TAKEN = "That code is already taken — choose another"


def _register(actor: audit.Actor, filename: str, note: str | None, **kwargs) -> dict:
    """Create the report and its first version, then log it."""
    try:
        created = report_store.create_report(**kwargs, actor=actor, note=note, original_filename=filename or None)
    except report_ref.InvalidCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except report_store.CodeTakenError as exc:
        raise HTTPException(status_code=409, detail=_CODE_TAKEN) from exc
    version = report_store.list_versions(created["report_id"])[0]
    audit.record(
        actor, "report.create", "report", created["report_id"],
        label=created["name"], org_id=created["org_id"],
        summary=f'Registered template "{created["name"]}" (.{created["template_ext"]})',
        details={"version": 1, "sha256": version["sha256"], "size_bytes": version["size_bytes"],
                 "original_filename": filename or None, "note": note, "code": created["code"]},
    )
    return created


@router.get("", summary="List registered reports", response_model=list[ReportMeta])
def list_reports() -> list[dict]:
    return report_store.list_reports()


_ACCESS_LEVELS = ("manage", "render", "view")  # highest first


def _report_access_level(session, context: AuthContext, report_id: str) -> str | None:
    """The highest level `context` holds on `report_id`, or None. Each
    level is checked exactly the way `require_report_permission(level)`
    (../auth.py) enforces it on the write/render routes -- the global
    `report:<level>` permission, or a report/folder grant at that level
    (rbac.has_report_access) -- so this listing can't drift from what
    the API would actually let the caller do.
    """
    holds_globally = {level: context.has_permission(f"report:{level}") for level in _ACCESS_LEVELS}
    # A grant at any level satisfies "view" (levels are cumulative), so
    # one has_report_access("view") call is enough to rule out a report
    # the caller has no path to at all, before the per-level checks below.
    if not any(holds_globally.values()) and not has_report_access(session, context, report_id, "view"):
        return None
    for level in _ACCESS_LEVELS:
        if holds_globally[level] or has_report_access(session, context, report_id, level):
            return level
    return None


@router.get(
    "/accessible",
    summary="List the reports the caller may open, with the access level they hold on each",
    response_model=list[AccessibleReport],
)
def list_accessible_reports(context: AuthContext = Depends(get_current_user)) -> list[dict]:
    """Backs the portal's end-user "Reports" page. Unlike `GET /reports`
    above (public, every template -- it exists for developers wiring up
    an integration), this requires a signed-in caller and returns only
    reports they have a route to: a superuser sees everything; anyone
    else sees reports in *their own organization* that they hold a global
    `report:*` permission for, or a report grant or (inherited) folder
    grant on. Another org's reports never appear, whatever the grants.
    """
    if not context.is_superuser and context.org_id is None:
        # No org to scope to -- list_reports(org_id=None) would mean
        # "every report", so fail closed rather than let that through.
        return []

    rows = report_store.list_reports(org_id=None if context.is_superuser else context.org_id)
    visible: list[dict] = []
    with db.SessionLocal() as session:
        for row in rows:
            level = "manage" if context.is_superuser else _report_access_level(session, context, row["report_id"])
            if level is None:
                continue
            visible.append(
                {
                    "report_id": row["report_id"],
                    "name": row["name"],
                    "description": row["description"],
                    "template_ext": row["template_ext"],
                    "version": row["version"],
                    "version_label": row["version_label"],
                    "updated_at": row["updated_at"],
                    "access_level": level,
                }
            )
    visible.sort(key=lambda r: (r["name"].lower(), r["report_id"]))
    return visible


@router.get(
    "/batch-limits",
    summary="The most records one batch-render request may hold, per output format, and roughly how long each takes",
    response_model=BatchLimits,
)
def get_batch_limits() -> dict:
    """Registered before `/{report_id}` on purpose -- routes match in
    registration order, and "batch-limits" would otherwise be read as a
    report id (a 404). Public, like the render routes it describes."""
    return batch_limits.limits()


@router.get("/{report_id}", summary="Get one report's metadata", response_model=ReportMeta)
def get_report(report_id: str) -> dict:
    try:
        return report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")


@router.patch(
    "/{report_id}",
    summary="Update a report's name/description, or move it between Resources folders",
    response_model=ReportMeta,
)
def update_report(
    report_id: str, body: ReportUpdate, request: Request, context: AuthContext = Depends(require_report_permission("manage"))
) -> dict:
    """Moving a report into a folder (`folder_id` set to a real id) also
    requires `manage` on that *destination* folder — require_report_permission
    above only covers the report itself, which isn't enough to let someone
    file a report into a folder they can't otherwise touch.
    """
    folder_id_set = "folder_id" in body.model_fields_set
    if folder_id_set and body.folder_id is not None and not context.is_superuser:
        if not context.has_permission("folder:manage"):
            with db.SessionLocal() as session:
                if not has_folder_access(session, context, body.folder_id, "manage"):
                    raise HTTPException(status_code=403, detail="Missing 'manage' access on the destination folder")

    try:
        before = report_store.get_report(report_id)
        updated = report_store.update_report_meta(
            report_id,
            name=body.name,
            description=body.description,
            sample_context=body.sample_context,
            folder_id=body.folder_id if folder_id_set else report_store.UNSET,
            is_public=body.is_public,
            code=body.code if "code" in body.model_fields_set else report_store.UNSET,
        )
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    except report_ref.InvalidCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except report_store.CodeTakenError as exc:
        raise HTTPException(status_code=409, detail=_CODE_TAKEN) from exc

    changes = audit.diff(before, updated, ["name", "description", "folder_id", "is_public", "code"])
    if before["sample_context"] != updated["sample_context"]:
        changes.append(audit.opaque_change("sample_context"))
    if changes:
        renamed = next((c for c in changes if c["field"] == "name"), None)
        audit.record(
            audit.Actor.of(context, request), "report.update", "report", report_id,
            label=updated["name"], org_id=updated["org_id"], summary=_update_summary(changes), changes=changes,
        )
    return updated


@router.put(
    "/{report_id}/file",
    summary="Replace a report's template file (bumps its version)",
    response_model=ReportMeta,
)
async def replace_report_file(
    report_id: str,
    request: Request,
    file: UploadFile = File(..., description="A .docx or .xlsx template with Jinja2 placeholders"),
    note: str | None = Form(None, description="Optional: what changed in this version -- shown in the changelog"),
    version_label: str | None = Form(None, description="Optional name for this version, e.g. 1.0.1 -- shown instead of v<N>; unique per report"),
    context: AuthContext = Depends(require_report_permission("manage")),
) -> dict:
    try:
        report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")

    filename = (file.filename or "").lower()
    if filename.endswith(".docx"):
        template_ext = "docx"
    elif filename.endswith(".xlsx"):
        template_ext = "xlsx"
    else:
        raise HTTPException(status_code=400, detail="Template file must be a .docx or .xlsx")
    content = await file.read()
    if not report_store.is_valid_office_file(content, template_ext):
        raise HTTPException(status_code=400, detail=f"Uploaded file is not a valid .{template_ext}")
    actor = audit.Actor.of(context, request)
    try:
        replaced = report_store.replace_report_file(
            report_id, content, template_ext, actor=actor, note=note or None,
            original_filename=file.filename or None, version_label=version_label,
        )
    except report_store.VersionLabelError as exc:
        raise HTTPException(status_code=409 if "already" in str(exc) else 400, detail=str(exc))
    version = report_store.list_versions(report_id)[0]
    audit.record(
        actor, "report.file_replace", "report", report_id,
        label=replaced["name"], org_id=replaced["org_id"],
        summary=f'Uploaded new template file (v{replaced["version"] - 1} → {_vname(replaced)})',
        details={
            "version": replaced["version"], "version_label": replaced["version_label"], "from_version": replaced["version"] - 1,
            "sha256": version["sha256"], "size_bytes": version["size_bytes"], "size_delta": version["size_delta"],
            "original_filename": file.filename or None, "note": note or None,
            "fields_added": version["fields_added"], "fields_removed": version["fields_removed"],
        },
    )
    return replaced


def _update_summary(changes: list[dict]) -> str:
    """One readable sentence for a PATCH's field changes."""
    if len(changes) == 1:
        (only,) = changes
        if only["field"] == "name":
            return f'Renamed "{only["before"]}" to "{only["after"]}"'
        if only["field"] == "folder_id":
            return "Moved into a folder" if only["after"] else "Moved to the Resources root"
        if only["field"] == "is_public":
            return "Made visible to everyone in the organization" if only["after"] else "Stopped sharing with the whole organization"
        if only["field"] == "code":
            if not only["before"]:
                return f'Set code "{only["after"]}"'
            return f'Changed code "{only["before"]}" to "{only["after"]}"' if only["after"] else f'Removed code "{only["before"]}"'
    labels = {"folder_id": "folder", "is_public": "sharing", "sample_context": "sample data", "code": "code"}
    return "Updated " + ", ".join(labels.get(c["field"], c["field"].replace("_", " ")) for c in changes)


def _vname(d: dict) -> str:
    """"v1.0.1" for a labelled version, else "v3"."""
    return f'v{d.get("version_label") or d["version"]}'


_TEMPLATE_MEDIA_TYPES = {**_MEDIA_TYPES, "html": "text/html; charset=utf-8"}


def _download_name(name: str, report_id: str, version: int | str, ext: str) -> str:
    """ASCII-only on purpose: the portal reads the name back out of a plain
    `filename="..."` (api.ts's filenameFromDisposition) and a Khmer report
    name can't ride in a header that way. Falls back to the report id."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()[:60] or report_id
    return f"{slug}-v{version}.{ext}"


@router.get(
    "/{report_id}/file",
    summary="Download the template file itself -- the current one, or any retained version (v1 is the original upload)",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}, 404: {"description": "Unknown report, or that version isn't retained"}},
)
def download_template_file(
    report_id: str,
    request: Request,
    version: int | None = Query(None, ge=1, description="Omit for the current file. 1 is the file as first uploaded."),
    context: AuthContext = Depends(require_report_permission("manage")),
) -> Response:
    """The template as uploaded -- Jinja2 placeholders intact -- not a
    rendering of it (that's /render and /run). Manage-level only: the
    template is the report's source, more than the person who may merely
    run it is meant to have. Every download is recorded (who, which
    version, the file's checksum), since a template leaving the system is
    exactly what an investigation may need to find later.
    """
    try:
        meta = report_store.get_report(report_id)
        _require_report_in_callers_org(context, meta)
        path, info = report_store.get_version_file(report_id, version)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    except report_store.VersionNotFoundError:
        detail = (
            "The original upload isn't available -- this template was replaced before version history was kept"
            if version == 1
            else f"Version {version} of this template isn't available"
        )
        raise HTTPException(status_code=404, detail=detail)

    is_current = info["version"] == meta["version"]
    audit.record(
        audit.Actor.of(context, request), "report.template_download", "report", report_id,
        label=meta["name"], org_id=meta["org_id"],
        summary=f'Downloaded template file ({_vname(info)}, '
        + ("original upload" if info["version"] == 1 else "current" if is_current else "earlier version")
        + ")",
        details={"version": info["version"], "version_label": info["version_label"], "is_current": is_current, "sha256": info["sha256"], "size_bytes": info["size_bytes"]},
    )
    filename = _download_name(meta["name"], report_id, info["version_label"] or info["version"], info["template_ext"])
    return Response(
        content=path.read_bytes(),
        media_type=_TEMPLATE_MEDIA_TYPES[info["template_ext"]],
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


@router.patch(
    "/{report_id}/versions/{version}",
    summary="Edit a version's label or note (the file itself never changes)",
    response_model=ReportVersionOut,
)
def update_report_version(
    report_id: str,
    version: int,
    body: VersionUpdate,
    request: Request,
    context: AuthContext = Depends(require_report_permission("manage")),
) -> dict:
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change")
    try:
        meta = report_store.get_report(report_id)
        _require_report_in_callers_org(context, meta)
        before, after = report_store.update_version(report_id, version, changes)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    except report_store.VersionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Version {version} of this template isn't available")
    except report_store.VersionLabelError as exc:
        raise HTTPException(status_code=409 if "already" in str(exc) else 400, detail=str(exc))
    diff = audit.diff(before, after, ["version_label", "note"])
    if diff:
        audit.record(
            audit.Actor.of(context, request), "report.version_update", "report", report_id,
            label=meta["name"], org_id=meta["org_id"],
            summary=f"Edited {_vname({**after, 'version': version})} ({', '.join(c['field'].replace('_', ' ') for c in diff)})",
            details={"version": version}, changes=diff,
        )
    return next(v for v in report_store.list_versions(report_id) if v["version"] == version)


@router.get(
    "/{report_id}/changelog",
    summary="A report's change log: every version of its template file, merged with every other recorded change",
    response_model=ReportChangelog,
)
def get_report_changelog(
    report_id: str,
    limit: int = Query(500, ge=1, le=2000),
    context: AuthContext = Depends(require_report_permission("manage")),
) -> dict:
    """One newest-first timeline. A file version and the audit event that
    recorded its upload are the same happening, so they're one entry (the
    version, carrying the event for its who/where); everything else --
    renames, moves, data-source and protected-term changes, access changes,
    template downloads -- comes through as its own entry.
    """
    try:
        meta = report_store.get_report(report_id)
        _require_report_in_callers_org(context, meta)
        versions = report_store.list_versions(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")

    with db.SessionLocal() as session:
        events, _total = audit.list_events(session, entity_type="report", entity_id=report_id, limit=limit)

    upload_by_version = {
        e["details"]["version"]: e
        for e in events
        if e["action"] in ("report.create", "report.file_replace") and e.get("details") and "version" in e["details"]
    }
    known_versions = {v["version"] for v in versions}
    consumed = {e["id"] for ver, e in upload_by_version.items() if ver in known_versions}

    entries = [
        {"kind": "version", "at": v["created_at"], "version": v, "upload_event": upload_by_version.get(v["version"])}
        for v in versions
    ] + [{"kind": "event", "at": e["created_at"], "event": e} for e in events if e["id"] not in consumed]
    entries.sort(key=lambda entry: entry["at"], reverse=True)

    return {
        "report_id": report_id,
        "current_version": meta["version"],
        "first_retained_version": min((v["version"] for v in versions), default=None),
        "original_available": any(v["version"] == 1 and v["available"] for v in versions),
        "entries": entries,
    }


@router.delete(
    "/{report_id}",
    status_code=204,
    summary="Delete a report template",
)
def delete_report(
    report_id: str, request: Request, context: AuthContext = Depends(require_report_permission("manage"))
) -> None:
    try:
        meta = report_store.get_report(report_id)
        versions = report_store.list_versions(report_id)
        report_store.delete_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    # What's left of the template once it's gone is this row: the last
    # version's checksum lets someone later confirm whether a file they
    # found is (or was) this template.
    audit.record(
        audit.Actor.of(context, request), "report.delete", "report", report_id,
        label=meta["name"], org_id=meta["org_id"],
        summary=f'Deleted template "{meta["name"]}" ({_vname(meta)})',
        details={
            "version": meta["version"], "template_ext": meta["template_ext"],
            "sha256": versions[0]["sha256"] if versions else None,
        },
    )


def _render_one(
    report_id: str,
    data: dict[str, Any],
    fmt: Format,
    *,
    triggered_by: str,
    user_id: str | None = None,
    show_detail: bool | Callable[[], bool] = False,
) -> bytes:
    """Validate `fmt` against this report's template type and render it.
    Shared by the single-render, batch-render, and run routes below so
    all three stay in sync with exactly one implementation of "is this
    format allowed for this report, and how do I actually render it" --
    and, as of the dashboard feature (specs/admin_dashboard_design.md),
    one implementation of "record that a render happened," so
    popular-template/render-time stats reflect every entry point.
    `triggered_by`/`user_id` are telemetry only, threaded through by each
    caller below -- "public" for the two unauthenticated routes (no
    user_id), "run" for the authenticated end-user route.
    """
    try:
        meta = report_store.get_report(report_id)
        template_path = report_store.get_template_path(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")

    allowed = _ALLOWED_FORMATS[meta["template_ext"]]
    if fmt not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"This report is a .{meta['template_ext']} template; supported formats: {sorted(allowed)}",
        )

    try:
        data = resolve_image_refs(data, meta["org_id"])
    except ImageResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if meta["template_ext"] == "html":
        # The html-template counterpart to resolve_image_refs above: binds
        # a `resource` callable into the context so {{ resource('name') }}
        # in the template resolves to a data: URI — see html_template.py's
        # module docstring for why this, not a real file path, is what
        # WeasyPrint ever sees for a custom template's assets.
        data = {**data, "resource": build_resource_resolver(meta.get("resource_bindings"), meta["org_id"])}

    backend = "weasyprint" if meta["template_ext"] == "html" else "libreoffice"
    inject_terms, protected_exclude_terms = resolve_protected_terms(meta.get("protected_terms_config"))
    start = time.perf_counter()
    try:
        content = doc_render(
            data,
            fmt,
            backend=backend,
            template_path=template_path,
            extra_terms=inject_terms,
            exclude_terms=protected_exclude_terms,
        )
    except ConversionError as exc:
        record_render_event(report_id, meta.get("org_id"), fmt, backend, "error", None, triggered_by, user_id)
        failure = render_errors.build(
            exc,
            template_path=Path(template_path) if template_path else None,
            full=show_detail() if callable(show_detail) else show_detail,
        )
        _log.exception("Rendering report_id=%r as .%s failed (ref %s)", report_id, fmt, failure.info["reference"])
        raise failure from exc
    except ResourceBindingError as exc:
        record_render_event(report_id, meta.get("org_id"), fmt, backend, "error", None, triggered_by, user_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # A template that can't be rendered (an unclosed loop, a missing field...) used to escape as a bare
        # 500 -- which the browser can't even read -- so say what happened, to whoever may be told.
        record_render_event(report_id, meta.get("org_id"), fmt, backend, "error", None, triggered_by, user_id)
        failure = render_errors.build(
            exc,
            template_path=Path(template_path) if template_path else None,
            full=show_detail() if callable(show_detail) else show_detail,
        )
        _log.exception("Rendering report_id=%r as .%s failed (ref %s)", report_id, fmt, failure.info["reference"])
        raise failure from exc

    record_render_event(
        report_id, meta.get("org_id"), fmt, backend, "success", int((time.perf_counter() - start) * 1000), triggered_by, user_id
    )
    return content


def _caller_manages(request: Request, report_id: str) -> bool:
    """Whether this (otherwise anonymous) call carries the credentials -- an access token, or Basic -- of
    someone who manages the report: the template author previewing it. Looked up only when a render has
    already failed, and never raises."""
    context = optional_auth_context(request)
    if context is None:
        return False
    if context.is_superuser:
        return True
    try:
        with db.SessionLocal() as session:
            return _report_access_level(session, context, report_id) == "manage"
    except Exception:  # noqa: BLE001
        return False


def _plan_parts(report_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    """The contexts to render for this report -- more than one when its
    repeating table is over the per-file row limit (see report_split.py)."""
    try:
        meta = report_store.get_report(report_id)
        template_path = report_store.get_template_path(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    collections = report_split.loop_collections(template_path, meta["template_ext"])
    try:
        return report_split.plan_parts(data, collections)
    except report_split.TooManyPartsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _render_output(
    report_id: str,
    data: dict[str, Any],
    fmt: Format,
    *,
    triggered_by: str,
    user_id: str | None = None,
    part: int | None = None,
    show_detail: bool | Callable[[], bool] = False,
) -> StreamingResponse:
    """Render `data` and build the response, shared by /render and /run.

    Normally one file. If the report's table is over the row limit it is
    split into several files (report_split.py): asked for as a whole they
    come back as one ZIP; asked for one `part` -- what the portal's preview
    does -- that single file comes back. Either way `X-Report-Parts` says how
    many files the report has, so a client can offer the rest.
    """
    try:
        contexts = _plan_parts(report_id, data)
    except HTTPException:
        raise
    except Exception as exc:  # reading a broken template to plan the split must not escape as a bare 500
        failure = render_errors.build(exc, template_path=None, full=show_detail() if callable(show_detail) else show_detail)
        _log.exception("Planning the files of report_id=%r failed (ref %s)", report_id, failure.info["reference"])
        raise failure from exc
    count = len(contexts)
    if part is not None and not 1 <= part <= count:
        raise HTTPException(status_code=400, detail=f"This report has {count} file(s); there is no part {part}")

    headers = {"X-Report-Parts": str(count)}
    if part is not None or count == 1:
        index = (part or 1) - 1
        content = _render_one(report_id, contexts[index], fmt, triggered_by=triggered_by, user_id=user_id, show_detail=show_detail)
        name = f"{report_id}.{fmt}" if count == 1 else report_split.part_filename(report_id, index + 1, count, fmt)
        return StreamingResponse(
            io.BytesIO(content),
            media_type=_MEDIA_TYPES[fmt],
            headers={**headers, "X-Report-Part": str(index + 1), "Content-Disposition": f'attachment; filename="{name}"'},
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for number, context in enumerate(contexts, start=1):
            content = _render_one(report_id, context, fmt, triggered_by=triggered_by, user_id=user_id, show_detail=show_detail)
            zf.writestr(report_split.part_filename(report_id, number, count, fmt), content)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={**headers, "Content-Disposition": f'attachment; filename="{report_split.zip_name(report_id)}"'},
    )


@router.post(
    "/{report_id}/render",
    summary="Render a registered report against arbitrary JSON data",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/pdf": {}, "application/zip": {}}}},
)
def render_report(
    request: Request,
    report_id: str,
    data: dict[str, Any],
    fmt: Format = Query("pdf", alias="format", description="docx, pdf, png, or xlsx"),
    part: int | None = Query(
        None,
        ge=1,
        description="If the report is split into several files (its table is over the per-file row limit), "
        "return just this one (1-based) instead of all of them as a ZIP",
    ),
) -> StreamingResponse:
    """Render one report and stream the result back.

    "Stream" here describes HTTP delivery, not generation: the file is
    still produced by one synchronous LibreOffice/openpyxl conversion
    before any bytes are sent (there's no incremental/progressive
    rendering), but the response body itself is delivered to the client
    as a stream (`StreamingResponse` over the in-memory result) rather
    than handed to Starlette as one pre-sized blob.

    A report whose repeating table has more rows than the per-file limit
    (MAX_ROWS_PER_FILE, default 1,000) is rendered as several files and
    returned as a ZIP -- see report_split.py.
    """
    return _render_output(
        report_id, data, fmt, triggered_by="public", part=part,
        show_detail=lambda: _caller_manages(request, report_id),
    )


@router.post(
    "/{report_id}/render/batch",
    summary="Render a registered report against a list of JSON contexts, as one ZIP",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {}}}},
)
def render_report_batch(
    report_id: str,
    data: list[dict[str, Any]],
    fmt: Format = Query("pdf", alias="format", description="docx, pdf, png, or xlsx"),
) -> StreamingResponse:
    """Render the same report against N contexts in one call -- "a ton of
    reports at once" (a mail-merge run, a batch of invoices, etc.) without
    N separate HTTP round trips.

    This is one synchronous request: every context is rendered in order, the
    results are collected into one ZIP in memory, and *then* the ZIP is
    streamed to the client -- there is no incremental/partial delivery, and
    no progress, while rendering is under way. (The Jobs feature's worker
    could run this in the background, but there is no batch job type yet --
    its `render_report` job renders a single context.) So the size of a
    batch is bounded by time, per output format: see batch_limits.py and
    `GET /reports/batch-limits`. The first rendering error fails the whole
    batch (same error shape as the single-render route); there's no
    partial-success manifest in this version.
    """
    if not data:
        raise HTTPException(status_code=400, detail="Batch must contain at least one context")
    if len(data) > batch_limits.max_batch_size(fmt):
        raise HTTPException(status_code=400, detail=batch_limits.over_limit_message(len(data), fmt))

    # Every record is checked before any is rendered, so an oversized one
    # fails the request immediately instead of after minutes of rendering.
    # (One document per record: a record big enough to need splitting into
    # several files belongs on the single-render route, not in this ZIP.)
    contexts = []
    for index, record in enumerate(data):
        planned = _plan_parts(report_id, record)
        if len(planned) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"Record {index + 1} has more rows than fit in one file "
                f"(limit {report_split.max_rows_per_file():,}); render it on its own with POST /{report_id}/render "
                "to get it split into parts.",
            )
        contexts.append(planned[0])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, context in enumerate(contexts):
            content = _render_one(report_id, context, fmt, triggered_by="public")
            zf.writestr(f"{report_id}-{index:04d}.{fmt}", content)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{report_id}-batch.zip"'},
    )


_ORDERED_FORMATS = ("pdf", "png", "docx", "xlsx")


@router.get(
    "/{report_id}/data-config",
    summary="A report's filter parameters and data source (managers only)",
    response_model=DataConfig,
    dependencies=[Depends(require_report_permission("manage"))],
)
def get_data_config(report_id: str) -> dict:
    """Manager-only on purpose: this holds the full option lists a grant is
    meant to narrow, and possibly header values for the data source -- so
    it's not part of ReportMeta, which the public GET routes return."""
    try:
        meta = report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"parameters": meta.get("parameters") or [], "data_source": meta.get("data_source")}


@router.put(
    "/{report_id}/data-config",
    summary="Replace a report's filter parameters and data source",
    response_model=DataConfig,
)
def put_data_config(
    report_id: str, body: DataConfig, request: Request, context: AuthContext = Depends(require_report_permission("manage"))
) -> dict:
    try:
        before = report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        parameters, data_source = report_data.validate_data_config(
            [p.model_dump() for p in body.parameters],
            body.data_source.model_dump() if body.data_source else None,
            connection_names=connections.names_for_org(before["org_id"]),
            secret_names=secrets.active_names_for_org(before["org_id"]),
            connection_kinds=connections.kinds_for_org(before["org_id"]),
        )
    except report_data.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = report_store.update_data_config(report_id, parameters, data_source)

    changes = []
    parameter_change = audit.named_list_change("parameters", before.get("parameters"), updated["parameters"])
    if parameter_change:
        changes.append(parameter_change)
    source_changes = audit.diff({"data_source": before.get("data_source")}, {"data_source": updated["data_source"]}, ["data_source"])
    # Sample data is a bulky payload (up to 1 MB of arbitrary keys): record that it changed, not every leaf of it.
    sample = [c for c in source_changes if c["field"].startswith("data_source.static_data")]
    if sample:
        source_changes = [c for c in source_changes if c not in sample] + [audit.opaque_change("data_source.static_data")]
    changes += source_changes
    if changes:
        # The data source is where a report's rows come from -- pointing it
        # somewhere else is the change worth being able to find later.
        audit.record(
            audit.Actor.of(context, request), "report.data_config_update", "report", report_id,
            label=updated["name"], org_id=updated["org_id"],
            summary="Changed data source" if any(c["field"].startswith("data_source") for c in changes) and not parameter_change
            else "Changed filter parameters" if parameter_change and len(changes) == 1
            else "Changed filter parameters and data source",
            changes=changes,
        )
    return {"parameters": updated["parameters"] or [], "data_source": updated["data_source"]}


_PREVIEW_OPTIONS_SHOWN = 20


@router.post(
    "/{report_id}/data-config/preview-options",
    summary="Try a parameter's REST-backed choice list -- saved or not -- and see the choices it gives",
    response_model=OptionsPreview,
)
def preview_options(
    report_id: str, body: OptionsPreviewRequest, context: AuthContext = Depends(require_report_permission("manage"))
) -> dict:
    """What the "Test" button on a choice list calls, so the JSONPaths can be
    checked against the real response before anything is saved. It makes a real
    outbound request (with the connection's credentials, if any), so unlike the
    other data-config routes it also insists the report is in the caller's own
    organization -- a manager elsewhere can't borrow this one's connections.
    Answers only with the mapped choices, never the raw response."""
    try:
        meta = report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    _require_report_in_callers_org(context, meta)
    try:
        source = report_data.validate_options_source(
            body.options_source.model_dump(), "this choice list",
            connections.names_for_org(meta["org_id"]), secrets.active_names_for_org(meta["org_id"]),
            connections.kinds_for_org(meta["org_id"]),
        )
        options = report_data.fetch_parameter_options(connections.materialize(source, meta["org_id"]))
    except report_data.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except report_data.DataSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"total": len(options), "options": options[:_PREVIEW_OPTIONS_SHOWN]}


@router.get(
    "/{report_id}/protected-terms-config",
    summary="A report's own protected-terms layer (managers only)",
    response_model=ProtectedTermsConfig,
    dependencies=[Depends(require_report_permission("manage"))],
)
def get_protected_terms_config(report_id: str) -> dict:
    """Manager-only, same posture as get_data_config above."""
    try:
        meta = report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    config = meta.get("protected_terms_config") or {}
    return {
        "set_ids": config.get("set_ids") or [],
        "terms": config.get("terms") or [],
        "exclude_terms": config.get("exclude_terms") or [],
    }


@router.put(
    "/{report_id}/protected-terms-config",
    summary="Replace a report's own protected-terms layer",
    response_model=ProtectedTermsConfig,
)
def put_protected_terms_config(
    report_id: str, body: ProtectedTermsConfig, request: Request, context: AuthContext = Depends(require_report_permission("manage"))
) -> dict:
    try:
        meta = report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        cleaned = validate_protected_terms_config(body.model_dump(), meta["org_id"])
    except ProtectedTermsConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = report_store.update_protected_terms_config(report_id, cleaned)
    config = updated.get("protected_terms_config") or {}

    def _layer(m: dict) -> dict:
        c = m.get("protected_terms_config") or {}
        return {"set_ids": c.get("set_ids") or [], "terms": c.get("terms") or [], "exclude_terms": c.get("exclude_terms") or []}

    changes = audit.diff(_layer(meta), _layer(updated), ["set_ids", "terms", "exclude_terms"])
    if changes:
        audit.record(
            audit.Actor.of(context, request), "report.terms_config_update", "report", report_id,
            label=updated["name"], org_id=updated["org_id"],
            summary="Changed protected terms (" + ", ".join(c["field"].replace("_", " ") for c in changes) + ")",
            changes=changes,
        )
    return {
        "set_ids": config.get("set_ids") or [],
        "terms": config.get("terms") or [],
        "exclude_terms": config.get("exclude_terms") or [],
    }


def _require_report_in_callers_org(context: AuthContext, meta: dict) -> None:
    """404 -- not 403: whether it exists isn't theirs to learn -- for a report
    in another organization. `require_report_permission` (../auth.py) accepts
    the *global* report:manage/render permission without looking at which
    org a report belongs to, so a route that hands out a report's contents
    has to check that itself. Superusers span organizations.
    """
    if not context.is_superuser and (context.org_id is None or meta["org_id"] != context.org_id):
        raise HTTPException(status_code=404, detail="Report not found")


def _authorize_run(report_id: str, context: AuthContext):
    """Shared by run-form and run so the two can never disagree about who
    may do what. Returns (report meta, access level, parameter definitions,
    the caller's per-parameter limits).

    A report the caller has no route to -- including any report in another
    organization -- is a 404, never a 403: whether it exists isn't theirs
    to learn. Viewing isn't running: a view-only caller gets a 403.
    """
    try:
        meta = report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    _require_report_in_callers_org(context, meta)

    definitions = meta.get("parameters") or []
    with db.SessionLocal() as session:
        level = "manage" if context.is_superuser else _report_access_level(session, context, report_id)
        if level is None:
            raise HTTPException(status_code=404, detail="Report not found")
        if level == "view":
            raise HTTPException(status_code=403, detail="You can view this report but not run it")
        limits = effective_parameter_limits(session, context, report_id, [d["name"] for d in definitions])

    # Outside the DB session -- a live outbound HTTP call has no business
    # holding a connection open. Turns any options_source parameter into
    # a plain options list, so allowed_options/resolve_run_parameters
    # below never need to know dynamic options exist.
    try:
        definitions = report_data.resolve_parameter_definitions(
            definitions, materialize=lambda source: connections.materialize(source, meta["org_id"])
        )
    except report_data.DataSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return meta, level, definitions, limits


@router.get(
    "/{report_id}/run-form",
    summary="What the run page needs: the report's parameters, with options narrowed to the caller's grants",
    response_model=RunForm,
)
def get_run_form(report_id: str, context: AuthContext = Depends(get_current_user)) -> dict:
    meta, level, definitions, limits = _authorize_run(report_id, context)
    allowed = _ALLOWED_FORMATS[meta["template_ext"]]
    return {
        "report_id": meta["report_id"],
        "name": meta["name"],
        "description": meta["description"],
        "template_ext": meta["template_ext"],
        "access_level": level,
        "formats": [f for f in _ORDERED_FORMATS if f in allowed],
        "parameters": [
            {
                "name": d["name"],
                "label": d.get("label"),
                "type": d.get("type") or "text",
                "required": d.get("required", True),
                # As configured -- `now()` stays `now()`: the portal reads the
                # viewer's own clock for it, not the server's.
                "default_value": d.get("default_value"),
                # Narrowed here, server-side: a value the caller may not use
                # is never sent to the browser at all.
                "options": report_data.allowed_options(d, limits[d["name"]]),
            }
            for d in definitions
        ],
    }


@router.post(
    "/{report_id}/run",
    summary="Run a report for the signed-in user, enforcing their parameter limits before fetching its data",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/pdf": {}, "application/zip": {}}}},
)
def run_report(report_id: str, body: RunRequest, request: Request, context: AuthContext = Depends(get_current_user)) -> StreamingResponse:
    """The authenticated counterpart to the public `/render` route (which
    renders whatever data its caller supplies -- right for a trusted
    integration, wrong for enforcing "this user may only see branch BR01").
    Order matters: authorize -> reject any parameter value the caller's
    grants don't allow -> only then call the report's data source with the
    surviving values -> render. The browser supplies nothing but the
    parameter values; the data comes from the server-side source.
    """
    meta, _level, definitions, limits = _authorize_run(report_id, context)
    if body.format not in _ALLOWED_FORMATS[meta["template_ext"]]:
        raise HTTPException(
            status_code=400,
            detail=f"This report is a .{meta['template_ext']} template; supported formats: {sorted(_ALLOWED_FORMATS[meta['template_ext']])}",
        )

    try:
        params = report_data.resolve_run_parameters(definitions, limits, body.parameters)
    except report_data.ParameterError as exc:
        _log.warning("Report run denied: user=%r report_id=%r reason=%s", context.username, report_id, exc)
        # Only the 403 case is a real authorization denial worth the
        # security feed -- the 400 case is just an incomplete/malformed
        # request (missing value, unknown parameter), not a security event.
        if exc.status == 403:
            record_access_denied(
                username=context.username,
                org_id=context.org_id,
                user_id=context.user.id if context.user else None,
                permission_code="report:run",
                resource=report_id,
                ip_address=client_ip(request),
                reason=str(exc),
            )
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    return _fetch_and_render(
        meta,
        params,
        body.format,
        body.part,
        triggered_by="run",
        user_id=context.user.id if context.user else None,
        who=f"user={context.username!r}",
        actor=audit.Actor.of(context, request),
        selected=[name for name, value in body.parameters.items() if value not in (None, "")],
        # Whoever manages the report is the one testing it, so they get the engine's own error.
        show_detail=_level == "manage",
    )


def _fetch_and_render(
    meta: dict,
    params: dict[str, str],
    fmt: Format,
    part: int | None,
    *,
    triggered_by: str,
    user_id: str | None,
    who: str,
    show_detail: bool = False,
    actor: audit.Actor | None = None,
    selected: list[str] | None = None,
) -> StreamingResponse:
    """The last two steps of a parameterised run, shared by /run (a signed-in
    user) and /embed-run (a ticket-holder): call the report's data source with
    the already-validated `params`, then render. Whoever is allowed to ask has
    been decided before this point."""
    started = time.monotonic()

    def audited(outcome: str, reason: str | None = None) -> None:
        if actor is not None:
            _audit_run(actor, meta, fmt, params, selected or [], triggered_by, outcome, reason, started)

    fetched: dict = {}
    if meta.get("data_source"):
        try:
            source = connections.materialize(meta["data_source"], meta["org_id"])
            fetched = report_data.fetch_report_data(source, params, {d["name"]: d.get("type") or "text" for d in meta.get("parameters") or []})
        except report_data.DataSourceError as exc:
            audited("data_source_failed", str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    _log.info("Report %s: %s report_id=%r format=%s parameters=%r", triggered_by, who, meta["report_id"], fmt, params)
    # The validated parameter values win over any same-named key the data
    # source returned, so the document always states what was actually asked for.
    try:
        response = _render_output(
            meta["report_id"],
            {**fetched, **params},
            fmt,
            triggered_by=triggered_by,
            user_id=user_id,
            part=part,
            show_detail=show_detail,
        )
    except HTTPException as exc:
        audited("render_failed", f"HTTP {exc.status_code}")
        raise
    audited("success")
    response.headers.update(_report_headers(meta))
    return response


def _audit_run(
    actor: audit.Actor,
    meta: dict,
    fmt: str,
    params: dict[str, str],
    selected: list[str],
    triggered_by: str,
    outcome: str,
    reason: str | None,
    started: float,
) -> None:
    """One audit row per run: who ran which report, when (the row's timestamp), how many parameters they
    chose and how it ended. The parameter *names* are kept, never their values -- a value can be an account
    or customer number, which the audit trail has no business holding."""
    ok = outcome == "success"
    audit.record(
        actor,
        "report.run" if ok else "report.run_failed",
        "report",
        meta["report_id"],
        label=meta.get("name"),
        org_id=meta.get("org_id"),
        summary=(
            f"Ran the report with {len(selected)} parameter(s) chosen"
            if ok
            else f"Run failed ({outcome.replace('_', ' ')}) with {len(selected)} parameter(s) chosen"
        ),
        details={
            "via": triggered_by,
            "format": fmt,
            "parameters_selected": len(selected),
            "parameters_total": len(params),
            "parameter_names": sorted(selected),
            "outcome": outcome,
            **({"reason": reason} if reason else {}),
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
    )


def _report_headers(meta: dict) -> dict[str, str]:
    """What a viewer needs to present a run's result -- the report's name and template
    type -- so a caller that starts from just parameters (the embed page) needn't look the
    report up first. The name is percent-encoded: header values are ASCII, and Khmer report
    names are the common case here."""
    return {"X-Report-Name": quote(meta["name"], safe=""), "X-Report-Ext": meta["template_ext"]}


@router.post(
    "/{report_id}/embed-run",
    summary="Run a report by parameters for an embedder -- with a signed ticket or an API client's credentials",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/pdf": {}, "application/zip": {}}}},
)
def embed_run_report(report_id: str, body: EmbedRunRequest, request: Request) -> StreamingResponse:
    """What an embedded viewer (`#/embed/<report>`) calls when its host page
    hands it parameters instead of finished data.

    Anonymous like `/render` -- the embedder's visitors have no account here --
    but where `/render` only formats what the caller supplied, this fetches
    from the report's data source using its stored credentials. So who may ask
    is decided before anything is fetched, one of two ways -- and a request
    with neither is refused:

    * a **ticket** (app/embed_tickets.py): signed by the embedder's backend
      after it checked its own signed-in user, and bound to this report and
      these exact parameters; or
    * an **API client** (app/clients.py): a client id + secret an admin created
      and granted this report -- allowed or revoked at runtime, with no
      deployment change; rate-limited per client.

    Order matters: authorize -> then resolve/validate the parameters -> only
    then call the data source.
    """
    try:
        meta = report_store.get_report(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")

    if body.ticket is not None:
        who = _authorize_ticketed_embed_run(meta, body, request)
        triggered_by = "embed"
    elif body.client_id is not None:
        who = _authorize_client_embed_run(meta, body, request)
        triggered_by = "embed-client"
    else:
        # Log only: anyone can send these, so a security-feed row per attempt
        # would let an anonymous caller grow that table without limit.
        _log.warning("Embed run rejected: report_id=%r ip=%s reason=no ticket or client credentials", meta["report_id"], client_ip(request))
        raise HTTPException(status_code=401, detail="This report can only be run with a signed ticket or API client credentials")

    if body.format not in _ALLOWED_FORMATS[meta["template_ext"]]:
        raise HTTPException(
            status_code=400,
            detail=f"This report is a .{meta['template_ext']} template; supported formats: {sorted(_ALLOWED_FORMATS[meta['template_ext']])}",
        )

    try:
        definitions = report_data.resolve_parameter_definitions(
            meta.get("parameters") or [], materialize=lambda source: connections.materialize(source, meta["org_id"])
        )
    except report_data.DataSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # No per-user limits to apply: there's no user here, and the values were
    # authorized by whoever signed the ticket (which pinned them), or -- for an
    # opted-in report -- are only what the parameter definitions themselves allow.
    unrestricted = {d["name"]: None for d in definitions}
    try:
        params = report_data.resolve_run_parameters(definitions, unrestricted, body.parameters)
    except report_data.ParameterError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    return _fetch_and_render(
        meta,
        params,
        body.format,
        body.part,
        triggered_by=triggered_by,
        user_id=None,
        who=who,
        actor=audit.Actor(username=who, org_id=meta.get("org_id"), ip_address=client_ip(request)),
        selected=[name for name, value in body.parameters.items() if value not in (None, "")],
    )


def _authorize_client_embed_run(meta: dict, body: EmbedRunRequest, request: Request) -> str:
    """Let a run through for an active API client that holds a grant for this
    report, within the client's rate limit. Returns who to log it against."""
    ip = client_ip(request)
    identity = clients.authenticate(body.client_id, body.client_secret)
    if identity is None:
        # One message for an unknown client, a wrong secret and a disabled client. Log only:
        # anyone can send these, so a security-feed row per attempt would let an anonymous
        # caller grow that table without limit.
        _log.warning("Embed run rejected: report_id=%r ip=%s client_id=%r reason=invalid client credentials", meta["report_id"], ip, body.client_id)
        raise HTTPException(status_code=401, detail="Invalid client credentials")

    # From here the credentials are genuine, so being refused is a real client asking for
    # something it wasn't granted -- which the security feed should show.
    if not clients.may_run(identity, meta):
        _log.warning("Embed run denied: client_id=%r report_id=%r reason=not granted", identity.client_id, meta["report_id"])
        record_access_denied(
            username=f"client:{identity.client_id}",
            org_id=identity.org_id,
            user_id=None,
            permission_code="client:run",
            resource=meta["report_id"],
            ip_address=ip,
            reason="API client has no grant for this report",
        )
        raise HTTPException(status_code=403, detail="This client may not run this report")

    retry_after = clients.limiter.retry_after(identity.pk)
    if retry_after is not None:
        _log.warning("Embed run rate-limited: client_id=%r report_id=%r", identity.client_id, meta["report_id"])
        raise HTTPException(
            status_code=429,
            detail="Too many requests -- try again in a moment",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    clients.touch(identity)
    return f"client:{identity.client_id}"


def _authorize_ticketed_embed_run(meta: dict, body: EmbedRunRequest, request: Request) -> str:
    """Verify the ticket -> check it is for this report and these exact values.
    Returns who to log the run against."""
    try:
        claims = embed_tickets.verify(body.ticket)
    except embed_tickets.TicketError as exc:
        # Log only: anyone can send these, so a security-feed row per attempt
        # would let an anonymous caller grow that table without limit.
        _log.warning("Embed run rejected: report_id=%r ip=%s reason=%s", meta["report_id"], client_ip(request), exc)
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    # From here the ticket is genuine: a mismatch is its holder asking for
    # something it wasn't issued for, which the security feed should show.
    def deny(reason: str) -> HTTPException:
        _log.warning("Embed run denied: ticket sub=%r report_id=%r reason=%s", claims["sub"], meta["report_id"], reason)
        record_access_denied(
            username=f"ticket:{claims['sub']}",
            org_id=meta["org_id"],
            user_id=None,
            permission_code="report:embed-run",
            resource=meta["report_id"],
            ip_address=client_ip(request),
            reason=reason,
        )
        return HTTPException(status_code=403, detail=reason)

    if claims["report"] not in (meta["report_id"], meta.get("code")):
        raise deny("This ticket is for a different report")
    if claims["params"] != body.parameters:
        raise deny("These parameters aren't the ones this ticket was issued for")
    return f"ticket sub={claims['sub']!r}"


@router.get(
    "/{report_id}/schema",
    summary="Best-effort list of Jinja2 placeholder fields the template expects",
    response_model=ReportSchema,
)
def get_report_schema(report_id: str) -> dict:
    """Not a guaranteed-complete schema -- a cheap, honest best-effort scan
    (same spirit as report_store.is_valid_office_file's "cheap sanity
    check," not full validation):

    - docx: docxtpl's own `get_undeclared_template_variables()`, which
      walks the compiled Jinja2 AST -- reliable for top-level names, but a
      loop variable (`{%tr for item in items %}` ... `{{ item.label }}`)
      surfaces as `item`/`items`, not the nested `item.label` path.
    - xlsx: xltpl has no equivalent introspection API, so this falls back
      to a plain regex scan of the workbook's XML for `{{ name` patterns --
      cruder, and won't see anything docxtpl-style AST analysis would
      catch, but good enough to seed a starter payload.
    - html: the same Jinja2 AST walk POST /reports/parse-template ran at
      register time (../html_template.py), re-run fresh off the stored
      file rather than cached, so this stays correct if that logic
      changes later.
    """
    try:
        meta = report_store.get_report(report_id)
        template_path = report_store.get_template_path(report_id)
    except report_store.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")

    ext = meta["template_ext"]
    return {"fields": detect_fields(template_path, ext), "engine": template_fields.ENGINE_BY_EXT[ext], "note": _SCHEMA_NOTES[ext]}


_SCHEMA_NOTES = {
    "docx": "Top-level Jinja2 variable names only -- a repeating-row loop variable "
    "(e.g. 'item') is listed on its own, not as 'item.label'.",
    "html": "Top-level Jinja2 variable names only, excluding 'resource' (bound automatically "
    "at render time — see resource_bindings on this report's metadata for the image/stylesheet "
    "references it needs, already mapped at registration).",
    "xlsx": "Best-effort text scan of the workbook XML, not AST-based -- may miss or "
    "misclassify some placeholders; treat this as a starting point, not ground truth.",
}


@router.get(
    "/analytics/summary",
    summary="Per-report render counts and duration stats, from report_render_log",
    response_model=list[ReportRenderStats],
)
def get_render_analytics(
    days: int = Query(30, ge=1, le=365, description="How far back to look"),
    limit: int = Query(10, ge=1, le=100, description="Top N reports by render count"),
    org_id: str | None = Query(None, description="Superusers may omit this to see every org's stats"),
    context: AuthContext = Depends(require_permission("report:view")),
) -> list[ReportRenderStats]:
    """Backs the admin dashboard's "popular templates" / render-time
    panel (specs/admin_dashboard_design.md). Gated report:view, not
    report:manage -- render counts/durations aren't sensitive the way
    data_source's header values are, and whoever can already see a
    report can see its own usage stats.
    """
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.SessionLocal() as session:
        query = (
            select(
                db.RenderEvent.report_id,
                db.ReportRow.name,
                func.count(db.RenderEvent.id).label("render_count"),
                func.sum(case((db.RenderEvent.status == "error", 1), else_=0)).label("error_count"),
                func.avg(db.RenderEvent.duration_ms).label("avg_duration_ms"),
                func.max(db.RenderEvent.created_at).label("last_rendered_at"),
            )
            .join(db.ReportRow, db.ReportRow.report_id == db.RenderEvent.report_id)
            .where(db.RenderEvent.created_at >= since)
        )
        if org_id is not None:
            query = query.where(db.RenderEvent.org_id == org_id)
        query = (
            query.group_by(db.RenderEvent.report_id, db.ReportRow.name)
            .order_by(func.count(db.RenderEvent.id).desc())
            .limit(limit)
        )
        rows = session.execute(query).all()

        # p95 computed in Python per report, over this same window's
        # successful renders -- no native percentile function that's
        # portable across this repo's sqlite-dev/postgres-prod split.
        # N+1 (one query per row) is acceptable here: `limit` caps rows
        # at 100 and this is a dashboard view, not a hot path.
        result: list[ReportRenderStats] = []
        for row in rows:
            durations = sorted(
                d
                for d in session.execute(
                    select(db.RenderEvent.duration_ms).where(
                        db.RenderEvent.report_id == row.report_id,
                        db.RenderEvent.status == "success",
                        db.RenderEvent.created_at >= since,
                    )
                )
                .scalars()
                .all()
                if d is not None
            )
            p95 = durations[min(int(len(durations) * 0.95), len(durations) - 1)] if durations else None
            result.append(
                ReportRenderStats(
                    report_id=row.report_id,
                    name=row.name,
                    render_count=row.render_count,
                    error_count=row.error_count or 0,
                    avg_duration_ms=row.avg_duration_ms,
                    p95_duration_ms=p95,
                    last_rendered_at=row.last_rendered_at,
                )
            )
        return result
