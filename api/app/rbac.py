"""RBAC domain logic: the fixed permission catalog, the standard role
catalog and its role->permission mapping, seeding, and effective-
permission resolution (role-granted union direct-granted, both filtered
for expiry) -- see app/db.py for the table shapes this reads/writes.

Benchmarked against JasperReports Server's model (Organizations, Users,
Roles, resource ACLs, a standard role catalog) and extended in one place
Jasper doesn't cover: every grant here can optionally expire.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .db import (
    Folder,
    FolderAccessGrant,
    Organization,
    Permission,
    ReportAccessGrant,
    ReportRow,
    Role,
    RolePermission,
    User,
    UserPermissionGrant,
    UserRoleAssignment,
)

# Coarser levels satisfy a request for a finer one -- a "manage" grant on
# a report also covers anything a "render" or "view" grant would.
_REPORT_LEVEL_RANK = {"view": 0, "render": 1, "manage": 2}

# A folder isn't itself renderable, so it only needs the two tiers.
_FOLDER_LEVEL_RANK = {"view": 0, "manage": 1}

ROOT_ORG_ID = "root"
ROOT_ORG_NAME = "Root"

# Fixed catalog -- (code, description). Not user-editable at runtime;
# adding a new permission means adding a line here and a migration to
# insert it, same as adding an enum value would be.
PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("org:manage", "Create/update organizations (cross-tenant; not granted by any per-org role)"),
    ("user:manage", "Create/update/deactivate users within an organization"),
    ("role:manage", "Create/update roles and their permission grants within an organization"),
    ("report:manage", "Create/update/replace/delete report templates"),
    ("client:manage", "Create/update/delete API clients (client id + secret) and choose which reports each may run"),
    ("report:render", "Render a report against data (rendering itself stays publicly reachable by default -- see reports.py)"),
    ("report:view", "View a report template's metadata/schema"),
    ("job:manage", "Create/update/delete scheduled jobs (Phase 3)"),
    ("job:trigger", "Manually trigger a job or invoke it via the trigger API (Phase 3)"),
    ("job:view", "View job definitions and run history (Phase 3)"),
    ("settings:manage", "Manage organization-level settings, incl. LDAP configuration"),
    ("folder:manage", "Create/rename/delete Resources folders, move reports/images between them, and grant folder access"),
    ("audit:view", "View login-failure and access-denied activity, and the change audit trail (who changed what, and its before/after), across the organization"),
    ("protected_terms:manage", "Create/update/delete reusable protected term sets, and select/edit a report's own protected-terms layer"),
    ("connection:manage", "Create/update/delete reusable data connections (base URL, headers, authentication) that reports fetch their data and choice lists from"),
    ("secret:manage", "Create/rotate/revoke/delete named credentials (a connection's or data source's token or password) stored encrypted in the database"),
    ("driver:manage", "Upload, download and delete JDBC driver .jar files -- code the JDBC driver service runs, so granted separately from connection:manage"),
    ("font:manage", "Add and remove fonts under Resources > Fonts -- installed for the whole server, so every organization's documents are drawn with them"),
)

# name -> set of permission codes. ROLE_ADMINISTRATOR is handled specially
# (system-wide, gets every current and future permission -- see
# seed_system_roles) rather than listed here with an enumerated set.
_ORG_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "ROLE_ORG_ADMIN": (
        "user:manage",
        "role:manage",
        "report:manage",
        "client:manage",
        "report:render",
        "report:view",
        "job:manage",
        "job:trigger",
        "job:view",
        "settings:manage",
        "folder:manage",
        "audit:view",
        "protected_terms:manage",
        "connection:manage",
        "secret:manage",
        "driver:manage",
    ),
    "ROLE_REPORT_ADMIN": ("report:manage", "report:render", "report:view", "folder:manage", "protected_terms:manage"),
    "ROLE_REPORT_VIEWER": ("report:view", "report:render"),
    "ROLE_JOB_OPERATOR": ("job:trigger", "job:view"),
    "ROLE_USER": ("report:view",),
}

SYSTEM_ADMIN_ROLE_NAME = "ROLE_ADMINISTRATOR"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _not_expired_clause(model):
    now = _now_iso()
    return (model.expires_at.is_(None)) | (model.expires_at > now)


def seed_permissions(session: Session) -> None:
    """Insert any catalog permissions missing from the `permissions`
    table. Idempotent -- safe to call on every app startup and at the
    top of every test's fixture setup.
    """
    existing = set(session.execute(select(Permission.code)).scalars().all())
    for code, description in PERMISSIONS:
        if code not in existing:
            session.add(Permission(code=code, description=description))


def seed_system_roles(session: Session) -> None:
    """The single cross-org ROLE_ADMINISTRATOR (org_id=None), granted
    every permission in the catalog. Idempotent.
    """
    role = session.execute(
        select(Role).where(Role.org_id.is_(None), Role.name == SYSTEM_ADMIN_ROLE_NAME)
    ).scalar_one_or_none()
    if role is None:
        role = Role(
            org_id=None,
            name=SYSTEM_ADMIN_ROLE_NAME,
            description="Cross-organization superadmin -- every permission, every org.",
            is_system=True,
        )
        session.add(role)
        session.flush()

    granted = set(
        session.execute(
            select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
        ).scalars()
    )
    for code, _ in PERMISSIONS:
        if code not in granted:
            session.add(RolePermission(role_id=role.id, permission_code=code))


def seed_org_roles(session: Session, org: Organization) -> dict[str, Role]:
    """Instantiate the standard per-org role catalog for `org` (idempotent
    -- existing roles of the same name in this org are reused, not
    duplicated) and make sure each one's permission grants match
    `_ORG_ROLE_PERMISSIONS`. Returns {role_name: Role}.
    """
    roles: dict[str, Role] = {}
    for name, perm_codes in _ORG_ROLE_PERMISSIONS.items():
        role = session.execute(
            select(Role).where(Role.org_id == org.id, Role.name == name)
        ).scalar_one_or_none()
        if role is None:
            role = Role(org_id=org.id, name=name, description=f"Standard role: {name}", is_system=True)
            session.add(role)
            session.flush()
        roles[name] = role

        granted = set(
            session.execute(
                select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
            ).scalars()
        )
        for code in perm_codes:
            if code not in granted:
                session.add(RolePermission(role_id=role.id, permission_code=code))
    return roles


def get_or_create_root_org(session: Session) -> Organization:
    org = session.get(Organization, ROOT_ORG_ID)
    if org is None:
        org = Organization(id=ROOT_ORG_ID, name=ROOT_ORG_NAME, is_active=True, created_at=_now_iso())
        session.add(org)
        session.flush()
    return org


def create_organization(session: Session, org_id: str, name: str, parent_org_id: str | None = None) -> Organization:
    """Create a new organization and seed its standard role catalog in
    one step -- an org with no roles yet would make user-role assignment
    impossible, so the two always happen together.
    """
    org = Organization(id=org_id, name=name, parent_org_id=parent_org_id, is_active=True, created_at=_now_iso())
    session.add(org)
    session.flush()
    seed_org_roles(session, org)
    return org


def seed_defaults(session: Session) -> None:
    """Full bootstrap: permission catalog, the system admin role, and the
    default root organization with its standard role catalog. Called at
    API startup (main.py) and by the test fixture (conftest.py) -- both
    need the same baseline to exist before anything else can work.
    """
    seed_permissions(session)
    seed_system_roles(session)
    get_or_create_root_org(session)
    # Every organization, not just the root one: a permission added to the catalog later (a role
    # that gains it) has to reach the standard roles of organizations that already exist, or
    # their administrators silently can't use the new feature until someone edits each role.
    for org in session.execute(select(Organization)).scalars().all():
        seed_org_roles(session, org)


@dataclass
class AuthContext:
    """Resolved identity for one request -- either the env-var break-glass
    superuser (no `user` row backs it) or a real database User, always
    with an effective, expiry-filtered permission set attached.
    """

    username: str
    is_superuser: bool
    permissions: set[str] = field(default_factory=set)
    user: User | None = None
    org_id: str | None = None
    # The sign-in session this request's access token belongs to (app/auth_tokens.py); None for a
    # caller that authenticated with HTTP Basic, which has no session.
    session_id: str | None = None

    def has_permission(self, code: str) -> bool:
        return self.is_superuser or code in self.permissions


def user_holds_system_admin_role(session: Session, user: User) -> bool:
    """True if `user` currently, actively holds the cross-org
    ROLE_ADMINISTRATOR (role.org_id IS NULL) -- such a user is a real
    superuser (see AuthContext.is_superuser), not just "happens to have
    every permission code," so org-scoping checks (auth.ensure_org_scope)
    correctly treat them as exempt rather than only break-glass.
    """
    role_ids = list(
        session.execute(
            select(UserRoleAssignment.role_id).where(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.is_active.is_(True),
                _not_expired_clause(UserRoleAssignment),
            )
        ).scalars()
    )
    if not role_ids:
        return False
    return (
        session.execute(
            select(Role.id).where(Role.id.in_(role_ids), Role.org_id.is_(None), Role.name == SYSTEM_ADMIN_ROLE_NAME)
        ).scalar_one_or_none()
        is not None
    )


def get_effective_permissions(session: Session, user: User) -> set[str]:
    """Union of every permission `user` currently holds: via an
    unexpired, active role assignment, or via an unexpired, active direct
    permission grant. Break-glass superusers never reach this function --
    see AuthContext.has_permission's `is_superuser` shortcut instead.
    """
    role_ids = list(
        session.execute(
            select(UserRoleAssignment.role_id).where(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.is_active.is_(True),
                _not_expired_clause(UserRoleAssignment),
            )
        ).scalars()
    )

    permissions: set[str] = set()
    if role_ids:
        permissions |= set(
            session.execute(
                select(RolePermission.permission_code).where(RolePermission.role_id.in_(role_ids))
            ).scalars()
        )

    permissions |= set(
        session.execute(
            select(UserPermissionGrant.permission_code).where(
                UserPermissionGrant.user_id == user.id,
                UserPermissionGrant.is_active.is_(True),
                _not_expired_clause(UserPermissionGrant),
            )
        ).scalars()
    )
    return permissions


def parse_login_identifier(raw: str) -> tuple[str, str | None]:
    """Split a login identifier into (username, org_id_or_None).

    Plain `alice` looks up the username across every org (must resolve
    to exactly one active user, or authentication fails -- see
    authenticate_local_user); `alice|acme` scopes the lookup to org
    `acme` directly. Same `username|org` convention JasperReports Server
    uses for its own multi-tenant logins, for the same reason: HTTP Basic
    (and most simple login forms) only carries one identifier field, so
    disambiguating a username that exists in more than one org needs an
    escape hatch built into that one field.
    """
    if "|" in raw:
        username, org_id = raw.split("|", 1)
        return username, (org_id or None)
    return raw, None


def find_user_for_login(session: Session, raw_identifier: str) -> User | None:
    username, org_id = parse_login_identifier(raw_identifier)
    query = select(User).where(User.username == username, User.is_active.is_(True))
    if org_id is not None:
        query = query.where(User.org_id == org_id)
    matches = session.execute(query).scalars().all()
    if len(matches) != 1:
        # Zero matches (unknown user) and multiple matches (ambiguous
        # username across orgs, caller didn't disambiguate) are both
        # "can't log this identifier in" -- deliberately not distinguished
        # in the response, so a username-enumeration probe can't tell
        # which case it hit.
        return None
    return matches[0]


def _active_role_ids(session: Session, user_id: str) -> list[str]:
    return list(
        session.execute(
            select(UserRoleAssignment.role_id).where(
                UserRoleAssignment.user_id == user_id,
                UserRoleAssignment.is_active.is_(True),
                _not_expired_clause(UserRoleAssignment),
            )
        ).scalars()
    )


def _folder_ancestor_chain(session: Session, folder_id: str) -> list[str]:
    """`[folder_id, its parent, its grandparent, ...]` up to the root.
    Depth is bounded by however deep the caller actually nested folders
    (there's no separate max-depth limit), which is fine at this
    console's scale -- same N+small-work tradeoff SchedulesPage's
    per-job runs lookup already accepts.
    """
    chain = [folder_id]
    current = session.get(Folder, folder_id)
    while current is not None and current.parent_folder_id is not None:
        chain.append(current.parent_folder_id)
        current = session.get(Folder, current.parent_folder_id)
    return chain


def has_folder_access(session: Session, context: AuthContext, folder_id: str, level: str) -> bool:
    """True if `context` holds an unexpired, active folder_access_grants
    row at `level` or higher on `folder_id` *or any of its ancestors* --
    unlike Organization.parent_org_id (explicitly non-inheriting, see
    db/rbac.py's Organization docstring), folder grants deliberately
    inherit downward: granting a role "view" on "Finance" is meant to
    cover "Finance/Q1" too, the same way every real filesystem's
    permission model and JasperReports Server's own repository ACLs
    work. A grant on a *child* folder does not reach back up to its
    parent -- inheritance only flows down the tree, never up.
    """
    if context.user is None:
        return False

    role_ids = _active_role_ids(session, context.user.id)
    ancestor_ids = _folder_ancestor_chain(session, folder_id)

    is_direct_grant = (FolderAccessGrant.subject_type == "user") & (FolderAccessGrant.subject_id == context.user.id)
    is_role_grant = (FolderAccessGrant.subject_type == "role") & (FolderAccessGrant.subject_id.in_(role_ids))
    subject_clause = or_(is_direct_grant, is_role_grant) if role_ids else is_direct_grant

    grants = session.execute(
        select(FolderAccessGrant.permission_level).where(
            FolderAccessGrant.folder_id.in_(ancestor_ids),
            FolderAccessGrant.is_active.is_(True),
            _not_expired_clause(FolderAccessGrant),
            subject_clause,
        )
    ).scalars()

    required_rank = _FOLDER_LEVEL_RANK[level]
    return any(_FOLDER_LEVEL_RANK.get(granted_level, -1) >= required_rank for granted_level in grants)


def can_view_folder_contents(session: Session, context: AuthContext, folder_id: str | None) -> bool:
    """True if `context` may see a folder/report/image filed in
    `folder_id` (None means the org root). Shared by routers/folders.py
    and routers/images.py's listing endpoints.
    """
    if context.is_superuser or context.has_permission("folder:manage"):
        return True
    if folder_id is None:
        return False
    return has_folder_access(session, context, folder_id, "view")


def can_manage_folder_contents(session: Session, context: AuthContext, folder_id: str | None) -> bool:
    """True if `context` may create/move a folder/report/image *into*
    `folder_id` (None means the org root). Shared by routers/folders.py
    and routers/images.py -- root requires the global `folder:manage`
    permission, since there's no folder node above the root to hold a
    narrower grant on.
    """
    if context.is_superuser or context.has_permission("folder:manage"):
        return True
    if folder_id is None:
        return False
    return has_folder_access(session, context, folder_id, "manage")


def has_report_access(session: Session, context: AuthContext, report_id: str, level: str) -> bool:
    """True if `context` (a database-user AuthContext -- break-glass
    superusers should short-circuit before ever calling this) has an
    unexpired, active report_access_grants row for `report_id` at
    `level` or higher (directly, or via a role), OR holds a
    `has_folder_access` grant at an equivalent-or-higher level on the
    report's folder (if it's filed in one), OR -- new -- the report is
    marked `is_public` and `context` belongs to the same org (a public
    report only ever satisfies `view`, never `render`/`manage`).
    Composition is a union of every path, same as every other grant in
    this system: there are no deny-grants anywhere here, only additive
    allow-grants layered together, and this doesn't introduce the first
    one. A folder grant only satisfies report levels it has an
    equivalent for -- folder `manage` satisfies report `manage`; folder
    `view` satisfies report `view`; neither satisfies report `render`
    (a folder has no view a report doesn't already cover for
    view/manage, but "render" has no folder-level analogue, so it's
    never satisfied via a folder alone).
    """
    if context.user is None:
        return False

    role_ids = _active_role_ids(session, context.user.id)

    is_direct_grant = (ReportAccessGrant.subject_type == "user") & (ReportAccessGrant.subject_id == context.user.id)
    is_role_grant = (ReportAccessGrant.subject_type == "role") & (ReportAccessGrant.subject_id.in_(role_ids))
    subject_clause = or_(is_direct_grant, is_role_grant) if role_ids else is_direct_grant

    grants = session.execute(
        select(ReportAccessGrant.permission_level).where(
            ReportAccessGrant.report_id == report_id,
            ReportAccessGrant.is_active.is_(True),
            _not_expired_clause(ReportAccessGrant),
            subject_clause,
        )
    ).scalars()

    required_rank = _REPORT_LEVEL_RANK[level]
    if any(_REPORT_LEVEL_RANK.get(granted_level, -1) >= required_rank for granted_level in grants):
        return True

    if level in ("view", "manage"):
        report = session.get(ReportRow, report_id)
        if report is not None:
            if level == "view" and report.is_public and report.org_id == context.org_id:
                return True
            if report.folder_id is not None:
                return has_folder_access(session, context, report.folder_id, level)

    return False


def effective_parameter_limits(
    session: Session, context: AuthContext, report_id: str, parameter_names: list[str]
) -> dict[str, set[str] | None]:
    """For each of a report's filter parameters, what `context` may run it
    with: `None` = unrestricted, otherwise the set of permitted values
    (possibly empty -- fail closed).

    Same additive, no-deny philosophy as every other grant here: the limits
    of every path that lets the caller *run* the report are unioned, so any
    one unrestricted path wins.
      - a superuser, or a global `report:render` / `report:manage`
        permission, or `manage` on the report's folder (folder grants carry
        no parameter limits) -> unrestricted;
      - otherwise each active, unexpired render/manage *report* grant
        (direct or via a role) contributes: no entry for a parameter in its
        `parameter_limits` leaves that parameter unrestricted, an entry
        restricts it to those values;
      - no such grant at all -> nothing permitted (empty sets).
    view-level grants never count -- viewing isn't running.
    """
    unrestricted: dict[str, set[str] | None] = {name: None for name in parameter_names}
    if context.is_superuser or context.has_permission("report:render") or context.has_permission("report:manage"):
        return unrestricted
    if context.user is None:
        return {name: set() for name in parameter_names}

    report = session.get(ReportRow, report_id)
    if report is not None and report.folder_id is not None and has_folder_access(session, context, report.folder_id, "manage"):
        return unrestricted

    role_ids = _active_role_ids(session, context.user.id)
    is_direct_grant = (ReportAccessGrant.subject_type == "user") & (ReportAccessGrant.subject_id == context.user.id)
    is_role_grant = (ReportAccessGrant.subject_type == "role") & (ReportAccessGrant.subject_id.in_(role_ids))
    subject_clause = or_(is_direct_grant, is_role_grant) if role_ids else is_direct_grant

    grants = session.execute(
        select(ReportAccessGrant).where(
            ReportAccessGrant.report_id == report_id,
            ReportAccessGrant.is_active.is_(True),
            _not_expired_clause(ReportAccessGrant),
            ReportAccessGrant.permission_level.in_(("render", "manage")),
            subject_clause,
        )
    ).scalars().all()

    limits: dict[str, set[str] | None] = {name: set() for name in parameter_names}
    for grant in grants:
        grant_limits = grant.parameter_limits or {}
        for name in parameter_names:
            if limits[name] is None:
                continue
            allowed = grant_limits.get(name)
            if allowed is None:
                limits[name] = None
            else:
                limits[name] |= set(allowed)
    return limits


def any_user_exists(session: Session) -> bool:
    """Used to distinguish "nothing is configured yet" (503, matching the
    old single-admin-credential behavior) from "credentials just didn't
    match anything" (401) now that there are two independent ways to be
    configured (env-var break-glass, or at least one database user).
    """
    return session.execute(select(User.id).limit(1)).scalar_one_or_none() is not None
