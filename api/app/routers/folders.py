"""The Resources repository: a nested folder tree for organizing report
templates and uploaded images (see routers/images.py), modeled on
JasperReports Server's own repository -- folder-scoped role/user grants
(app/db/folders.py's FolderAccessGrant, granted/revoked via
routers/grants.py's `/grants/folders` endpoints) let an admin hand out
"view" or "manage" on one folder and everything nested under it, without
touching the global `report:*`/`folder:manage` permissions. See
app/rbac.py's `has_folder_access` for why folder grants inherit down the
tree (deliberately unlike Organization.parent_org_id).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete as sa_delete, select

from .. import audit, db
from ..auth import ensure_org_scope, get_current_user, require_folder_permission
from ..models import FolderCreate, FolderOut, FolderUpdate
from ..rbac import AuthContext, can_manage_folder_contents, can_view_folder_contents

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_out(row: db.Folder) -> FolderOut:
    return FolderOut(
        id=row.id,
        org_id=row.org_id,
        parent_folder_id=row.parent_folder_id,
        name=row.name,
        description=row.description,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _check_sibling_name_free(session, org_id: str, parent_folder_id: str | None, name: str, exclude_id: str | None = None) -> None:
    query = select(db.Folder).where(
        db.Folder.org_id == org_id, db.Folder.parent_folder_id == parent_folder_id, db.Folder.name == name
    )
    if exclude_id is not None:
        query = query.where(db.Folder.id != exclude_id)
    if session.execute(query).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="A folder with this name already exists here")


@router.post("", summary="Create a folder", response_model=FolderOut)
def create_folder(body: FolderCreate, request: Request, context: AuthContext = Depends(get_current_user)) -> FolderOut:
    ensure_org_scope(context, body.org_id)
    with db.SessionLocal() as session:
        if body.parent_folder_id is not None:
            parent = session.get(db.Folder, body.parent_folder_id)
            if parent is None:
                raise HTTPException(status_code=404, detail="Parent folder not found")
            if parent.org_id != body.org_id:
                raise HTTPException(status_code=400, detail="Parent folder belongs to a different organization")
        if not can_manage_folder_contents(session, context, body.parent_folder_id):
            raise HTTPException(status_code=403, detail="Missing 'manage' access on the destination folder")

        _check_sibling_name_free(session, body.org_id, body.parent_folder_id, body.name)

        now = _now_iso()
        row = db.Folder(
            org_id=body.org_id,
            parent_folder_id=body.parent_folder_id,
            name=body.name,
            description=body.description,
            created_by=context.user.id if context.user else None,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "folder.create", "folder", row.id,
            label=row.name, org_id=row.org_id, summary=f'Created folder "{row.name}"',
            details={"parent_folder_id": row.parent_folder_id},
        )
        return _row_to_out(row)


@router.get("", summary="List folders visible to the caller", response_model=list[FolderOut])
def list_folders(
    org_id: str | None = Query(None, description="Superusers may omit this to list every org's folders"),
    context: AuthContext = Depends(get_current_user),
) -> list[FolderOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    with db.SessionLocal() as session:
        query = select(db.Folder).order_by(db.Folder.name)
        if org_id is not None:
            query = query.where(db.Folder.org_id == org_id)
        rows = session.execute(query).scalars().all()
        visible = [row for row in rows if can_view_folder_contents(session, context, row.id)]
        return [_row_to_out(row).model_copy(update={"can_manage": can_manage_folder_contents(session, context, row.id)}) for row in visible]


@router.get("/{folder_id}", summary="Get one folder", response_model=FolderOut)
def get_folder(folder_id: str, context: AuthContext = Depends(require_folder_permission("view"))) -> FolderOut:
    with db.SessionLocal() as session:
        row = session.get(db.Folder, folder_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return _row_to_out(row)


@router.patch(
    "/{folder_id}",
    summary="Rename a folder, or move it under a different parent (drag-and-drop)",
    response_model=FolderOut,
)
def update_folder(
    folder_id: str, body: FolderUpdate, request: Request, context: AuthContext = Depends(require_folder_permission("manage"))
) -> FolderOut:
    with db.SessionLocal() as session:
        row = session.get(db.Folder, folder_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        before = {"name": row.name, "description": row.description, "parent_folder_id": row.parent_folder_id}

        new_parent_id = row.parent_folder_id
        if "parent_folder_id" in body.model_fields_set:
            new_parent_id = body.parent_folder_id
            if new_parent_id == folder_id:
                raise HTTPException(status_code=400, detail="A folder cannot be its own parent")
            if new_parent_id is not None:
                new_parent = session.get(db.Folder, new_parent_id)
                if new_parent is None:
                    raise HTTPException(status_code=404, detail="Destination parent folder not found")
                if new_parent.org_id != row.org_id:
                    raise HTTPException(status_code=400, detail="Destination folder belongs to a different organization")
                # Moving a folder under its own descendant would create a
                # cycle -- walk the destination's ancestor chain and make
                # sure this folder isn't in it.
                cursor = new_parent
                while cursor is not None:
                    if cursor.id == folder_id:
                        raise HTTPException(status_code=400, detail="Cannot move a folder into one of its own subfolders")
                    cursor = session.get(db.Folder, cursor.parent_folder_id) if cursor.parent_folder_id else None
            if not can_manage_folder_contents(session, context, new_parent_id):
                raise HTTPException(status_code=403, detail="Missing 'manage' access on the destination folder")

        new_name = body.name if body.name is not None else row.name
        if new_name != row.name or new_parent_id != row.parent_folder_id:
            _check_sibling_name_free(session, row.org_id, new_parent_id, new_name, exclude_id=folder_id)

        if body.name is not None:
            row.name = body.name
        if body.description is not None:
            row.description = body.description
        row.parent_folder_id = new_parent_id
        row.updated_at = _now_iso()
        session.commit()
        changes = audit.diff(
            before, {"name": row.name, "description": row.description, "parent_folder_id": row.parent_folder_id},
            ["name", "description", "parent_folder_id"],
        )
        if changes:
            moved = any(c["field"] == "parent_folder_id" for c in changes)
            audit.record(
                audit.Actor.of(context, request), "folder.move" if moved else "folder.update", "folder", row.id,
                label=row.name, org_id=row.org_id,
                summary=f'{"Moved" if moved else "Updated"} folder "{row.name}"', changes=changes,
            )
        return _row_to_out(row)


@router.delete("/{folder_id}", status_code=204, summary="Delete an empty folder")
def delete_folder(
    folder_id: str, request: Request, context: AuthContext = Depends(require_folder_permission("manage"))
) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.Folder, folder_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Folder not found")

        has_subfolder = session.execute(select(db.Folder.id).where(db.Folder.parent_folder_id == folder_id).limit(1)).scalar_one_or_none()
        has_report = session.execute(select(db.ReportRow.report_id).where(db.ReportRow.folder_id == folder_id).limit(1)).scalar_one_or_none()
        has_image = session.execute(select(db.ImageResource.id).where(db.ImageResource.folder_id == folder_id).limit(1)).scalar_one_or_none()
        if has_subfolder or has_report or has_image:
            raise HTTPException(status_code=409, detail="Folder is not empty -- move or delete its contents first")

        # Shortcuts are only links -- the reports they point at stay where they are -- so they don't hold a
        # folder open; they go with it.
        session.execute(sa_delete(db.ReportShortcut).where(db.ReportShortcut.folder_id == folder_id))
        session.delete(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "folder.delete", "folder", folder_id,
            label=row.name, org_id=row.org_id, summary=f'Deleted folder "{row.name}"',
        )
