"""Expiring access grants -- the part of this project's RBAC that goes
beyond JasperReports Server's permanent-membership model: a role, a
direct permission, or access to one specific report can each be granted
to a user with an optional `expires_at`, after which the grant simply
stops counting (app/rbac.py's expiry-filtered queries), no cleanup
required for correctness. See app/db.py for the three underlying tables.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from .. import audit, db, report_data
from ..auth import ensure_org_scope, get_current_user, require_permission
from ..models import AccessReviewGrant, FolderGrantCreate, GrantOut, PermissionGrantCreate, ReportGrantCreate, RoleGrantCreate
from ..rbac import PERMISSIONS, AuthContext

router = APIRouter(prefix="/api/v1/grants", tags=["grants"])

_VALID_PERMISSION_CODES = {code for code, _ in PERMISSIONS}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _role_grant_out(row: db.UserRoleAssignment) -> GrantOut:
    return GrantOut(
        id=row.id,
        granted_at=row.granted_at,
        granted_by=row.granted_by,
        expires_at=row.expires_at,
        is_active=row.is_active,
        user_id=row.user_id,
        role_id=row.role_id,
    )


def _permission_grant_out(row: db.UserPermissionGrant) -> GrantOut:
    return GrantOut(
        id=row.id,
        granted_at=row.granted_at,
        granted_by=row.granted_by,
        expires_at=row.expires_at,
        is_active=row.is_active,
        user_id=row.user_id,
        permission_code=row.permission_code,
    )


def _report_grant_out(row: db.ReportAccessGrant) -> GrantOut:
    return GrantOut(
        id=row.id,
        granted_at=row.granted_at,
        granted_by=row.granted_by,
        expires_at=row.expires_at,
        is_active=row.is_active,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        report_id=row.report_id,
        permission_level=row.permission_level,
        parameter_limits=row.parameter_limits,
    )


def _validate_parameter_limits(report: db.ReportRow, level: str, limits: dict[str, list[str]]) -> dict[str, list[str]]:
    """Reject anything that would silently do the wrong thing: limits on a
    grant that can't run the report, a parameter the report doesn't have
    (or one with neither a static option list nor an options_source, so
    there's nothing to narrow), a value that isn't one of its *static*
    options (a typo would lock the user out with no hint why), or an
    empty list (also a lockout -- to leave a parameter unrestricted,
    omit it).

    A parameter with `options_source` skips the "is this a real option"
    check: its option list is only known by fetching it, and grant
    creation shouldn't depend on a third-party API being reachable (same
    reasoning `PUT /data-config` doesn't probe `data_source`/
    `options_source` live either -- see app/report_data.py). Membership
    is still enforced for real, every time, at run-form/run
    (`report_data.resolve_parameter_definitions` fetches the live list
    before `effective_parameter_limits`'s narrowing or
    `resolve_run_parameters`'s check ever runs) -- this only loses the
    early, friendly typo-catch for the dynamic case, not any actual
    enforcement.
    """
    if not limits:
        return {}
    if level not in ("render", "manage"):
        raise HTTPException(status_code=400, detail="Parameter limits only apply to render or manage grants")
    defined = {p["name"]: p for p in (report.parameters or [])}
    cleaned: dict[str, list[str]] = {}
    for name, values in limits.items():
        definition = defined.get(name)
        if definition is None:
            raise HTTPException(status_code=400, detail=f"{name!r} isn't a filter parameter of this report")
        options = definition.get("options")
        dynamic = definition.get("options_source") is not None
        if options is None and not dynamic:
            raise HTTPException(status_code=400, detail=f"{name!r} has no option list, so it can't be limited")
        if not values:
            raise HTTPException(
                status_code=400,
                detail=f"The limit for {name!r} is empty, which would allow nothing -- leave it out to keep it unrestricted",
            )
        if options is not None:
            valid = {o["value"] for o in options}
            unknown = sorted(set(values) - valid)
            if unknown:
                raise HTTPException(status_code=400, detail=f"Not an option of {name!r}: {', '.join(unknown)}")
        else:
            for value in values:
                if not value.strip() or len(value) > report_data.MAX_VALUE_LENGTH:
                    raise HTTPException(status_code=400, detail=f"An invalid value was given for {name!r}")
        cleaned[name] = sorted(set(values))
    return cleaned


def _folder_grant_out(row: db.FolderAccessGrant) -> GrantOut:
    return GrantOut(
        id=row.id,
        granted_at=row.granted_at,
        granted_by=row.granted_by,
        expires_at=row.expires_at,
        is_active=row.is_active,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        folder_id=row.folder_id,
        permission_level=row.permission_level,
    )


def _subject_name(session, subject_type: str, subject_id: str) -> str:
    """A user's username or a role's name, for an audit label -- the id if
    the subject has since gone."""
    row = session.get(db.User if subject_type == "user" else db.Role, subject_id)
    return (row.username if subject_type == "user" else row.name) if row is not None else subject_id


def _expiry_note(expires_at: str | None) -> str:
    return f" until {expires_at}" if expires_at else ""


def _resolve_user_and_scope(session, context: AuthContext, user_id: str) -> db.User:
    user = session.get(db.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    ensure_org_scope(context, user.org_id)
    return user


# --- role grants -----------------------------------------------------


@router.post("/roles", summary="Grant a role to a user, optionally until it expires", response_model=GrantOut)
def grant_role(
    body: RoleGrantCreate, request: Request, context: AuthContext = Depends(require_permission("user:manage"))
) -> GrantOut:
    with db.SessionLocal() as session:
        user = _resolve_user_and_scope(session, context, body.user_id)
        role = session.get(db.Role, body.role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        if role.org_id is not None:
            ensure_org_scope(context, role.org_id)
        elif not context.is_superuser:
            raise HTTPException(status_code=403, detail="Only a superuser can grant the system-wide ROLE_ADMINISTRATOR")

        row = db.UserRoleAssignment(
            user_id=user.id,
            role_id=role.id,
            granted_at=_now_iso(),
            granted_by=context.user.id if context.user else None,
            expires_at=body.expires_at,
            is_active=True,
        )
        session.add(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "user.role_grant", "user", user.id,
            label=user.username, org_id=user.org_id,
            summary=f"Granted role {role.name} to {user.username}{_expiry_note(row.expires_at)}",
            details={"grant_id": row.id, "role_id": role.id, "role_name": role.name, "expires_at": row.expires_at},
        )
        return _role_grant_out(row)


@router.get("/roles", summary="List a user's role grants", response_model=list[GrantOut])
def list_role_grants(
    user_id: str = Query(...), context: AuthContext = Depends(require_permission("user:manage"))
) -> list[GrantOut]:
    with db.SessionLocal() as session:
        _resolve_user_and_scope(session, context, user_id)
        rows = session.query(db.UserRoleAssignment).filter(db.UserRoleAssignment.user_id == user_id).all()
        return [_role_grant_out(row) for row in rows]


@router.delete("/roles/{grant_id}", status_code=204, summary="Revoke a role grant")
def revoke_role_grant(
    grant_id: str, request: Request, context: AuthContext = Depends(require_permission("user:manage"))
) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.UserRoleAssignment, grant_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Grant not found")
        user = session.get(db.User, row.user_id)
        if user is not None:
            ensure_org_scope(context, user.org_id)
        was_active = row.is_active
        row.is_active = False
        session.commit()
        if was_active:
            role_name = _subject_name(session, "role", row.role_id)
            username = user.username if user is not None else row.user_id
            audit.record(
                audit.Actor.of(context, request), "user.role_revoke", "user", row.user_id,
                label=username, org_id=user.org_id if user is not None else None,
                summary=f"Revoked role {role_name} from {username}",
                details={"grant_id": row.id, "role_id": row.role_id, "role_name": role_name},
            )


# --- direct permission grants -----------------------------------------


@router.post(
    "/permissions", summary="Grant a permission directly to a user, optionally until it expires", response_model=GrantOut
)
def grant_permission(
    body: PermissionGrantCreate, request: Request, context: AuthContext = Depends(require_permission("user:manage"))
) -> GrantOut:
    if body.permission_code not in _VALID_PERMISSION_CODES:
        raise HTTPException(status_code=400, detail=f"Unknown permission code: {body.permission_code!r}")
    with db.SessionLocal() as session:
        user = _resolve_user_and_scope(session, context, body.user_id)
        row = db.UserPermissionGrant(
            user_id=user.id,
            permission_code=body.permission_code,
            granted_at=_now_iso(),
            granted_by=context.user.id if context.user else None,
            expires_at=body.expires_at,
            is_active=True,
        )
        session.add(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "user.permission_grant", "user", user.id,
            label=user.username, org_id=user.org_id,
            summary=f"Granted permission {row.permission_code} to {user.username}{_expiry_note(row.expires_at)}",
            details={"grant_id": row.id, "permission_code": row.permission_code, "expires_at": row.expires_at},
        )
        return _permission_grant_out(row)


@router.get("/permissions", summary="List a user's direct permission grants", response_model=list[GrantOut])
def list_permission_grants(
    user_id: str = Query(...), context: AuthContext = Depends(require_permission("user:manage"))
) -> list[GrantOut]:
    with db.SessionLocal() as session:
        _resolve_user_and_scope(session, context, user_id)
        rows = (
            session.query(db.UserPermissionGrant).filter(db.UserPermissionGrant.user_id == user_id).all()
        )
        return [_permission_grant_out(row) for row in rows]


@router.delete("/permissions/{grant_id}", status_code=204, summary="Revoke a direct permission grant")
def revoke_permission_grant(
    grant_id: str, request: Request, context: AuthContext = Depends(require_permission("user:manage"))
) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.UserPermissionGrant, grant_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Grant not found")
        user = session.get(db.User, row.user_id)
        if user is not None:
            ensure_org_scope(context, user.org_id)
        was_active = row.is_active
        row.is_active = False
        session.commit()
        if was_active:
            username = user.username if user is not None else row.user_id
            audit.record(
                audit.Actor.of(context, request), "user.permission_revoke", "user", row.user_id,
                label=username, org_id=user.org_id if user is not None else None,
                summary=f"Revoked permission {row.permission_code} from {username}",
                details={"grant_id": row.id, "permission_code": row.permission_code},
            )


# --- report-specific access grants -------------------------------------


@router.post(
    "/reports",
    summary="Grant a user or role access to one specific report, optionally until it expires",
    response_model=GrantOut,
)
def grant_report_access(
    body: ReportGrantCreate, request: Request, context: AuthContext = Depends(require_permission("report:manage"))
) -> GrantOut:
    with db.SessionLocal() as session:
        report = session.get(db.ReportRow, body.report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        parameter_limits = _validate_parameter_limits(report, body.permission_level, body.parameter_limits or {})

        if body.subject_type == "user":
            _resolve_user_and_scope(session, context, body.subject_id)
        else:
            role = session.get(db.Role, body.subject_id)
            if role is None:
                raise HTTPException(status_code=404, detail="Role not found")
            if role.org_id is not None:
                ensure_org_scope(context, role.org_id)

        row = db.ReportAccessGrant(
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            report_id=body.report_id,
            permission_level=body.permission_level,
            granted_at=_now_iso(),
            granted_by=context.user.id if context.user else None,
            expires_at=body.expires_at,
            is_active=True,
            parameter_limits=parameter_limits or None,
        )
        session.add(row)
        session.commit()
        who = _subject_name(session, body.subject_type, body.subject_id)
        audit.record(
            audit.Actor.of(context, request), "report.access_grant", "report", report.report_id,
            label=report.name, org_id=report.org_id,
            summary=f"Granted {row.permission_level} access to {body.subject_type} {who}{_expiry_note(row.expires_at)}",
            details={
                "grant_id": row.id, "subject_type": row.subject_type, "subject_id": row.subject_id, "subject_name": who,
                "permission_level": row.permission_level, "expires_at": row.expires_at,
                "parameter_limits": row.parameter_limits,
            },
        )
        return _report_grant_out(row)


@router.get("/reports", summary="List access grants for one report", response_model=list[GrantOut])
def list_report_grants(
    report_id: str = Query(...), context: AuthContext = Depends(require_permission("report:manage"))
) -> list[GrantOut]:
    with db.SessionLocal() as session:
        if session.get(db.ReportRow, report_id) is None:
            raise HTTPException(status_code=404, detail="Report not found")
        rows = (
            session.query(db.ReportAccessGrant).filter(db.ReportAccessGrant.report_id == report_id).all()
        )
        return [_report_grant_out(row) for row in rows]


@router.delete("/reports/{grant_id}", status_code=204, summary="Revoke a report access grant")
def revoke_report_grant(
    grant_id: str, request: Request, context: AuthContext = Depends(require_permission("report:manage"))
) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.ReportAccessGrant, grant_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Grant not found")
        was_active = row.is_active
        row.is_active = False
        session.commit()
        if was_active:
            report = session.get(db.ReportRow, row.report_id)
            who = _subject_name(session, row.subject_type, row.subject_id)
            audit.record(
                audit.Actor.of(context, request), "report.access_revoke", "report", row.report_id,
                label=report.name if report is not None else None, org_id=report.org_id if report is not None else None,
                summary=f"Revoked {row.permission_level} access from {row.subject_type} {who}",
                details={
                    "grant_id": row.id, "subject_type": row.subject_type, "subject_id": row.subject_id,
                    "subject_name": who, "permission_level": row.permission_level,
                },
            )


# --- folder-specific access grants --------------------------------------

# Deliberately `require_permission("folder:manage")` (global), same as
# grant_report_access above requires global `report:manage` rather than
# a report-specific grant -- creating a *grant* is administration of the
# whole access-control system, not "management of one folder's own
# contents," so it stays gated by the blanket permission rather than a
# narrower has_folder_access("manage") check. Letting a folder-scoped
# manager hand out grants on their own folder would be a privilege-
# escalation surface (nothing stops them fabricating a grant on a
# sibling folder they don't otherwise manage), matching why reports work
# the same way.


@router.post(
    "/folders",
    summary="Grant a user or role access to one Resources folder (and everything nested under it)",
    response_model=GrantOut,
)
def grant_folder_access(
    body: FolderGrantCreate, request: Request, context: AuthContext = Depends(require_permission("folder:manage"))
) -> GrantOut:
    with db.SessionLocal() as session:
        folder = session.get(db.Folder, body.folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")

        if body.subject_type == "user":
            _resolve_user_and_scope(session, context, body.subject_id)
        else:
            role = session.get(db.Role, body.subject_id)
            if role is None:
                raise HTTPException(status_code=404, detail="Role not found")
            if role.org_id is not None:
                ensure_org_scope(context, role.org_id)

        row = db.FolderAccessGrant(
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            folder_id=body.folder_id,
            permission_level=body.permission_level,
            granted_at=_now_iso(),
            granted_by=context.user.id if context.user else None,
            expires_at=body.expires_at,
            is_active=True,
        )
        session.add(row)
        session.commit()
        who = _subject_name(session, body.subject_type, body.subject_id)
        audit.record(
            audit.Actor.of(context, request), "folder.access_grant", "folder", folder.id,
            label=folder.name, org_id=folder.org_id,
            summary=f"Granted {row.permission_level} access to {body.subject_type} {who}{_expiry_note(row.expires_at)}",
            details={
                "grant_id": row.id, "subject_type": row.subject_type, "subject_id": row.subject_id, "subject_name": who,
                "permission_level": row.permission_level, "expires_at": row.expires_at,
            },
        )
        return _folder_grant_out(row)


@router.get("/folders", summary="List access grants for one folder", response_model=list[GrantOut])
def list_folder_grants(
    folder_id: str = Query(...), context: AuthContext = Depends(require_permission("folder:manage"))
) -> list[GrantOut]:
    with db.SessionLocal() as session:
        if session.get(db.Folder, folder_id) is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        rows = session.query(db.FolderAccessGrant).filter(db.FolderAccessGrant.folder_id == folder_id).all()
        return [_folder_grant_out(row) for row in rows]


@router.delete("/folders/{grant_id}", status_code=204, summary="Revoke a folder access grant")
def revoke_folder_grant(
    grant_id: str, request: Request, context: AuthContext = Depends(require_permission("folder:manage"))
) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.FolderAccessGrant, grant_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Grant not found")
        was_active = row.is_active
        row.is_active = False
        session.commit()
        if was_active:
            folder = session.get(db.Folder, row.folder_id)
            who = _subject_name(session, row.subject_type, row.subject_id)
            audit.record(
                audit.Actor.of(context, request), "folder.access_revoke", "folder", row.folder_id,
                label=folder.name if folder is not None else None, org_id=folder.org_id if folder is not None else None,
                summary=f"Revoked {row.permission_level} access from {row.subject_type} {who}",
                details={
                    "grant_id": row.id, "subject_type": row.subject_type, "subject_id": row.subject_id,
                    "subject_name": who, "permission_level": row.permission_level,
                },
            )


# --- aggregate access review --------------------------------------------

# GET /grants/reports and GET /grants/folders above both require a
# scoping id -- there's no way to see "every grant across the org" in one
# call. This is the first aggregate view, backing the admin Access Review
# page. Gated on *either* report:manage or folder:manage (not a single
# blanket permission) since a custom role can hold just one of the two --
# requiring both would under-expose a caller who legitimately manages
# only folders (or only reports); requiring only one would over-expose
# the other category to someone who can't otherwise see it. Each grant
# category is included only if the caller actually holds that category's
# own permission, mirroring the existing per-resource gates rather than
# loosening them.


@router.get(
    "/access-review",
    summary="Every active report and folder access grant the caller may review, with names resolved server-side",
    response_model=list[AccessReviewGrant],
)
def list_access_review_grants(
    org_id: str | None = Query(None, description="Superusers may omit this to see every organization's grants"),
    context: AuthContext = Depends(get_current_user),
) -> list[AccessReviewGrant]:
    can_see_reports = context.has_permission("report:manage")
    can_see_folders = context.has_permission("folder:manage")
    if not (can_see_reports or can_see_folders):
        raise HTTPException(status_code=403, detail="Missing required permission: report:manage or folder:manage")

    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    results: list[AccessReviewGrant] = []
    with db.SessionLocal() as session:
        users_by_id = {u.id: u for u in session.execute(select(db.User)).scalars()}
        roles_by_id = {r.id: r for r in session.execute(select(db.Role)).scalars()}

        def _subject_name(subject_type: str, subject_id: str) -> str:
            if subject_type == "user":
                u = users_by_id.get(subject_id)
                return u.username if u else subject_id
            r = roles_by_id.get(subject_id)
            return r.name if r else subject_id

        def _granted_by_name(user_id: str | None) -> str | None:
            u = users_by_id.get(user_id) if user_id else None
            return u.username if u else None

        if can_see_reports:
            query = select(db.ReportAccessGrant, db.ReportRow.name, db.ReportRow.org_id).join(
                db.ReportRow, db.ReportRow.report_id == db.ReportAccessGrant.report_id
            ).where(db.ReportAccessGrant.is_active.is_(True))
            if org_id is not None:
                query = query.where(db.ReportRow.org_id == org_id)
            for grant, report_name, report_org_id in session.execute(query).all():
                results.append(
                    AccessReviewGrant(
                        id=grant.id,
                        grant_type="report",
                        subject_type=grant.subject_type,
                        subject_id=grant.subject_id,
                        subject_name=_subject_name(grant.subject_type, grant.subject_id),
                        resource_id=grant.report_id,
                        resource_name=report_name,
                        org_id=report_org_id,
                        permission_level=grant.permission_level,
                        granted_at=grant.granted_at,
                        granted_by=grant.granted_by,
                        granted_by_name=_granted_by_name(grant.granted_by),
                        expires_at=grant.expires_at,
                        parameter_limits=grant.parameter_limits,
                    )
                )

        if can_see_folders:
            query = select(db.FolderAccessGrant, db.Folder.name, db.Folder.org_id).join(
                db.Folder, db.Folder.id == db.FolderAccessGrant.folder_id
            ).where(db.FolderAccessGrant.is_active.is_(True))
            if org_id is not None:
                query = query.where(db.Folder.org_id == org_id)
            for grant, folder_name, folder_org_id in session.execute(query).all():
                results.append(
                    AccessReviewGrant(
                        id=grant.id,
                        grant_type="folder",
                        subject_type=grant.subject_type,
                        subject_id=grant.subject_id,
                        subject_name=_subject_name(grant.subject_type, grant.subject_id),
                        resource_id=grant.folder_id,
                        resource_name=folder_name,
                        org_id=folder_org_id,
                        permission_level=grant.permission_level,
                        granted_at=grant.granted_at,
                        granted_by=grant.granted_by,
                        granted_by_name=_granted_by_name(grant.granted_by),
                        expires_at=grant.expires_at,
                        parameter_limits=None,
                    )
                )

    results.sort(key=lambda g: (g.resource_name.lower(), g.subject_name.lower()))
    return results
