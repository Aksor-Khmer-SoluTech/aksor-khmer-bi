"""Organizations, users, roles, permissions, grants -- see app/db.py for
the underlying tables and app/rbac.py for the authorization logic these
are shaped around.
"""
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from ..security import check_password_policy

# A password being *set* (never one being presented at login -- see
# security.check_password_policy for why). Failing it is a 422 naming the
# field, like any other bad request body.
NewPassword = Annotated[str, AfterValidator(check_password_policy)]

# A person's names and address, as the New user / edit forms take them (the portal shows the same limits as
# counters -- UserFormDialog.tsx). Checked only where they are *set*: an account that already exists, or one an
# LDAP sync created, is never refused for what it already has.
USERNAME_MAX = 100  # room for a directory name in user@company.example form
EMAIL_MAX = 254  # the longest address the email standard allows
DISPLAY_NAME_MAX = 100
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_username(value: str) -> str:
    if not value.strip():
        raise ValueError("Enter a username")
    if value != value.strip():
        raise ValueError("A username can't start or end with a space")
    if "|" in value:
        # Signing in reads "name|organization" to pick between organizations (rbac.parse_login_identifier).
        raise ValueError("A username can't contain | -- it separates the name from the organization at sign-in")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("A username can't contain control characters")
    return value


def _blank_to_none(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def _check_email(value: str | None) -> str | None:
    value = _blank_to_none(value)
    if value is not None and not _EMAIL_RE.match(value):
        raise ValueError("That doesn't look like an email address (name@example.com)")
    return value


def _check_email_edit(value: str | None) -> str | None:
    # On an edit None means "unchanged" and "" means "clear it" -- keep that difference.
    if value is not None and value.strip() == "":
        return ""
    return _check_email(value)


Username = Annotated[str, Field(min_length=1, max_length=USERNAME_MAX), AfterValidator(_check_username)]
Email = Annotated[str | None, Field(max_length=EMAIL_MAX), AfterValidator(_check_email)]
DisplayName = Annotated[str | None, Field(max_length=DISPLAY_NAME_MAX), AfterValidator(_blank_to_none)]
EmailEdit = Annotated[str | None, Field(max_length=EMAIL_MAX), AfterValidator(_check_email_edit)]
DisplayNameEdit = Annotated[str | None, Field(max_length=DISPLAY_NAME_MAX), AfterValidator(lambda v: v.strip() if v is not None else None)]


class OrganizationCreate(BaseModel):
    id: str = Field(..., description="Short slug, e.g. 'acme' -- used in the 'username|org_id' login form")
    name: str
    parent_org_id: str | None = None


class OrganizationOut(BaseModel):
    id: str
    name: str
    parent_org_id: str | None = None
    is_active: bool
    created_at: str


class UserCreate(BaseModel):
    username: Username
    email: Email = None
    display_name: DisplayName = None
    auth_source: Literal["local", "ldap"] = "local"
    password: NewPassword | None = Field(
        None, description="Required when auth_source='local'; ignored (must be omitted) for 'ldap'"
    )
    must_change_password: bool = Field(
        True,
        description="The new user must choose their own password at first sign-in (everything else answers "
        "403 PASSWORD_CHANGE_REQUIRED until they do). On by default -- an admin-chosen password is a "
        "temporary one; turn it off for an account nobody signs in to interactively. Ignored for 'ldap'.",
    )


class UserUpdate(BaseModel):
    email: EmailEdit = None
    display_name: DisplayNameEdit = None
    is_active: bool | None = None
    is_locked: bool | None = None
    password: NewPassword | None = Field(
        None,
        description="Set a new password for a 'local' user. Does not touch must_change_password -- prefer "
        "POST /users/{id}/reset-password, which sets both and can generate the password.",
    )
    must_change_password: bool | None = Field(
        None,
        description="Require (true) or stop requiring (false) a password change at the user's next sign-in. "
        "Only meaningful for 'local' users; true is rejected for an 'ldap' user.",
    )
    reset_totp: bool | None = Field(
        None,
        description="Admin escape hatch (user:manage) for a lost-authenticator lockout -- clears the user's "
        "2FA enrollment entirely (they'll need to re-enroll from Settings > Access). No code/password check "
        "here since the whole point is recovering an account that can't produce a valid code any more.",
    )


class UserSelfUpdate(BaseModel):
    """Unlike UserUpdate, deliberately has no is_active/is_locked -- a
    user must not be able to unlock or reactivate themselves. Changing
    the password additionally requires current_password even though Basic
    Auth already re-proves it on every request -- a browser caches and
    auto-resends that header, so this is the one moment the caller has to
    freshly type the password they're replacing."""

    email: EmailEdit = None
    display_name: DisplayNameEdit = None
    new_password: NewPassword | None = Field(None, description="Set a new password; only valid for auth_source='local'")
    current_password: str | None = Field(None, description="Required when new_password is set")
    notify_new_signin: bool | None = Field(
        None, description="Settings > Notifications toggle -- alert in-app when a new device/location signs in"
    )


class UserOut(BaseModel):
    id: str
    org_id: str
    username: str
    email: str | None = None
    display_name: str | None = None
    auth_source: Literal["local", "ldap"]
    is_active: bool
    is_locked: bool
    created_at: str
    updated_at: str
    last_login_at: str | None = None
    notify_new_signin: bool = True
    avatar_content_type: str | None = Field(
        None, description="Set once an avatar's been uploaded (GET /users/me/avatar serves the bytes); null means show initials"
    )
    totp_enabled: bool = Field(False, description="Whether a confirmed TOTP second factor gates this account's /auth/verify")
    must_change_password: bool = Field(
        False, description="The user must choose a new password before anything else works (see UserCreate)"
    )


class PasswordResetRequest(BaseModel):
    password: NewPassword | None = Field(
        None, description="The new password. Omit to have the server generate one (returned once, in the response)"
    )
    require_change: bool = Field(
        True,
        description="Force the user to choose their own password at next sign-in. Leave on when the admin "
        "knows the password (it's temporary); turn off only when the user chose it themselves.",
    )


class PasswordResetOut(BaseModel):
    user: UserOut
    generated_password: str | None = Field(
        None,
        description="Only set when the server generated the password -- shown exactly once, never stored "
        "in readable form or written to the audit trail",
    )


class EffectivePermissions(BaseModel):
    user_id: str
    permissions: list[str]


class RoleCreate(BaseModel):
    org_id: str = Field(..., description="Organization the new role belongs to")
    name: str
    description: str | None = None


class RoleOut(BaseModel):
    id: str
    org_id: str | None
    name: str
    description: str | None = None
    is_system: bool
    permissions: list[str] = Field(default_factory=list)


class RolePermissionsUpdate(BaseModel):
    permissions: list[str] = Field(..., description="Full replacement set of permission codes for this role")


class PermissionOut(BaseModel):
    code: str
    description: str


class RoleGrantCreate(BaseModel):
    user_id: str
    role_id: str
    expires_at: str | None = Field(None, description="ISO 8601 UTC timestamp; omit for a permanent grant")


class PermissionGrantCreate(BaseModel):
    user_id: str
    permission_code: str
    expires_at: str | None = None


class ReportGrantCreate(BaseModel):
    subject_type: Literal["user", "role"]
    subject_id: str
    report_id: str
    permission_level: Literal["view", "render", "manage"]
    expires_at: str | None = None
    # e.g. {"p_branch": ["BR01", "BR07"]} -- narrows this grant's holders
    # to those values of the report's filter parameters. Only for
    # render/manage grants, and only values that exist in the parameter's
    # option list (see routers/grants.py's validation).
    parameter_limits: dict[str, list[str]] | None = None


class FolderGrantCreate(BaseModel):
    subject_type: Literal["user", "role"]
    subject_id: str
    folder_id: str
    permission_level: Literal["view", "manage"]
    expires_at: str | None = None


class GrantOut(BaseModel):
    id: str
    granted_at: str
    granted_by: str | None = None
    expires_at: str | None = None
    is_active: bool
    # Populated depending on which grant table this came from -- exactly
    # one of (role_id) / (permission_code) / (report_id + permission_level)
    # / (folder_id + permission_level) is set, matching whichever of the
    # four grant tables this row is.
    user_id: str | None = None
    role_id: str | None = None
    permission_code: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    report_id: str | None = None
    folder_id: str | None = None
    permission_level: str | None = None
    parameter_limits: dict[str, list[str]] | None = None


class AccessReviewGrant(BaseModel):
    """One row of GET /grants/access-review -- resolved server-side (names,
    not raw ids) so the console's aggregate Access Review page doesn't need
    to N+1 the way AccessTab's own client-side subjectLabel() does today.
    """

    id: str
    grant_type: Literal["report", "folder", "dataset"]
    subject_type: Literal["user", "role"]
    subject_id: str
    subject_name: str
    resource_id: str
    resource_name: str
    org_id: str
    # "run" / "build" for a dataset grant.
    permission_level: Literal["view", "render", "manage", "run", "build"]
    granted_at: str
    granted_by: str | None = None
    granted_by_name: str | None = None
    expires_at: str | None = None
    parameter_limits: dict[str, list[str]] | None = None  # report and dataset grants; always null for folder grants
