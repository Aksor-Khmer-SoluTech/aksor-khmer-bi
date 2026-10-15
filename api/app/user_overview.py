"""One user, seen from the admin console: the templates they put in, the templates they can reach and how, and every
permission they hold with where it comes from. Backs GET /api/v1/users/{id}/overview (the user detail panel).

Reach is worked out with the very check the portal's own Reports page uses for that user
(routers/reports.py `_report_access_level`, run on an AuthContext built for them), so what this says they can open
is what they would really see -- never a second, drifting copy of the rules.

Templates have no owner column: "theirs" means a version they uploaded (report_versions.created_by_user_id), and
"started" means they uploaded its first version.
"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import db
from .rbac import PERMISSIONS, AuthContext, _not_expired_clause, get_effective_permissions, user_holds_system_admin_role

_DESCRIPTIONS = dict(PERMISSIONS)
_RECENT_LIMIT = 50


def _active_role_assignments(session: Session, user_id: str) -> list[tuple[db.UserRoleAssignment, db.Role]]:
    return list(
        session.execute(
            select(db.UserRoleAssignment, db.Role)
            .join(db.Role, db.Role.id == db.UserRoleAssignment.role_id)
            .where(
                db.UserRoleAssignment.user_id == user_id,
                db.UserRoleAssignment.is_active.is_(True),
                _not_expired_clause(db.UserRoleAssignment),
            )
        ).all()
    )


def user_overview(session: Session, user: db.User) -> dict:
    from .routers.reports import _report_access_level  # the Reports page's own rule; imported late (router module)

    assignments = _active_role_assignments(session, user.id)
    roles_by_id = {role.id: (role, a) for a, role in assignments}
    role_ids = list(roles_by_id)
    is_admin = user_holds_system_admin_role(session, user)
    permissions = get_effective_permissions(session, user)
    context = AuthContext(username=user.username, is_superuser=is_admin, permissions=permissions, user=user, org_id=user.org_id)

    # --- folders: full paths, for an administrator's eyes (no visibility trimming) ---
    folders = {f.id: f for f in session.execute(select(db.Folder).where(db.Folder.org_id == user.org_id)).scalars()}

    def path(folder_id: str | None) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        while folder_id and folder_id in folders and folder_id not in seen:
            seen.add(folder_id)
            names.append(folders[folder_id].name)
            folder_id = folders[folder_id].parent_folder_id
        return list(reversed(names))

    reports_q = select(db.ReportRow)
    if not is_admin:
        reports_q = reports_q.where(db.ReportRow.org_id == user.org_id)
    reports = list(session.execute(reports_q).scalars())
    by_id = {r.report_id: r for r in reports}

    # --- reach: the highest level on each template, as their Reports page would show it ---
    levels: dict[str, str | None] = {}
    for r in reports:
        level = "manage" if is_admin else _report_access_level(session, context, r.report_id)
        if r.is_draft and level != "manage":
            level = None  # a draft is only listed for the people who can finish it
        levels[r.report_id] = level
    counts = {lvl: sum(1 for v in levels.values() if v == lvl) for lvl in ("manage", "render", "view")}
    org_wide = "system administrator" if is_admin else next(
        (f"report:{lvl}" for lvl in ("manage", "render", "view") if f"report:{lvl}" in permissions), None
    )

    # --- templates they uploaded versions of ---
    mine = or_(
        db.ReportVersion.created_by_user_id == user.id,
        (db.ReportVersion.created_by_user_id.is_(None)) & (db.ReportVersion.created_by == user.username),
    )
    rows = session.execute(
        select(
            db.ReportVersion.report_id,
            func.count(db.ReportVersion.id),
            func.max(db.ReportVersion.created_at),
            func.min(db.ReportVersion.version),
        )
        .where(mine)
        .group_by(db.ReportVersion.report_id)
    ).all()
    contributed = [row for row in rows if row[0] in by_id]
    first_versions = dict(
        session.execute(
            select(db.ReportVersion.report_id, func.min(db.ReportVersion.version))
            .where(db.ReportVersion.report_id.in_([row[0] for row in contributed] or [""]))
            .group_by(db.ReportVersion.report_id)
        ).all()
    )
    templates = sorted(
        (
            {
                "report_id": report_id,
                "name": by_id[report_id].name,
                "template_ext": by_id[report_id].template_ext,
                "folder_path": path(by_id[report_id].folder_id),
                "is_draft": bool(by_id[report_id].is_draft),
                "versions": count,
                "last_upload_at": last,
                "started": first_mine == first_versions.get(report_id),
                "access_level": levels.get(report_id),
            }
            for report_id, count, last, first_mine in contributed
        ),
        key=lambda t: t["last_upload_at"] or "",
        reverse=True,
    )
    by_type: dict[str, int] = {}
    for t in templates:
        by_type[t["template_ext"]] = by_type.get(t["template_ext"], 0) + 1

    # --- every permission, with where it comes from ---
    sources: dict[str, list[dict]] = {}
    if role_ids:
        for role_id, code in session.execute(
            select(db.RolePermission.role_id, db.RolePermission.permission_code).where(db.RolePermission.role_id.in_(role_ids))
        ).all():
            role, assignment = roles_by_id[role_id]
            sources.setdefault(code, []).append({"kind": "role", "name": role.name, "expires_at": assignment.expires_at})
    for grant in session.execute(
        select(db.UserPermissionGrant).where(
            db.UserPermissionGrant.user_id == user.id,
            db.UserPermissionGrant.is_active.is_(True),
            _not_expired_clause(db.UserPermissionGrant),
        )
    ).scalars():
        sources.setdefault(grant.permission_code, []).append({"kind": "direct", "name": None, "expires_at": grant.expires_at})
    permission_list = [
        {"code": code, "description": _DESCRIPTIONS.get(code, ""), "sources": sources.get(code, [])}
        for code in sorted(permissions)
    ]

    # --- folder and template grants, to them or to one of their roles ---
    def subject_clause(model):
        direct = (model.subject_type == "user") & (model.subject_id == user.id)
        return or_(direct, (model.subject_type == "role") & (model.subject_id.in_(role_ids))) if role_ids else direct

    def via(grant) -> str | None:
        return None if grant.subject_type == "user" else roles_by_id[grant.subject_id][0].name

    def reports_under(folder_id: str) -> int:
        return sum(1 for r in reports if r.folder_id and folder_id in _chain(r.folder_id))

    chains: dict[str, set[str]] = {}

    def _chain(folder_id: str) -> set[str]:
        if folder_id not in chains:
            chain, current = set(), folder_id
            while current and current in folders and current not in chain:
                chain.add(current)
                current = folders[current].parent_folder_id
            chains[folder_id] = chain
        return chains[folder_id]

    folder_grants = [
        {
            "grant_id": g.id,
            "folder_id": g.folder_id,
            "path": path(g.folder_id),
            "is_project": bool(folders[g.folder_id].is_project) if g.folder_id in folders else False,
            "level": g.permission_level,
            "via_role": via(g),
            "expires_at": g.expires_at,
            "templates": reports_under(g.folder_id),
        }
        for g in session.execute(
            select(db.FolderAccessGrant).where(
                db.FolderAccessGrant.is_active.is_(True), _not_expired_clause(db.FolderAccessGrant), subject_clause(db.FolderAccessGrant)
            )
        ).scalars()
        if g.folder_id in folders
    ]
    report_grants = [
        {
            "grant_id": g.id,
            "report_id": g.report_id,
            "name": by_id[g.report_id].name,
            "template_ext": by_id[g.report_id].template_ext,
            "level": g.permission_level,
            "via_role": via(g),
            "expires_at": g.expires_at,
            "parameter_limits": g.parameter_limits or None,
        }
        for g in session.execute(
            select(db.ReportAccessGrant).where(
                db.ReportAccessGrant.is_active.is_(True), _not_expired_clause(db.ReportAccessGrant), subject_clause(db.ReportAccessGrant)
            )
        ).scalars()
        if g.report_id in by_id
    ]

    return {
        "user_id": user.id,
        "is_system_admin": is_admin,
        "roles": sorted(
            ({"name": role.name, "expires_at": a.expires_at} for role, a in roles_by_id.values()), key=lambda r: r["name"]
        ),
        "templates": {
            "contributed": len(templates),
            "started": sum(1 for t in templates if t["started"]),
            "versions": sum(t["versions"] for t in templates),
            "by_type": by_type,
            "items": templates[:_RECENT_LIMIT],
        },
        "reach": {"total": len(reports), "org_wide": org_wide, **counts},
        "permissions": permission_list,
        "folder_grants": sorted(folder_grants, key=lambda g: "/".join(g["path"]).lower()),
        "report_grants": sorted(report_grants, key=lambda g: g["name"].lower()),
    }
