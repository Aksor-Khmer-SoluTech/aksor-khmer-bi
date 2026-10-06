"""The stylesheet half of the Resources repository (see routers/folders.py
and routers/images.py, which this mirrors) -- upload/list/delete CSS
files, filed in the same folder tree report templates and images are.
Exists specifically to back an HTML report template's `{{
resource('theme.css') }}` references (see ../html_template.py) — the
other half of "point an uploaded template's href/src at a Resources
file," alongside images.py for `<img>`.
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from .. import audit, db, stylesheet_store
from ..auth import ensure_org_scope, get_current_user
from ..models import StylesheetOut
from ..rbac import AuthContext, can_manage_folder_contents, can_view_folder_contents

router = APIRouter(prefix="/api/v1/stylesheets", tags=["stylesheets"])


def _to_out(meta: dict) -> StylesheetOut:
    return StylesheetOut(**meta)


@router.post("", summary="Upload a stylesheet into the Resources library", response_model=StylesheetOut)
async def upload_stylesheet(
    request: Request,
    file: UploadFile = File(..., description="A .css file"),
    name: str = Form(..., description="Display name for this stylesheet"),
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
        created = stylesheet_store.create_stylesheet(
            name=name,
            content=content,
            org_id=org_id,
            folder_id=folder_id,
            created_by=context.user.id if context.user else None,
        )
    except stylesheet_store.InvalidStylesheetError as exc:
        raise HTTPException(status_code=400, detail=f"Uploaded file is not a valid stylesheet: {exc}") from exc
    audit.record(
        audit.Actor.of(context, request), "stylesheet.upload", "stylesheet", created["id"],
        label=created["name"], org_id=org_id, summary=f'Uploaded stylesheet "{created["name"]}"',
        details={"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
                 "original_filename": file.filename, "folder_id": folder_id},
    )
    return _to_out(created)


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
