"""The stylesheet half of the Resources repository (see routers/folders.py
and routers/images.py, which this mirrors) -- upload/list/delete CSS
files, filed in the same folder tree report templates and images are.
A stylesheet may be uploaded as CSS, SCSS, Sass or Less (app/style_compile.py): templates always get the compiled
CSS (/file); the upload itself is kept and served by /source.
Exists specifically to back an HTML report template's `{{
resource('theme.css') }}` references (see ../html_template.py) — the
other half of "point an uploaded template's href/src at a Resources
file," alongside images.py for `<img>`.
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from .. import audit, db, projects, resource_usage, style_compile, stylesheet_store
from ..auth import ensure_org_scope, get_current_user
from ..models import ResourceUpdate, ResourceUsage, StylesheetOut
from ..rbac import AuthContext, can_manage_folder_contents, can_view_folder_contents

router = APIRouter(prefix="/api/v1/stylesheets", tags=["stylesheets"])


def _to_out(meta: dict) -> StylesheetOut:
    return StylesheetOut(**meta)


@router.post("", summary="Upload a stylesheet into the Resources library", response_model=StylesheetOut)
async def upload_stylesheet(
    request: Request,
    file: UploadFile = File(..., description="A .css, .scss, .sass or .less file -- compiled to CSS on upload"),
    name: str = Form(..., description="Display name for this stylesheet"),
    source_format: str | None = Form(None, description="css | scss | sass | less; omitted: from the file's extension"),
    org_id: str = Form(...),
    folder_id: str | None = Form(None, description="Omit to place it at the organization root"),
    context: AuthContext = Depends(get_current_user),
) -> StylesheetOut:
    ensure_org_scope(context, org_id)
    content = await file.read()

    with db.SessionLocal() as session:
        if folder_id is not None:
            folder = session.get(db.Folder, folder_id)
            if folder is None:
                raise HTTPException(status_code=404, detail="Folder not found")
            if folder.org_id != org_id:
                raise HTTPException(status_code=400, detail="Folder belongs to a different organization")
        if not can_manage_folder_contents(session, context, folder_id):
            raise HTTPException(status_code=403, detail="Missing 'manage' access on the destination folder")

    try:
        fmt = style_compile.format_of(file.filename, source_format)
        created = stylesheet_store.create_stylesheet(
            name=name,
            content=content,
            org_id=org_id,
            folder_id=folder_id,
            created_by=context.user.id if context.user else None,
            source_format=fmt,
        )
    except style_compile.StyleCompileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except stylesheet_store.InvalidStylesheetError as exc:
        raise HTTPException(status_code=400, detail=f"Uploaded file is not a valid stylesheet: {exc}") from exc
    audit.record(
        audit.Actor.of(context, request), "stylesheet.upload", "stylesheet", created["id"],
        label=created["name"], org_id=org_id, summary=f'Uploaded stylesheet "{created["name"]}"',
        details={"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
                 "original_filename": file.filename, "folder_id": folder_id, "format": fmt},
    )
    # The same file already here (by content, whatever its name): said, so the uploader can use that one instead of
    # keeping two copies -- only ones they can see.
    with db.SessionLocal() as session:
        same = [
            {"id": d["id"], "name": d["name"], "where": projects.folder_path(session, d["folder_id"])}
            for d in stylesheet_store.with_content(org_id, created["sha256"])
            if d["id"] != created["id"] and can_view_folder_contents(session, context, d["folder_id"])
        ]
    return _to_out({**created, "duplicates": same})


@router.get("", summary="List stylesheets visible to the caller", response_model=list[StylesheetOut])
def list_stylesheets(
    org_id: str | None = Query(None, description="Superusers may omit this to list every org's stylesheets"),
    folder_id: str | None = Query(None),
    context: AuthContext = Depends(get_current_user),
) -> list[StylesheetOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    rows = stylesheet_store.list_stylesheets(org_id=org_id, folder_id=folder_id)
    if context.is_superuser or context.has_permission("folder:manage"):
        return [_to_out(r) for r in rows]

    with db.SessionLocal() as session:
        return [_to_out(r) for r in rows if can_view_folder_contents(session, context, r["folder_id"])]


@router.get("/{stylesheet_id}", summary="Get one stylesheet's metadata", response_model=StylesheetOut)
def get_stylesheet(stylesheet_id: str, context: AuthContext = Depends(get_current_user)) -> StylesheetOut:
    try:
        meta = stylesheet_store.get_stylesheet(stylesheet_id)
    except stylesheet_store.StylesheetNotFoundError:
        raise HTTPException(status_code=404, detail="Stylesheet not found")
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Stylesheet not found")
    return _to_out(meta)


@router.get("/{stylesheet_id}/file", summary="Get one stylesheet's raw CSS text (for a preview)")
def get_stylesheet_file(stylesheet_id: str, context: AuthContext = Depends(get_current_user)) -> Response:
    try:
        meta = stylesheet_store.get_stylesheet(stylesheet_id)
    except stylesheet_store.StylesheetNotFoundError:
        raise HTTPException(status_code=404, detail="Stylesheet not found")
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Stylesheet not found")
    content = stylesheet_store.get_stylesheet_bytes(stylesheet_id)
    return Response(content=content, media_type="text/css")


@router.get("/{stylesheet_id}/source", summary="What was uploaded: the SCSS / Sass / Less source (or the CSS itself)")
def get_stylesheet_source(stylesheet_id: str, context: AuthContext = Depends(get_current_user)) -> Response:
    meta = _visible(stylesheet_id, context)
    content, fmt = stylesheet_store.get_stylesheet_source(stylesheet_id)
    filename = f"{meta['name']}.{fmt}"
    return Response(content=content, media_type="text/plain; charset=utf-8" if fmt != "css" else "text/css",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@router.put("/{stylesheet_id}/file", summary="Replace a stylesheet's content (any format) -- templates using it change too", response_model=StylesheetOut)
async def replace_stylesheet(
    stylesheet_id: str,
    request: Request,
    file: UploadFile = File(..., description="A .css, .scss, .sass or .less file"),
    source_format: str | None = Form(None, description="css | scss | sass | less; omitted: from the file's extension"),
    context: AuthContext = Depends(get_current_user),
) -> StylesheetOut:
    meta = _visible(stylesheet_id, context)
    with db.SessionLocal() as session:
        if not can_manage_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=403, detail="Missing 'manage' access on this stylesheet's folder")
    content = await file.read()
    try:
        fmt = style_compile.format_of(file.filename, source_format)
        updated = stylesheet_store.replace_stylesheet_content(stylesheet_id, content, fmt)
    except style_compile.StyleCompileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except stylesheet_store.InvalidStylesheetError as exc:
        raise HTTPException(status_code=400, detail=f"Not a valid stylesheet: {exc}") from exc
    audit.record(
        audit.Actor.of(context, request), "stylesheet.replace", "stylesheet", stylesheet_id,
        label=meta["name"], org_id=meta["org_id"], summary=f'Replaced stylesheet "{meta["name"]}" ({style_compile.LABELS[fmt]})',
        details={"sha256": updated["sha256"], "format": fmt, "previous_format": meta.get("source_format")},
    )
    return _to_out(updated)


def _visible(stylesheet_id: str, context: AuthContext) -> dict:
    try:
        meta = stylesheet_store.get_stylesheet(stylesheet_id)
    except stylesheet_store.StylesheetNotFoundError:
        raise HTTPException(status_code=404, detail="Stylesheet not found")
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Stylesheet not found")
    return meta


@router.delete("/{stylesheet_id}", status_code=204, summary="Delete a stylesheet")
def delete_stylesheet(stylesheet_id: str, request: Request, context: AuthContext = Depends(get_current_user)) -> None:
    try:
        meta = stylesheet_store.get_stylesheet(stylesheet_id)
    except stylesheet_store.StylesheetNotFoundError:
        raise HTTPException(status_code=404, detail="Stylesheet not found")
    with db.SessionLocal() as session:
        if not can_manage_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=403, detail="Missing 'manage' access on this stylesheet's folder")
    stylesheet_store.delete_stylesheet(stylesheet_id)
    audit.record(
        audit.Actor.of(context, request), "stylesheet.delete", "stylesheet", stylesheet_id,
        label=meta["name"], org_id=meta["org_id"], summary=f'Deleted stylesheet "{meta["name"]}"',
        details={"size_bytes": meta.get("size_bytes"), "folder_id": meta["folder_id"]},
    )


def _check_move(session, context: AuthContext, meta: dict, body: ResourceUpdate) -> None:
    """Moving needs manage on the folder it leaves and the one it goes to (same organization)."""
    if not can_manage_folder_contents(session, context, meta["folder_id"]):
        raise HTTPException(status_code=403, detail="Missing 'manage' access on this stylesheet's folder")
    if "folder_id" in body.model_fields_set and body.folder_id is not None:
        folder = session.get(db.Folder, body.folder_id)
        if folder is None or folder.org_id != meta["org_id"]:
            raise HTTPException(status_code=404, detail="Folder not found")
    if "folder_id" in body.model_fields_set and not can_manage_folder_contents(session, context, body.folder_id):
        raise HTTPException(status_code=403, detail="Missing 'manage' access on the destination folder")


@router.patch("/{stylesheet_id}", summary="Rename or move a stylesheet (its id, and every template using it, stay the same)", response_model=StylesheetOut)
def update_stylesheet(stylesheet_id: str, body: ResourceUpdate, request: Request, context: AuthContext = Depends(get_current_user)) -> StylesheetOut:
    try:
        meta = stylesheet_store.get_stylesheet(stylesheet_id)
    except stylesheet_store.StylesheetNotFoundError:
        raise HTTPException(status_code=404, detail="Stylesheet not found")
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Stylesheet not found")
        _check_move(session, context, meta, body)
        where_to = projects.folder_path(session, body.folder_id) if "folder_id" in body.model_fields_set else None
    kwargs = {"name": body.name.strip() if body.name else None}
    if "folder_id" in body.model_fields_set:
        kwargs["folder_id"] = body.folder_id
    updated = stylesheet_store.update_stylesheet_meta(stylesheet_id, **kwargs)
    changes = [c for c in (
        {"field": "name", "before": meta["name"], "after": updated["name"]} if updated["name"] != meta["name"] else None,
        {"field": "folder_id", "before": meta["folder_id"], "after": updated["folder_id"]} if updated["folder_id"] != meta["folder_id"] else None,
    ) if c]
    if changes:
        audit.record(
            audit.Actor.of(context, request), "stylesheet.update", "stylesheet", stylesheet_id, label=updated["name"], org_id=meta["org_id"],
            summary=f'{"Moved" if where_to else "Renamed"} stylesheet "{updated["name"]}"' + (f" to {where_to}" if where_to else ""), changes=changes,
        )
    return _to_out(updated)


@router.get("/{stylesheet_id}/usage", summary="The templates that use this stylesheet", response_model=list[ResourceUsage])
def stylesheet_usage(stylesheet_id: str, context: AuthContext = Depends(get_current_user)) -> list[ResourceUsage]:
    try:
        meta = stylesheet_store.get_stylesheet(stylesheet_id)
    except stylesheet_store.StylesheetNotFoundError:
        raise HTTPException(status_code=404, detail="Stylesheet not found")
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Stylesheet not found")
    return [ResourceUsage(**u) for u in resource_usage.used_by("stylesheet", stylesheet_id, meta["org_id"])]
