"""Projects -- see app/projects.py. A project is a top-level Resources folder marked as one (PATCH /folders/{id}
{"is_project": true}); here it's exported as a package and a package is imported, in two steps: a preview that says
what would happen to every item (nothing is written), then the import with the deployer's choices.

Who may: `project:transfer`, plus manage access on the project (export, or importing into it); a new project
needs `folder:manage` (it's a new top-level folder) and every import `report:manage`. Both are in the audit log."""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import audit, db, image_store, projects, stylesheet_store
from ..auth import ensure_org_scope, require_permission
from ..rbac import ROOT_ORG_ID, AuthContext, can_manage_folder_contents

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

_transfer = require_permission("project:transfer")


class ExportRequest(BaseModel):
    leave_out: list[str] = Field(default_factory=list, description='Shared resources the target already has, as "image:<id>" / "stylesheet:<id>" -- recorded, not packed')
    versions: bool = Field(True, description="Every earlier version of each template, with its note")
    data_sources: bool = Field(True, description="Each template's data source, filters and sample data (connections and secrets by name only)")
    fonts: bool = Field(True, description="Runtime fonts the templates name (Resources > Fonts)")
    term_sets: bool = Field(True, description="Protected-term sets the templates use")


class ImportRequest(BaseModel):
    decisions: dict[str, Literal[
        "create", "create_shared", "create_in_project", "link", "copy_into_project", "overwrite", "keep_both",
        "use_existing", "update", "skip", "install", "replace",
    ]] = Field(default_factory=dict, description="Item key -> choice; an item not named takes its default")


def _user_key(context: AuthContext) -> str:
    return context.user.id if context.user else f"break-glass:{context.username}"


def _manageable_project(session, context: AuthContext, folder_id: str) -> db.Folder:
    try:
        row = projects.project_row(session, folder_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except projects.NotAProject as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ensure_org_scope(context, row.org_id)
    if not can_manage_folder_contents(session, context, folder_id):
        raise HTTPException(status_code=403, detail="You need manage access on this project")
    return row


@router.get("", summary="The projects in an organization the caller may export or import into")
def list_projects(org_id: str | None = Query(None), context: AuthContext = Depends(_transfer)) -> list[dict]:
    org = org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org)
    with db.SessionLocal() as session:
        rows = session.execute(select(db.Folder).where(db.Folder.org_id == org, db.Folder.is_project.is_(True)).order_by(db.Folder.name)).scalars().all()
        return [{"id": r.id, "name": r.name, "description": r.description} for r in rows if can_manage_folder_contents(session, context, r.id)]


@router.get("/{folder_id}", summary="What a project holds and uses -- templates, its own and shared resources, fonts, term sets")
def project_contents(folder_id: str, context: AuthContext = Depends(_transfer)) -> dict:
    with db.SessionLocal() as session:
        _manageable_project(session, context, folder_id)
    return projects.contents(folder_id)


@router.post("/{folder_id}/export", summary="The project as a package (.zip)", response_class=Response)
def export_project(folder_id: str, body: ExportRequest, request: Request, context: AuthContext = Depends(_transfer)) -> Response:
    with db.SessionLocal() as session:
        row = _manageable_project(session, context, folder_id)
        name, org_id = row.name, row.org_id
    content, manifest = projects.export(
        folder_id, leave_out=set(body.leave_out), versions=body.versions, data_sources=body.data_sources,
        fonts=body.fonts, term_sets=body.term_sets, who=context.username,
    )
    left_out = [r["name"] for r in manifest["resources"] if not r["file"]]
    audit.record(
        audit.Actor.of(context, request), "project.export", "folder", folder_id, label=name, org_id=org_id,
        summary=f'Exported project "{name}" ({len(manifest["templates"])} templates, {len(manifest["resources"]) - len(left_out)} resources'
        + (f", {len(left_out)} shared left out" if left_out else "") + ")",
        details={"templates": [t["name"] for t in manifest["templates"]], "left_out": left_out, "contains": manifest["contains"]},
    )
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "project"
    filename = f"{safe}.aksor-project.zip"
    return Response(content=content, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"})


def _check_import_rights(session, context: AuthContext, org_id: str, into: str | None) -> None:
    if not (context.is_superuser or context.has_permission("report:manage")):
        raise HTTPException(status_code=403, detail="Importing a project needs report:manage")
    if into:
        _manageable_project(session, context, into)
    elif not can_manage_folder_contents(session, context, None):
        raise HTTPException(status_code=403, detail="Creating a new project (a top-level folder) needs folder:manage")


@router.post("/import/preview", summary="Read a package and say what importing it would do -- nothing is written yet")
async def preview_import(
    file: UploadFile = File(..., description="A project package (.aksor-project.zip)"),
    into: str | None = Form(None, description="Import into this existing project; omit for a new project"),
    org_id: str | None = Form(None),
    context: AuthContext = Depends(_transfer),
) -> dict:
    org = org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org)
    data = await file.read()
    with db.SessionLocal() as session:
        _check_import_rights(session, context, org, into)
    try:
        package = projects.Package(data)
        result = projects.plan(package, org, into=into, context=context)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except projects.ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "token": projects.stash(data, org, _user_key(context), into)}


@router.post("/import/{token}", summary="Import the previewed package with these choices")
def apply_import(token: str, body: ImportRequest, request: Request, context: AuthContext = Depends(_transfer)) -> dict:
    try:
        data, meta = projects.unstash(token, _user_key(context))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="That import has expired or isn't yours -- upload the package again") from exc
    with db.SessionLocal() as session:
        _check_import_rights(session, context, meta["org_id"], meta.get("into"))
    actor = audit.Actor.of(context, request)
    try:
        summary = projects.apply(projects.Package(data), meta["org_id"], into=meta.get("into"), decisions=body.decisions, context=context, actor=actor)
    except projects.ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (image_store.InvalidImageError, stylesheet_store.InvalidStylesheetError) as exc:
        raise HTTPException(status_code=400, detail=f"A file in the package isn't usable: {exc}") from exc
    projects.discard(token)
    audit.record(
        actor, "project.import", "folder", summary["project"]["id"], label=summary["project"]["name"], org_id=meta["org_id"],
        summary=f'Imported project "{summary["project"]["name"]}": {len(summary["created"])} created, {len(summary["updated"])} updated, '
        f'{len(summary["linked"])} already here, {len(summary["skipped"])} skipped',
        details={k: summary[k] for k in ("created", "updated", "linked", "skipped", "warnings")},
    )
    return summary


@router.delete("/import/{token}", status_code=204, summary="Forget a previewed package without importing it")
def cancel_import(token: str, context: AuthContext = Depends(_transfer)) -> None:
    try:
        projects.unstash(token, _user_key(context))
    except LookupError:
        return
    projects.discard(token)
