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

from .. import audit, db, image_store, projects, resource_usage
from ..auth import ensure_org_scope, get_current_user
from ..models import ImageOut, ResourceUpdate, ResourceUsage
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
    # The same file already here (by content, whatever its name): said, so the uploader can use that one instead of
    # keeping two copies -- only ones they can see.
    with db.SessionLocal() as session:
        same = [
            {"id": d["id"], "name": d["name"], "where": projects.folder_path(session, d["folder_id"])}
            for d in image_store.with_content(org_id, created["sha256"])
            if d["id"] != created["id"] and can_view_folder_contents(session, context, d["folder_id"])
        ]
    return _to_out({**created, "duplicates": same})


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
    ensure_org_scope(context, meta["org_id"])
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
    ensure_org_scope(context, meta["org_id"])
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Image not found")
    content = image_store.get_image_bytes(image_id)
    return Response(content=content, media_type=meta["content_type"])


@router.get("/{image_id}/thumbnail", summary="A small preview of an image (for the portal's file cards)")
def get_image_thumbnail(
    image_id: str,
    request: Request,
    size: int = Query(480, description="The box it fits in, in pixels: 240 or 480"),
    context: AuthContext = Depends(get_current_user),
) -> Response:
    if size not in image_store.THUMBNAIL_SIZES:
        raise HTTPException(status_code=400, detail=f"size must be one of {', '.join(map(str, image_store.THUMBNAIL_SIZES))}")
    try:
        meta = image_store.get_image(image_id)
    except image_store.ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    ensure_org_scope(context, meta["org_id"])
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Image not found")
    try:
        content, media_type, etag = image_store.get_thumbnail(image_id, size)
    except image_store.ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    # The browser may keep it (private: it's per user), and ask again with the etag -- an unchanged picture is then a
    # 304 with no body. The etag is the content's hash, so a replaced picture is fetched fresh.
    headers = {"Cache-Control": "private, max-age=3600", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=content, media_type=media_type, headers=headers)


@router.delete("/{image_id}", status_code=204, summary="Delete an image")
def delete_image(image_id: str, request: Request, context: AuthContext = Depends(get_current_user)) -> None:
    try:
        meta = image_store.get_image(image_id)
    except image_store.ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    ensure_org_scope(context, meta["org_id"])
    with db.SessionLocal() as session:
        if not can_manage_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=403, detail="Missing 'manage' access on this image's folder")
    image_store.delete_image(image_id)
    audit.record(
        audit.Actor.of(context, request), "image.delete", "image", image_id,
        label=meta["name"], org_id=meta["org_id"], summary=f'Deleted image "{meta["name"]}"',
        details={"size_bytes": meta.get("size_bytes"), "folder_id": meta["folder_id"]},
    )


def _check_move(session, context: AuthContext, meta: dict, body: ResourceUpdate) -> None:
    """Moving needs manage on the folder it leaves and the one it goes to (same organization)."""
    if not can_manage_folder_contents(session, context, meta["folder_id"]):
        raise HTTPException(status_code=403, detail="Missing 'manage' access on this image's folder")
    if "folder_id" in body.model_fields_set and body.folder_id is not None:
        folder = session.get(db.Folder, body.folder_id)
        if folder is None or folder.org_id != meta["org_id"]:
            raise HTTPException(status_code=404, detail="Folder not found")
    if "folder_id" in body.model_fields_set and not can_manage_folder_contents(session, context, body.folder_id):
        raise HTTPException(status_code=403, detail="Missing 'manage' access on the destination folder")


@router.patch("/{image_id}", summary="Rename or move a image (its id, and every template using it, stay the same)", response_model=ImageOut)
def update_image(image_id: str, body: ResourceUpdate, request: Request, context: AuthContext = Depends(get_current_user)) -> ImageOut:
    try:
        meta = image_store.get_image(image_id)
    except image_store.ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    ensure_org_scope(context, meta["org_id"])
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Image not found")
        _check_move(session, context, meta, body)
        where_to = projects.folder_path(session, body.folder_id) if "folder_id" in body.model_fields_set else None
    kwargs = {"name": body.name.strip() if body.name else None}
    if "folder_id" in body.model_fields_set:
        kwargs["folder_id"] = body.folder_id
    updated = image_store.update_image_meta(image_id, **kwargs)
    changes = [c for c in (
        {"field": "name", "before": meta["name"], "after": updated["name"]} if updated["name"] != meta["name"] else None,
        {"field": "folder_id", "before": meta["folder_id"], "after": updated["folder_id"]} if updated["folder_id"] != meta["folder_id"] else None,
    ) if c]
    if changes:
        audit.record(
            audit.Actor.of(context, request), "image.update", "image", image_id, label=updated["name"], org_id=meta["org_id"],
            summary=f'{"Moved" if where_to else "Renamed"} image "{updated["name"]}"' + (f" to {where_to}" if where_to else ""), changes=changes,
        )
    return _to_out(updated)


@router.get("/{image_id}/usage", summary="The templates that use this image", response_model=list[ResourceUsage])
def image_usage(image_id: str, context: AuthContext = Depends(get_current_user)) -> list[ResourceUsage]:
    try:
        meta = image_store.get_image(image_id)
    except image_store.ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    ensure_org_scope(context, meta["org_id"])
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Image not found")
    return [ResourceUsage(**u) for u in resource_usage.used_by("image", image_id, meta["org_id"])]


@router.put("/{image_id}/file", summary="Replace an image's picture, keeping its id -- every template using it changes", response_model=ImageOut)
async def replace_image(image_id: str, request: Request, file: UploadFile = File(...), context: AuthContext = Depends(get_current_user)) -> ImageOut:
    try:
        meta = image_store.get_image(image_id)
    except image_store.ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    ensure_org_scope(context, meta["org_id"])
    with db.SessionLocal() as session:
        if not can_view_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=404, detail="Image not found")
        if not can_manage_folder_contents(session, context, meta["folder_id"]):
            raise HTTPException(status_code=403, detail="Missing 'manage' access on this image's folder")
    content = await file.read()
    try:
        updated = image_store.replace_image_content(image_id, content)
    except image_store.InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=f"Uploaded file is not a valid image: {exc}") from exc
    audit.record(
        audit.Actor.of(context, request), "image.replace", "image", image_id, label=meta["name"], org_id=meta["org_id"],
        summary=f'Replaced image "{meta["name"]}"', details={"sha256": updated["sha256"], "previous_sha256": meta.get("sha256"), "original_filename": file.filename},
    )
    return _to_out(updated)
