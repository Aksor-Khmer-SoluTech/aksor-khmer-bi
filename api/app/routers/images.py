"""The image half of the Resources repository (see routers/folders.py) --
upload/list/delete images, filed in the same folder tree report
templates are. An image's visibility follows the folder it's filed in
(rbac.has_folder_access, inherited down the tree) exactly like a
folder's own visibility does; unlike reports, there's no "images stay
public" precedent to preserve here, since this is a brand-new resource
type.

Wiring an uploaded image into a *rendered* report is a separate concern,
handled by ../context_media.py (resolves a `{"image_id": ...}` context
value to bytes right before doc_engine.render()) -- this router is only
the library/CRUD side.
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from .. import audit, db, image_store
from ..auth import ensure_org_scope, get_current_user
from ..models import ImageOut
from ..rbac import AuthContext, can_manage_folder_contents, can_view_folder_contents

router = APIRouter(prefix="/api/v1/images", tags=["images"])


def _to_out(meta: dict) -> ImageOut:
    return ImageOut(**meta)


@router.post("", summary="Upload an image into the Resources library", response_model=ImageOut)
async def upload_image(
    request: Request,
    file: UploadFile = File(..., description="An image file (png/jpeg/gif/webp/...)"),
    name: str = Form(..., description="Display name for this image"),
    org_id: str = Form(...),
    folder_id: str | None = Form(None, description="Omit to place it at the organization root"),
    context: AuthContext = Depends(get_current_user),
) -> ImageOut:
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
        created = image_store.create_image(
            name=name,
            content=content,
            org_id=org_id,
            folder_id=folder_id,
            created_by=context.user.id if context.user else None,
        )
    except image_store.InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=f"Uploaded file is not a valid image: {exc}") from exc
    audit.record(
        audit.Actor.of(context, request), "image.upload", "image", created["id"],
        label=created["name"], org_id=org_id, summary=f'Uploaded image "{created["name"]}"',
        details={"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
                 "original_filename": file.filename, "folder_id": folder_id},
    )
    return _to_out(created)


@router.get("", summary="List images visible to the caller", response_model=list[ImageOut])
def list_images(
    org_id: str | None = Query(None, description="Superusers may omit this to list every org's images"),
    folder_id: str | None = Query(None),
    context: AuthContext = Depends(get_current_user),
) -> list[ImageOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    rows = image_store.list_images(org_id=org_id, folder_id=folder_id)
    if context.is_superuser or context.has_permission("folder:manage"):
        return [_to_out(r) for r in rows]

    with db.SessionLocal() as session:
        return [_to_out(r) for r in rows if can_view_folder_contents(session, context, r["folder_id"])]


@router.get("/{image_id}", summary="Get one image's metadata", response_model=ImageOut)
def get_image(image_id: str, context: AuthContext = Depends(get_current_user)) -> ImageOut:
    try:
        meta = image_store.get_image(image_id)
    except image_store.ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Image not found")
    return _to_out(meta)


@router.get("/{image_id}/file", summary="Get one image's raw bytes (for a thumbnail preview)")
def get_image_file(image_id: str, context: AuthContext = Depends(get_current_user)) -> Response:
    try:
        meta = image_store.get_image(image_id)
    except image_store.ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Image not found")
    content = image_store.get_image_bytes(image_id)
    return Response(content=content, media_type=meta["content_type"])


@router.delete("/{image_id}", status_code=204, summary="Delete an image")
def delete_image(image_id: str, request: Request, context: AuthContext = Depends(get_current_user)) -> None:
    try:
        meta = image_store.get_image(image_id)
    except image_store.ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    with db.SessionLocal() as session:
        if not can_manage_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=403, detail="Missing 'manage' access on this image's folder")
    image_store.delete_image(image_id)
    audit.record(
        audit.Actor.of(context, request), "image.delete", "image", image_id,
        label=meta["name"], org_id=meta["org_id"], summary=f'Deleted image "{meta["name"]}"',
        details={"size_bytes": meta.get("size_bytes"), "folder_id": meta["folder_id"]},
    )
