"""Authentication + authorization for the administrative surface of the
reports API (the template management portal and the mutating /reports
routes it drives, plus the organizations/users/roles/grants routes).

**People sign in once and then carry a short-lived access token** (app/auth_tokens.py):
`POST /api/v1/auth/login` checks the password (and a 2FA code), opens a session, and returns a
JWT access token plus a rotating refresh token in an HttpOnly cookie. Every other route
accepts `Authorization: Bearer <access token>`; this module turns it into an AuthContext --
checking the signature and expiry, that the *session* hasn't been revoked, and re-reading the
user and their permissions from the database, so a role change or a revoked session applies on
the very next request.

**HTTP Basic is still accepted, for scripts** (`curl -u user:password`): the credential is an
explicit header the client attaches, not an ambient cookie, so there's no CSRF surface either
way. Two limits keep it from undermining the sign-in flow: an account with two-factor
authentication can't use it (a script can't supply the code -- give the script its own service
account, or sign in through /auth/login), and `AUTH_ALLOW_BASIC=false` turns it off altogether.

Two kinds of identity, whichever way they authenticate:

1. **Break-glass superuser** -- PORTAL_USERNAME/PORTAL_PASSWORD env vars,
   the only mechanism that existed before this module grew a database
   backend. Kept specifically to avoid the chicken-and-egg problem of
   needing an admin account to create the very first admin account; a
   break-glass match always resolves to every permission, in every org.
2. **Database user** (app/db.py's User, app/rbac.py's grant tables) --
   `local` users are checked against a bcrypt hash (app/security.py);
   `ldap` users are checked against a directory (app/auth_ldap.py) --
   bind method, server, and group-to-role mapping all come from that
   user's organization's LdapConfig. (A directory is consulted when someone
   *signs in*, not on every request: a user removed from the directory keeps
   working until their session ends or an administrator disables the account.)

A database user flagged `must_change_password` (set on admin-created
accounts and by every admin reset -- see routers/users.py) authenticates
fine but is then refused everywhere with `403 PASSWORD_CHANGE_REQUIRED`,
except the places they need to get out of that state: /auth/login, /auth/refresh
and /auth/verify (so the portal learns of it), and GET/PATCH /users/me (read the
profile, choose a new password). That gate lives in get_current_user below -- the
dependency every protected route already uses -- rather than in the
portal, so it holds for a caller using the API directly too. 403 rather
than 401 on purpose: the credential was right, and the portal treats a
401 as "refresh, or signed out".

A deactivated or locked account is refused at sign-in and, because every request
re-reads the user, on the next request of a session that was already open.

"Not configured at all" (fails closed, 503) now means neither mechanism
is available: no break-glass env vars *and* zero users exist in the
database. Once at least one of those is true, an unmatched/wrong
credential is a normal 401, not 503 -- unconfigured and merely-wrong are
different failure modes and callers should be able to tell them apart.
"""
from __future__ import annotations

import logging
import os
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer

from . import auth_tokens, db
from .auth_events import client_ip
from .auth_ldap import attempt_ldap_login
from .rbac import (
    AuthContext,
    any_user_exists,
    find_user_for_login,
    system_admin_exists,
    get_effective_permissions,
    has_folder_access,
    has_report_access,
    user_holds_system_admin_role,
)
from .security import verify_password
from .security_events import record_access_denied

# auto_error off: a request may carry either scheme (or neither), and which one is
# decided in get_current_user_allowing_password_change below.
_basic = HTTPBasic(auto_error=False, description="A username and password on every call -- for scripts. Accounts with 2FA can't use it.")
_bearer = HTTPBearer(auto_error=False, description="The access token from POST /api/v1/auth/login")
_log = logging.getLogger("aksor_khmer_bi.auth")

# Sentinel `detail` the portal matches on (api.ts's PASSWORD_CHANGE_REQUIRED)
# to show the change-password screen instead of a generic "forbidden".
PASSWORD_CHANGE_REQUIRED_DETAIL = "PASSWORD_CHANGE_REQUIRED"


def _break_glass_credentials() -> tuple[str, str] | None:
    expected_username = os.environ.get("PORTAL_USERNAME")
    expected_password = os.environ.get("PORTAL_PASSWORD")
    if not expected_username or not expected_password:
        return None
    return expected_username, expected_password


