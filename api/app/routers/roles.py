"""Role and permission-catalog management, scoped to the caller's own
organization unless the caller is a superuser — same org-scoping model
as routers/users.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit, db
from ..auth import ensure_org_scope, get_current_user, require_permission
from ..models import PermissionOut, RoleCreate, RoleOut, RolePermissionsUpdate
from ..rbac import PERMISSIONS, AuthContext

router = APIRouter(prefix="/api/v1", tags=["roles"])


def _role_permissions(session, role_id: str) -> list[str]:
    return sorted(
        session.execute(
            select(db.RolePermission.permission_code).where(db.RolePermission.role_id == role_id)
        ).scalars()
    )


def _row_to_out(session, row: db.Role) -> RoleOut:
    return RoleOut(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        description=row.description,
        is_system=row.is_system,
        permissions=_role_permissions(session, row.id),
    )


@router.get("/permissions", summary="List the fixed permission catalog", response_model=list[PermissionOut])
def list_permissions(_: AuthContext = Depends(get_current_user)) -> list[PermissionOut]:
    return [PermissionOut(code=code, description=description) for code, description in PERMISSIONS]


@router.post("/roles", summary="Create a custom role", response_model=RoleOut)
def create_role(
    body: RoleCreate, request: Request, context: AuthContext = Depends(require_permission("role:manage"))
) -> RoleOut:
    ensure_org_scope(context, body.org_id)
    with db.SessionLocal() as session:
        if session.get(db.Organization, body.org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        row = db.Role(org_id=body.org_id, name=body.name, description=body.description, is_system=False)
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="A role with this name already exists in this organization") from exc
        audit.record(
            audit.Actor.of(context, request), "role.create", "role", row.id,
            label=row.name, org_id=row.org_id, summary=f"Created role {row.name}",
            details={"description": row.description},
        )
        return _row_to_out(session, row)


@router.get("/roles", summary="List roles", response_model=list[RoleOut])
def list_roles(
    org_id: str | None = Query(None, description="Superusers may omit this to list every org's roles"),
    context: AuthContext = Depends(get_current_user),
) -> list[RoleOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    with db.SessionLocal() as session:
        query = select(db.Role).order_by(db.Role.name)
        if org_id is not None:
            query = query.where(db.Role.org_id == org_id)
        rows = session.execute(query).scalars().all()
        return [_row_to_out(session, row) for row in rows]


@router.get("/roles/{role_id}", summary="Get one role and its permissions", response_model=RoleOut)
def get_role(role_id: str, context: AuthContext = Depends(get_current_user)) -> RoleOut:
    with db.SessionLocal() as session:
        row = session.get(db.Role, role_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Role not found")
        if row.org_id is not None:
            ensure_org_scope(context, row.org_id)
        return _row_to_out(session, row)


@router.put(
    "/roles/{role_id}/permissions",
    summary="Replace a role's permission set",
    response_model=RoleOut,
)
def set_role_permissions(
    role_id: str, body: RolePermissionsUpdate, request: Request, context: AuthContext = Depends(require_permission("role:manage"))
) -> RoleOut:
    valid_codes = {code for code, _ in PERMISSIONS}
    unknown = set(body.permissions) - valid_codes
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown permission code(s): {sorted(unknown)}")

    with db.SessionLocal() as session:
        row = session.get(db.Role, role_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Role not found")
        if row.org_id is None:
            raise HTTPException(status_code=400, detail="The system-wide ROLE_ADMINISTRATOR's permissions can't be edited")
        ensure_org_scope(context, row.org_id)

        before = _role_permissions(session, role_id)
        session.execute(db.RolePermission.__table__.delete().where(db.RolePermission.role_id == role_id))
        for code in body.permissions:
            session.add(db.RolePermission(role_id=role_id, permission_code=code))
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail="Failed to update role permissions") from exc
        after = _role_permissions(session, role_id)
        changes = audit.diff({"permissions": before}, {"permissions": after}, ["permissions"])
        if changes:
            c = changes[0]
            audit.record(
                audit.Actor.of(context, request), "role.permissions_update", "role", role_id,
                label=row.name, org_id=row.org_id,
                summary=f"Changed permissions of role {row.name} (+{c['added_count']} / −{c['removed_count']})",
                changes=changes,
            )
        return _row_to_out(session, row)


@router.delete("/roles/{role_id}", status_code=204, summary="Delete a custom role")
def delete_role(role_id: str, request: Request, context: AuthContext = Depends(require_permission("role:manage"))) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.Role, role_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Role not found")
        if row.is_system:
            raise HTTPException(status_code=400, detail="System roles can't be deleted")
        ensure_org_scope(context, row.org_id)

        active_assignments = session.execute(
            select(db.UserRoleAssignment.id).where(
                db.UserRoleAssignment.role_id == role_id, db.UserRoleAssignment.is_active.is_(True)
            )
        ).scalars().all()
        if active_assignments:
            raise HTTPException(
                status_code=400,
                detail=f"Role is still assigned to {len(active_assignments)} user(s) -- revoke those grants first",
            )

        permissions = _role_permissions(session, role_id)
        session.execute(db.RolePermission.__table__.delete().where(db.RolePermission.role_id == role_id))
        session.delete(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "role.delete", "role", role_id,
            label=row.name, org_id=row.org_id, summary=f"Deleted role {row.name}",
            details={"permissions": permissions},
        )
