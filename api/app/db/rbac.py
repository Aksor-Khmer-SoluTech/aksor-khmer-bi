"""Multi-tenant RBAC -- organizations, users, roles, permissions, and
three *expiring* grant tables (the part that goes beyond a normal
permanent-membership RBAC model -- see app/rbac.py for the authorization
logic that reads these).
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class Organization(Base):
    """A tenant. `parent_org_id` exists for optional future nesting but
    is not used for permission inheritance in this version -- every org
    is treated as independent regardless of `parent_org_id`.
    """

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    parent_org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class User(Base):
    """`username` is unique *within an org*, not globally -- the same
    username can exist in two different orgs (see app/rbac.py's login
    identifier resolution, which supports a `username|org_id` form to
    disambiguate, matching JasperReports Server's own multi-tenant login
    convention).
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "username", name="uq_users_org_username"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # "local" (password_hash checked here) or "ldap" (Phase 2 -- bind
    # against app/auth_ldap.py at login time instead of checking a hash).
    auth_source: Mapped[str] = mapped_column(String, nullable=False, default="local")
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set on admin-created accounts and by every admin password reset: the
    # holder must pick their own password before anything else works (see
    # app/auth.py's get_current_user, which enforces it server-side). Only
    # ever true for `local` users -- an `ldap` user's password lives in the
    # directory, so there's nothing here to force a change of.
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_dn: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    last_login_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # Personal preference (Settings > Notifications) -- gates whether a
    # new-device sign-in (see app/auth_events.py) surfaces as an in-app
    # alert. Self-service only, see UserSelfUpdate; not exposed to
    # UserUpdate/UserCreate since it's the account owner's own call.
    notify_new_signin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set by app/avatar_store.py once an avatar is uploaded (Settings >
    # Profile) -- null means "no avatar, show initials" (see
    # AccountMenu.tsx's UserAvatar). Names the *stored* re-encoded
    # format (always png or jpeg -- see avatar_store.save_avatar), not
    # whatever format the original upload came in as.
    avatar_content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # Second factor (Settings > Access) -- see app/totp.py's module
    # docstring: /auth/login asks for the code, and an account that has it
    # can't use HTTP Basic. `totp_secret` is stored encrypted (app/totp.py seal/unseal, the same Fernet
    # key as Secrets) and is written
    # (pending, totp_enabled still False) by /me/totp/enroll and only
    # takes effect once /me/totp/confirm proves the account owner
    # actually captured it. `totp_last_used_step` blocks replaying an
    # already-accepted code across enroll/confirm/login/disable.
    totp_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    totp_last_used_step: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Role(Base):
    """`org_id` is NULL only for the single system-wide `ROLE_ADMINISTRATOR`
    (a true cross-org superadmin role). Every other standard role is
    instantiated once *per organization* (see rbac.seed_org_roles) so
    that granting e.g. "ROLE_ORG_ADMIN" to a user only ever affects that
    user's own org, never every org at once.
    """

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_roles_org_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Permission(Base):
    """A fixed, code-defined catalog (see rbac.PERMISSIONS) -- not
    user-editable at runtime, so `code` itself is the primary key rather
    than a separate surrogate id.
    """

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(String, nullable=False)


class RolePermission(Base):
    """Static role -> permission map (admin-editable via the Roles API,
    unlike the permission catalog itself)."""

    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code"), primary_key=True)


class UserRoleAssignment(Base):
    """Grant table #1 -- a user holds a role, optionally only until
    `expires_at`. `is_active` lets a grant be revoked (audit trail kept)
    without deleting the row.
    """

    __tablename__ = "user_role_assignments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)
    granted_at: Mapped[str] = mapped_column(String, nullable=False)
    granted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class UserPermissionGrant(Base):
    """Grant table #2 -- a single permission granted directly to a user,
    bypassing roles entirely (e.g. a one-off, time-boxed capability that
    doesn't warrant a role membership). Same shape as UserRoleAssignment.
    """

    __tablename__ = "user_permission_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code"), nullable=False)
    granted_at: Mapped[str] = mapped_column(String, nullable=False)
    granted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ReportAccessGrant(Base):
    """Grant table #3 -- scopes a user's *or role's* access to one
    specific report, independent of their general `report:*` permissions
    -- e.g. give one user `manage` on exactly one report for 30 days,
    without granting the global `report:manage` permission via a role.
    `subject_type`/`subject_id` is polymorphic (a role or a user) rather
    than two nullable FK columns, since exactly one of the two subject
    kinds always applies and a report can be shared with a whole role at
    once (e.g. "everyone in ROLE_REPORT_VIEWER can render report X").
    """

    __tablename__ = "report_access_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    subject_type: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "role"
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.report_id"), nullable=False)
    permission_level: Mapped[str] = mapped_column(String, nullable=False)  # "view" | "render" | "manage"
    granted_at: Mapped[str] = mapped_column(String, nullable=False)
    granted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Narrows the report's filter parameters for this grant's holders:
    # {"p_branch": ["BR01", "BR07"]} means "may only run it with those
    # values". A parameter absent from the map is unrestricted by *this*
    # grant. Only meaningful at render/manage level (that's what running
    # needs) -- see rbac.effective_parameter_limits for how several grants
    # combine (a union: any unrestricted path wins).
    parameter_limits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