def resolve_auth_context(credentials: HTTPBasicCredentials) -> AuthContext:
    """Resolve `credentials` to an AuthContext: break-glass superuser,
    else a database user with their effective (expiry-filtered)
    permission set, else 401/503 as described in the module docstring.

    A plain function (not a FastAPI dependency itself) so routers/auth.py's
    /auth/verify can call it directly and wrap it in its own try/except --
    that's where sign-in attempts get logged (see app/auth_events.py),
    deliberately not here, since get_current_user below runs on every
    single authenticated request and logging there would flood the audit
    trail with one row per API call instead of one per sign-in.
    """
    break_glass = _break_glass_credentials()
    with db.SessionLocal() as session:
        user = find_user_for_login(session, credentials.username)
        if break_glass is not None:
            expected_username, expected_password = break_glass
            # compare_digest on both independently (not the tuple) to avoid
            # leaking username-correctness via early-exit timing.
            username_ok = secrets.compare_digest(credentials.username, expected_username)
            password_ok = secrets.compare_digest(credentials.password, expected_password)
            # Once a database account holds this name (the first-run setup creates it), the generated .env password
            # is retired for it: only the account's own password signs in. Recovery is a *different* PORTAL_USERNAME.
            if username_ok and password_ok and user is None:
                _log.info("Authenticated break-glass superuser username=%r", credentials.username)
                return AuthContext(username=credentials.username, is_superuser=True)

        authenticated = False

        if user is not None and user.auth_source == "local" and user.password_hash:
            authenticated = verify_password(credentials.password, user.password_hash)
        elif user is not None and user.auth_source == "ldap":
            # May commit (updates external_dn/last_login_at and syncs
            # ldap-sync role grants) -- see auth_ldap.attempt_ldap_login.
            authenticated = attempt_ldap_login(session, user, credentials.password)

        if user is not None and authenticated and user.is_locked:
            # Checked only once the password is right, so a locked account's existence isn't
            # something a wrong guess can discover -- and the person is told why, not "invalid credentials".
            _log.warning("Refused sign-in of locked account username=%r", credentials.username)
            raise HTTPException(status_code=401, detail="This account is locked -- ask an administrator to unlock it")

        if user is not None and authenticated:
            permissions = get_effective_permissions(session, user)
            is_superuser = user_holds_system_admin_role(session, user)
            _log.info(
                "Authenticated database user username=%r org_id=%r auth_source=%r superuser=%r",
                user.username,
                user.org_id,
                user.auth_source,
                is_superuser,
            )
            return AuthContext(
                username=user.username,
                is_superuser=is_superuser,
                permissions=permissions,
                user=user,
                org_id=user.org_id,
            )

        if break_glass is None and not any_user_exists(session):
            _log.warning("Rejected request: no break-glass credentials and no database users exist yet")
            raise HTTPException(
                status_code=503,
                detail="Authentication is not configured yet (set PORTAL_USERNAME/PORTAL_PASSWORD, or create a user)",
            )

    _log.warning("Rejected login attempt for username=%r", credentials.username)
    raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})


def _invalid_token() -> HTTPException:
    return HTTPException(
        status_code=401, detail="Your session has expired -- sign in again", headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
    )


def context_for_session(session, row: db.AuthSession) -> AuthContext:
    """The identity of a live session, read fresh from the database: the user must still exist, be active
    and unlocked, and their roles are looked up now -- which is how a role change, a disabled account or a
    revoked session takes effect on the next request. 401 if the account can no longer be used."""
    if row.user_id is None:
        # A break-glass session: only valid while the same env-var login is still configured.
        break_glass = _break_glass_credentials()
        if break_glass is None or row.username != break_glass[0]:
            raise _invalid_token()
        return AuthContext(username=row.username, is_superuser=True, session_id=row.id)

    user = session.get(db.User, row.user_id)
    if user is None or not user.is_active or user.is_locked:
        raise _invalid_token()
    return AuthContext(
        username=user.username,
        is_superuser=user_holds_system_admin_role(session, user),
        permissions=get_effective_permissions(session, user),
        user=user,
        org_id=user.org_id,
        session_id=row.id,
    )


