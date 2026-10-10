"""Signing in and staying signed in: the standard access-token / refresh-token flow.

* `POST /auth/login` -- user name + password (+ 2FA code, once enabled). Opens a session and
  answers with a short-lived **access token** (a JWT, sent as `Authorization: Bearer ...` on every
  other call) and sets the long-lived **refresh token** as an HttpOnly cookie scoped to /api/v1/auth.
* `POST /auth/refresh` -- trades the refresh cookie for a new access token, and rotates the cookie.
  A refresh token works once: replaying a used one revokes the whole session (app/auth_tokens.py).
* `POST /auth/logout` -- revokes the session and clears the cookie.
* `GET /auth/me`, `GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/sessions/revoke-others`
  -- who am I, and the places I'm signed in.
* `GET /auth/verify` -- the older "are these credentials valid?" check with HTTP Basic, kept for scripts.

See ../auth_tokens.py for the design and ../auth.py for how a request is authenticated afterwards.

This is also where sign-in attempts get logged (see ../auth_events.py) and where a TOTP second factor
is enforced (see ../totp.py): `/auth/login` always demands the code once an account has 2FA, and because
an account with 2FA can no longer use HTTP Basic on the other routes (../auth.py), the second factor now
guards the whole API, not just the form. `/auth/verify` keeps its older, narrower behaviour: the code is
only checked when `login=true`.

Refresh and logout are the only routes that act on a cookie, so they are the only ones a cross-site page
could try to trigger. They require a custom header (`X-Aksor-Client`, which forces a CORS preflight), an
`Origin` that is one the deployment allows (CORS_ALLOWED_ORIGINS, or this server's own), and the cookie is
`SameSite=Lax` (or Strict) -- three independent barriers.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select

from .. import audit, auth_tokens, db, totp
from ..auth import context_for_session, get_current_user, get_current_user_allowing_password_change, resolve_auth_context, setup_required
from ..auth_events import (
    DEVICE_COOKIE,
    DEVICE_COOKIE_MAX_AGE,
    browser_brand,
    client_ip,
    device_hash,
    new_device_token,
    parse_user_agent,
    record_login_failure,
    record_login_success,
)
from ..models import AuthVerifyOut, LoginRequest, SessionOut, SetupAdminRequest, TokenOut
from ..rate_limit import RateLimiter
from ..rbac import ROOT_ORG_ID, SYSTEM_ADMIN_ROLE_NAME, AuthContext, find_user_for_login, get_effective_permissions, system_admin_exists
from ..security import check_password_policy, hash_password

_log = logging.getLogger("aksor_khmer_bi.auth_routes")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_security = HTTPBasic()

# Sentinel `detail` the frontend matches on to know "prompt for a 2FA
# code" rather than "the password itself was wrong" -- both are plain
# 401s, so the detail string is what tells them apart (see api.ts's
# login()).
TOTP_REQUIRED_DETAIL = "2FA_REQUIRED"

def _attempts_per_minute() -> int:
    try:
        return min(max(int(os.environ.get("LOGIN_ATTEMPTS_PER_MINUTE", "10")), 1), 1000)
    except ValueError:
        return 10


# Password guessing: sign-in attempts are throttled per (client address, user name) and, more loosely, per client
# address (many people can share one office address). In memory, so the limit is per API process; a reverse
# proxy in front is the stronger place for it.
_per_account = RateLimiter(limit=_attempts_per_minute)
_per_address = RateLimiter(limit=lambda: _attempts_per_minute() * 5)


def _throttle_sign_in(request: Request, username: str) -> None:
    address = client_ip(request) or "unknown"
    wait = _per_account.retry_after(f"{address}|{username.strip().lower()}") or _per_address.retry_after(address)
    if wait is not None:
        _log.warning("Throttled sign-in attempts from %s for %r", address, username)
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts -- wait a minute and try again",
            headers={"Retry-After": str(int(wait) + 1)},
        )


COOKIE_NAME = "aksor_refresh"
COOKIE_PATH = "/api/v1/auth"
CLIENT_HEADER = "x-aksor-client"


def _verify_out(context: AuthContext) -> AuthVerifyOut:
    return AuthVerifyOut(
        authenticated=True,
        username=context.username,
        org_id=context.org_id,
        is_superuser=context.is_superuser,
        permissions=sorted(context.permissions),
        must_change_password=context.user.must_change_password if context.user is not None else setup_required(context),
        setup_required=setup_required(context),
    )


def _check_credentials(
    request: Request,
    credentials: HTTPBasicCredentials,
    *,
    require_totp: bool,
    totp_code: str | None,
    record_success: bool = True,
) -> AuthContext:
    """Password, then (if asked and the account has it) the 2FA code -- logging each failure, and the success unless
    the caller logs it itself (/auth/login does, once it knows the session and device)."""
    ip_address = client_ip(request)
    user_agent = request.headers.get("user-agent")

    def _log_failure() -> None:
        with db.SessionLocal() as session:
            record_login_failure(
                session, username=credentials.username, org_id=None, ip_address=ip_address, user_agent=user_agent
            )

    try:
        context = resolve_auth_context(credentials)
    except HTTPException as exc:
        # Only a real wrong-credential rejection is a loggable attempt --
        # 503 ("not configured at all") isn't the caller's fault and
        # isn't tied to any particular username.
        if exc.status_code == 401:
            _log_failure()
        raise

    if require_totp and context.user is not None and context.user.totp_enabled:
        if not totp_code:
            raise HTTPException(status_code=401, detail=TOTP_REQUIRED_DETAIL)
        step = totp.verify_totp_code(context.user.totp_secret or "", totp_code, context.user.totp_last_used_step)
        if step is None:
            _log_failure()
            raise HTTPException(status_code=401, detail="Invalid or expired code")
        with db.SessionLocal() as session:
            row = session.get(db.User, context.user.id)
            if row is not None:
                row.totp_last_used_step = step
                session.commit()

    # No database row behind a break-glass superuser (see auth.py's
    # module docstring) -- nothing to attach a log row to.
    if record_success and context.user is not None:
        with db.SessionLocal() as session:
            record_login_success(session, context.user, ip_address=ip_address, user_agent=user_agent)
    return context


def _device(request: Request, response: Response) -> str:
    """This browser's device id (as stored: its hash), giving it one -- and the cookie -- if it has none yet. The
    cookie is renewed on every sign-in, so a browser in regular use stays known."""
    token = request.cookies.get(DEVICE_COOKIE)
    if device_hash(token) is None:
        token = new_device_token()
    same_site = _cookie_samesite()
    response.set_cookie(
        DEVICE_COOKIE,
        token,
        max_age=DEVICE_COOKIE_MAX_AGE,
        path=COOKIE_PATH,
        httponly=True,
        secure=_cookie_secure(request) or same_site == "none",
        samesite=same_site,
    )
    return device_hash(token)  # type: ignore[return-value]  -- a fresh token always hashes


# --- the refresh cookie ---------------------------------------------------------------------------


def _cookie_secure(request: Request) -> bool:
    setting = os.environ.get("AUTH_COOKIE_SECURE", "auto").strip().lower()
    if setting in ("1", "true", "yes", "on"):
        return True
    if setting in ("0", "false", "no", "off"):
        return False
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def _cookie_samesite() -> str:
    value = os.environ.get("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    return value if value in ("lax", "strict", "none") else "lax"


def _set_refresh_cookie(response: Response, request: Request, token: str, row) -> None:
    same_site = _cookie_samesite()
    max_age = None
    if row.remember:
        # A "keep me signed in" cookie outlives the browser; otherwise it's a session cookie.
        max_age = max(int((datetime.fromisoformat(row.expires_at) - datetime.now(timezone.utc)).total_seconds()), 0)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        path=COOKIE_PATH,
        httponly=True,
        # SameSite=None is only honoured together with Secure.
        secure=_cookie_secure(request) or same_site == "none",
        samesite=same_site,
    )


def _clear_refresh_cookie(response: Response, request: Request) -> None:
    same_site = _cookie_samesite()
    response.delete_cookie(
        COOKIE_NAME, path=COOKIE_PATH, httponly=True, secure=_cookie_secure(request) or same_site == "none", samesite=same_site
    )


def _allowed_origins(request: Request) -> set[str]:
    allowed = {o.strip().rstrip("/") for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    allowed.add(f"{request.url.scheme}://{request.url.netloc}")
    return allowed


def _require_deliberate_request(request: Request) -> None:
    """Refresh and logout act on a cookie the browser attaches by itself, so a page on another site could try
    to trigger them. Insist on a header only our own script sets (it forces a CORS preflight a stranger's
    page would fail) and on a recognised Origin."""
    if CLIENT_HEADER not in request.headers:
        raise HTTPException(status_code=400, detail="Missing the X-Aksor-Client header")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in _allowed_origins(request):
        _log.warning("Refused an auth cookie request from origin %r", origin)
        raise HTTPException(status_code=403, detail="This origin isn't allowed")


def _issue(context: AuthContext, session_row, refresh_token: str | None, request: Request, response: Response) -> TokenOut:
    token, expires_in = auth_tokens.encode_access_token(
        session_id=session_row.id,
        username=context.username,
        user_id=context.user.id if context.user is not None else None,
        org_id=context.org_id,
    )
    if refresh_token is not None:
        _set_refresh_cookie(response, request, refresh_token, session_row)
    # An access token must never be cached by anything between here and the browser.
    response.headers["Cache-Control"] = "no-store"
    return TokenOut(access_token=token, expires_in=expires_in, user=_verify_out(context))


# --- sign in / refresh / sign out ------------------------------------------------------------------


@router.post("/login", summary="Sign in: get an access token (and the refresh cookie)", response_model=TokenOut)
def login(body: LoginRequest, request: Request, response: Response) -> TokenOut:
    _throttle_sign_in(request, body.username)
    try:
        context = _check_credentials(
            request,
            HTTPBasicCredentials(username=body.username, password=body.password),
            require_totp=True,
            totp_code=body.totp_code,
            record_success=False,
        )
    except HTTPException as exc:
        # The shared check answers a wrong password with `WWW-Authenticate: Basic` -- right for scripts that send HTTP
        # Basic, but on this JSON sign-in it makes the browser pop up its own login dialog over the portal's form.
        headers = {k: v for k, v in (exc.headers or {}).items() if k.lower() != "www-authenticate"}
        raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers or None) from None
    with db.SessionLocal() as session:
        row, refresh_token = auth_tokens.create_session(
            session,
            user=context.user,
            username=context.username,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            remember=body.remember,
            browser_brand=browser_brand(request),
        )
        context.session_id = row.id
        if context.user is not None:
            record_login_success(
                session,
                context.user,
                ip_address=client_ip(request),
                user_agent=request.headers.get("user-agent"),
                device=_device(request, response),
                session_id=row.id,
                brand=browser_brand(request),
            )
        return _issue(context, row, refresh_token, request, response)


@router.post(
    "/setup-admin",
    summary="First run: turn the generated break-glass sign-in into your own administrator account",
    response_model=TokenOut,
)
def setup_admin(
    body: SetupAdminRequest,
    request: Request,
    response: Response,
    context: AuthContext = Depends(get_current_user_allowing_password_change),
) -> TokenOut:
    """The PORTAL_PASSWORD that `deployment.sh init` generates is a one-time key. Signed in with it while no
    administrator account exists, this creates one -- the same user name, *your* password, the system-wide
    administrator role -- ends the break-glass session and signs you in as the new account. From then on the .env
    password no longer works for that name (a database account with the name takes precedence)."""
    if not setup_required(context):
        raise HTTPException(status_code=409, detail="The first-run setup is already done -- sign in with your administrator account")
    try:
        password = check_password_policy(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    now = datetime.now(timezone.utc).isoformat()
    with db.SessionLocal() as session:
        # Re-checked inside the transaction's session: two setups racing must not both create an administrator.
        if system_admin_exists(session):
            raise HTTPException(status_code=409, detail="An administrator account already exists -- sign in with it")
        if find_user_for_login(session, context.username) is not None:
            raise HTTPException(status_code=409, detail=f"A user named {context.username} already exists")
        role = session.execute(
            select(db.Role).where(db.Role.org_id.is_(None), db.Role.name == SYSTEM_ADMIN_ROLE_NAME)
        ).scalar_one()
        user = db.User(
            org_id=ROOT_ORG_ID,
            username=context.username,
            auth_source="local",
            password_hash=hash_password(password),
            must_change_password=False,
            is_active=True,
            is_locked=False,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        session.flush()
        session.add(db.UserRoleAssignment(user_id=user.id, role_id=role.id, granted_at=now, granted_by=None, is_active=True))
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "user.create", "user", user.id,
            label=user.username, org_id=ROOT_ORG_ID,
            summary=f"First-run setup: created administrator {user.username}",
            details={"auth_source": "local", "role": SYSTEM_ADMIN_ROLE_NAME},
        )
        if context.session_id:
            auth_tokens.revoke_session(session, context.session_id, "first-run setup finished")
        session.refresh(user)
        account = AuthContext(
            username=user.username,
            is_superuser=True,
            permissions=get_effective_permissions(session, user),
            user=user,
            org_id=user.org_id,
        )
        row, refresh_token = auth_tokens.create_session(
            session,
            user=user,
            username=user.username,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            remember=False,
            browser_brand=browser_brand(request),
        )
        account.session_id = row.id
        return _issue(account, row, refresh_token, request, response)


@router.post("/refresh", summary="Trade the refresh cookie for a new access token", response_model=TokenOut)
def refresh(request: Request, response: Response):
    _require_deliberate_request(request)
    cookie = request.cookies.get(COOKIE_NAME)

    def _refuse(detail: str) -> JSONResponse:
        refusal = JSONResponse(status_code=401, content={"detail": detail}, headers={"Cache-Control": "no-store"})
        _clear_refresh_cookie(refusal, request)
        return refusal

    if not cookie:
        return _refuse("Not signed in")
    with db.SessionLocal() as session:
        try:
            rotation = auth_tokens.rotate(
                session, cookie, ip_address=client_ip(request), user_agent=request.headers.get("user-agent")
            )
            context = context_for_session(session, rotation.session)
        except auth_tokens.TokenError as exc:
            if exc.code == "reuse_detected":
                return _refuse("This session was ended because its sign-in cookie was used twice -- sign in again")
            return _refuse("Your session has expired -- sign in again")
        except HTTPException as exc:  # the account was disabled or locked since the last refresh
            return _refuse(str(exc.detail))
        return _issue(context, rotation.session, rotation.refresh_token, request, response)


@router.post("/logout", status_code=204, summary="Sign out: revoke this session and clear the cookie")
def logout(request: Request, response: Response) -> Response:
    _require_deliberate_request(request)
    cookie = request.cookies.get(COOKIE_NAME)
    with db.SessionLocal() as session:
        if cookie:
            row = auth_tokens.find_by_refresh(session, cookie)
            if row is not None:
                auth_tokens.revoke_session(session, row.id, "logout")
    # Bearer holder without the cookie (a script that logged in): end that session too.
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            claims = auth_tokens.decode_access_token(header[7:].strip())
        except auth_tokens.TokenError:
            claims = None
        if claims:
            with db.SessionLocal() as session:
                auth_tokens.revoke_session(session, claims["sid"], "logout")
    _clear_refresh_cookie(response, request)
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 204
    return response


@router.get("/me", summary="Who the access token is, and what it may do", response_model=AuthVerifyOut)
def me(context: AuthContext = Depends(get_current_user_allowing_password_change)) -> AuthVerifyOut:
    return _verify_out(context)


# --- the places I'm signed in -------------------------------------------------------------------


def _session_out(row: db.AuthSession, current_id: str | None) -> SessionOut:
    parsed = parse_user_agent(row.user_agent, row.browser_brand)
    return SessionOut(
        id=row.id,
        current=row.id == current_id,
        browser=parsed.browser,
        os=parsed.os,
        device_type=parsed.device_type,
        ip_address=row.ip_address,
        remember=row.remember,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
    )


def _own_sessions(session, context: AuthContext) -> list[db.AuthSession]:
    return auth_tokens.live_sessions(session, user_id=context.user.id if context.user else None, username=context.username)


@router.get("/sessions", summary="The caller's live sign-in sessions", response_model=list[SessionOut])
def list_sessions(context: AuthContext = Depends(get_current_user)) -> list[SessionOut]:
    with db.SessionLocal() as session:
        return [_session_out(row, context.session_id) for row in _own_sessions(session, context)]


@router.delete("/sessions/{session_id}", status_code=204, summary="Sign out one of the caller's sessions")
def revoke_session(session_id: str, request: Request, context: AuthContext = Depends(get_current_user)) -> None:
    with db.SessionLocal() as session:
        # Only the caller's own sessions: anyone else's id is simply "not found".
        if session_id not in {row.id for row in _own_sessions(session, context)}:
            raise HTTPException(status_code=404, detail="Session not found")
        auth_tokens.revoke_session(session, session_id, "revoked_by_user")
    audit.record(
        audit.Actor.of(context, request), "auth.session_revoke", "session", session_id, label=context.username,
        org_id=context.org_id, summary="Signed out a session",
    )


@router.post("/sessions/revoke-others", summary="Sign out every session except this one", response_model=dict)
def revoke_other_sessions(request: Request, context: AuthContext = Depends(get_current_user)) -> dict:
    with db.SessionLocal() as session:
        ids = [row.id for row in _own_sessions(session, context) if row.id != context.session_id]
        for session_id in ids:
            auth_tokens.revoke_session(session, session_id, "revoked_by_user")
    if ids:
        audit.record(
            audit.Actor.of(context, request), "auth.session_revoke_others", "session", context.session_id or "-",
            label=context.username, org_id=context.org_id, summary=f"Signed out {len(ids)} other session(s)",
        )
    return {"revoked": len(ids)}


# --- the older Basic-credential check ----------------------------------------------------------------


@router.get("/verify", summary="Check whether the given credentials are valid", response_model=AuthVerifyOut)
def verify(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(_security),
    login: bool = Query(False, description="Also demand the 2FA code, as a sign-in would"),
    totp_code: str | None = Query(None, description="Required (when login=true) once the account has 2FA enabled"),
) -> AuthVerifyOut:
    """For scripts that want to test a username and password. The portal signs in through /auth/login instead."""
    _throttle_sign_in(request, credentials.username)
    context = _check_credentials(request, credentials, require_totp=login, totp_code=totp_code)
    return _verify_out(context)