def context_from_access_token(token: str) -> AuthContext:
    """The identity an access token stands for, or 401. The token proves who and which session; what that
    person may do is read fresh from the database on every call (see auth_tokens.py)."""
    try:
        claims = auth_tokens.decode_access_token(token)
    except auth_tokens.TokenError as exc:
        _log.info("Refused an access token: %s", exc.code)
        raise _invalid_token() from exc

    with db.SessionLocal() as session:
        row = auth_tokens.get_live_session(session, claims["sid"])
        if row is None:
            _log.info("Refused an access token: its session has ended")
            raise _invalid_token()
        # The token's subject must be the session's own user -- a token can't be pointed at another session.
        if claims.get("sub") != (row.user_id or "breakglass"):
            raise _invalid_token()
        return context_for_session(session, row)


def context_from_basic(credentials: HTTPBasicCredentials) -> AuthContext:
    """HTTP Basic, for scripts -- unless switched off, and never for an account that has two-factor
    authentication (a script can't supply the code; that account signs in through /auth/login)."""
    if not auth_tokens.basic_allowed():
        raise HTTPException(
            status_code=401,
            detail="Username/password authentication is turned off on this server -- sign in with POST /api/v1/auth/login",
            headers={"WWW-Authenticate": "Bearer"},
        )
    context = resolve_auth_context(credentials)
    if context.user is not None and context.user.totp_enabled:
        raise HTTPException(
            status_code=401,
            detail="This account uses two-factor authentication, so it can't authenticate with a password alone -- "
            "sign in with POST /api/v1/auth/login, or give the script its own service account",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return context


def get_current_user_allowing_password_change(
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
    basic: HTTPBasicCredentials | None = Depends(_basic),
) -> AuthContext:
    """Authenticate, but *don't* refuse an account that still has to change
    its password. Only for the endpoints that account needs in order to
    change it (GET/PATCH /users/me) -- everything else uses
    get_current_user below.

    A bearer access token wins when both are sent; with neither, a plain 401.
    """
    if bearer is not None:
        return context_from_access_token(bearer.credentials)
    if basic is not None:
        return context_from_basic(basic)
    raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def optional_auth_context(request: Request) -> AuthContext | None:
    """Who is calling, for a route that is open to everyone but shows more to a signed-in caller -- or None for
    an anonymous or unrecognised one. Never raises."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    try:
        if scheme.lower() == "bearer" and value:
            return context_from_access_token(value.strip())
        if scheme.lower() == "basic" and value:
            import base64

            username, _, password = base64.b64decode(value.strip()).decode("utf-8").partition(":")
            return context_from_basic(HTTPBasicCredentials(username=username, password=password))
    except Exception:  # noqa: BLE001 -- anonymous is the safe answer to anything unexpected
        return None
    return None


def get_current_user(context: AuthContext = Depends(get_current_user_allowing_password_change)) -> AuthContext:
    """FastAPI dependency -- every other router in the app depends on this
    (not on resolve_auth_context directly). Same as before, plus the
    must-change-password gate described in the module docstring.
    """
    if context.user is not None and context.user.must_change_password:
        _log.info("Refused request: username=%r must change their password first", context.username)
        raise HTTPException(status_code=403, detail=PASSWORD_CHANGE_REQUIRED_DETAIL)
    if setup_required(context):
        _log.info("Refused request: username=%r must finish the first-run setup first", context.username)
        raise HTTPException(status_code=403, detail=PASSWORD_CHANGE_REQUIRED_DETAIL)
    return context


# The first-run gate below. Only the test suite turns it off (tests/conftest.py): most tests sign in as the break-glass
# superuser on an empty database, which is exactly the state the gate exists for.
FIRST_RUN_SETUP = True


def setup_required(context: AuthContext) -> bool:
    """The break-glass login while no real administrator exists: its .env password was generated at install time and
    only gets you to the first-run setup (POST /auth/setup-admin), which turns it into your own administrator
    account. Until then every other route answers 403 PASSWORD_CHANGE_REQUIRED, as for any temporary password."""
    if not FIRST_RUN_SETUP or context.user is not None or not context.is_superuser:
        return False
    with db.SessionLocal() as session:
        return not system_admin_exists(session)


def require_auth(context: AuthContext = Depends(get_current_user)) -> str:
    """Backward-compatible shape for callers that only need "is this
    request authenticated at all" and the username (routers/auth.py's
    /auth/verify) -- no permission check, any successfully authenticated
    identity passes.
    """
    return context.username


def require_permission(code: str):
    """FastAPI dependency factory: authenticate, then require `code` in
    the caller's effective permission set (break-glass superusers always
    pass). Returns the full AuthContext, not just the username, so a
    route can also read `.org_id`/`.user` when it needs to scope a query
    to the caller's own organization.
    """

    def _dependency(request: Request, context: AuthContext = Depends(get_current_user)) -> AuthContext:
        if not context.has_permission(code):
            _log.warning("Permission denied: username=%r missing %r", context.username, code)
            record_access_denied(
                username=context.username,
                org_id=context.org_id,
                user_id=context.user.id if context.user else None,
                permission_code=code,
                resource=None,
                ip_address=client_ip(request),
                reason=f"Missing required permission: {code}",
            )
            raise HTTPException(status_code=403, detail=f"Missing required permission: {code}")
        return context

    return _dependency


def ensure_org_scope(context: AuthContext, org_id: str) -> None:
    """Raise 404 (not 403 -- a non-superuser caller shouldn't be able to
    tell "exists in another org" apart from "doesn't exist at all") if a
    non-superuser context's own org doesn't match `org_id`. Superusers
    (break-glass, or a database user holding the cross-org
    ROLE_ADMINISTRATOR) are exempt -- that's the point of that role.
    """
    if context.is_superuser:
        return
    if context.org_id != org_id:
        raise HTTPException(status_code=404, detail="Not found")


def require_folder_permission(level: str):
    """Like require_report_permission, but for a Resources folder
    (rbac.has_folder_access, which -- unlike report access -- inherits
    down from any ancestor folder, see that function's docstring).
    There's no global `folder:view` permission code (only `folder:manage`
    exists, since holding it already implies every finer level) -- a
    `level="view"` check is only ever satisfied by `folder:manage` or a
    folder-specific grant, never a same-named global permission.
    `folder_id` is read from the route's own path parameter, so this only
    works on routes shaped `/folders/{folder_id}/...`.
    """

    def _dependency(folder_id: str, request: Request, context: AuthContext = Depends(get_current_user)) -> AuthContext:
        if context.has_permission("folder:manage"):
            return context
        if not context.is_superuser:
            with db.SessionLocal() as session:
                if has_folder_access(session, context, folder_id, level):
                    return context
        _log.warning("Permission denied: username=%r missing folder:manage on folder_id=%r (level=%r)", context.username, folder_id, level)
        record_access_denied(
            username=context.username,
            org_id=context.org_id,
            user_id=context.user.id if context.user else None,
            permission_code="folder:manage",
            resource=folder_id,
            ip_address=client_ip(request),
            reason=f"Missing folder:manage (or a folder-specific '{level}' grant)",
        )
        raise HTTPException(
            status_code=403,
            detail=f"Missing required permission: folder:manage (or a folder-specific '{level}' grant)",
        )

    return _dependency


def require_report_permission(level: str):
    """Like require_permission("report:manage"/"report:render"/...), but
    also accepts a report-specific app/rbac.py ReportAccessGrant at `level`
    or higher as an alternative path -- lets a caller be authorized for
    exactly one report without holding the blanket `report:*` permission
    via a role. `report_id` is read from the route's own path parameter
    (FastAPI matches it by name), so this only works on routes shaped
    `/{report_id}/...`.
    """
    permission_code = f"report:{level}"

    def _dependency(report_id: str, request: Request, context: AuthContext = Depends(get_current_user)) -> AuthContext:
        if context.has_permission(permission_code):
            return context
        if not context.is_superuser:
            with db.SessionLocal() as session:
                if has_report_access(session, context, report_id, level):
                    return context
        _log.warning("Permission denied: username=%r missing %r on report_id=%r", context.username, permission_code, report_id)
        record_access_denied(
            username=context.username,
            org_id=context.org_id,
            user_id=context.user.id if context.user else None,
            permission_code=permission_code,
            resource=report_id,
            ip_address=client_ip(request),
            reason=f"Missing {permission_code} (or a report-specific '{level}' grant)",
        )
        raise HTTPException(
            status_code=403,
            detail=f"Missing required permission: {permission_code} (or a report-specific '{level}' grant)",
        )

    return _dependency
