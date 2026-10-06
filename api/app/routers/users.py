"""User management, scoped to the caller's own organization unless the
caller is a superuser (break-glass, or a database user holding the
cross-org ROLE_ADMINISTRATOR — see auth.ensure_org_scope).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import audit, auth_tokens, avatar_store, db, totp
from ..auth import ensure_org_scope, get_current_user, get_current_user_allowing_password_change, require_permission
from ..auth_events import client_ip, parse_user_agent
from ..models import (
    SETTING_CODE_PATTERN,
    AuthEventOut,
    EffectivePermissions,
    PasswordResetOut,
    PasswordResetRequest,
    TotpCodeRequest,
    TotpEnrollOut,
    UserCreate,
    UserOut,
    UserSelfUpdate,
    UserSettingOut,
    UserSettingUpdate,
    UserUpdate,
    check_setting_value,
)
from ..rbac import AuthContext, get_effective_permissions
from ..security import generate_password, hash_password, verify_password

router = APIRouter(prefix="/api/v1/users", tags=["users"])

# How far back an "Active sessions" listing looks -- a success fingerprint
# whose last_seen_at falls outside this window has effectively lapsed
# (see app/auth_events.py's SESSION_RENEW_WINDOW for the much shorter
# window that governs whether a *new* sign-in renews it instead of
# opening a fresh row).
_SESSIONS_LOOKBACK = timedelta(days=30)
_AUTH_LOG_LIMIT = 100

# Upper bound on distinct setting codes one user can hold -- a real
# account has a handful; this only exists so the generic PUT can't be
# used to grow one user's rows without limit.
_MAX_SETTINGS_PER_USER = 200


def _row_to_out(row: db.User) -> UserOut:
    return UserOut(
        id=row.id,
        org_id=row.org_id,
        username=row.username,
        email=row.email,
        display_name=row.display_name,
        auth_source=row.auth_source,
        is_active=row.is_active,
        is_locked=row.is_locked,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_login_at=row.last_login_at,
        notify_new_signin=row.notify_new_signin,
        avatar_content_type=row.avatar_content_type,
        totp_enabled=row.totp_enabled,
        must_change_password=row.must_change_password,
    )


def _event_to_out(row: db.AuthEvent, current_ip: str | None, current_user_agent: str | None) -> AuthEventOut:
    parsed = parse_user_agent(row.user_agent)
    return AuthEventOut(
        id=row.id,
        success=row.success,
        username=row.username,
        ip_address=row.ip_address,
        browser=parsed.browser,
        os=parsed.os,
        device_type=parsed.device_type,
        is_current=row.ip_address == current_ip and row.user_agent == current_user_agent,
        is_new_device=row.is_new_device,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
    )


@router.post("", summary="Create a user", response_model=UserOut)
def create_user(
    body: UserCreate,
    request: Request,
    org_id: str = Query(..., description="Organization the new user belongs to"),
    context: AuthContext = Depends(require_permission("user:manage")),
) -> UserOut:
    ensure_org_scope(context, org_id)

    if body.auth_source == "local":
        if not body.password:
            raise HTTPException(status_code=400, detail="password is required when auth_source='local'")
        password_hash = hash_password(body.password)
    else:
        if body.password:
            raise HTTPException(status_code=400, detail="password must be omitted when auth_source='ldap'")
        password_hash = None

    now = datetime.now(timezone.utc).isoformat()
    with db.SessionLocal() as session:
        if session.get(db.Organization, org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        row = db.User(
            org_id=org_id,
            username=body.username,
            email=body.email,
            display_name=body.display_name,
            auth_source=body.auth_source,
            password_hash=password_hash,
            # An LDAP user's password isn't ours to expire.
            must_change_password=body.must_change_password and body.auth_source == "local",
            is_active=True,
            is_locked=False,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="Username already exists in this organization") from exc
        audit.record(
            audit.Actor.of(context, request), "user.create", "user", row.id,
            label=row.username, org_id=org_id, summary=f"Created {row.auth_source} user {row.username}",
            details={
                "auth_source": row.auth_source,
                "email": row.email,
                "must_change_password": row.must_change_password,
            },
        )
        return _row_to_out(row)


@router.get("", summary="List users", response_model=list[UserOut])
def list_users(
    org_id: str | None = Query(None, description="Superusers may omit this to list across every org"),
    context: AuthContext = Depends(require_permission("user:manage")),
) -> list[UserOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    with db.SessionLocal() as session:
        query = select(db.User).order_by(db.User.username)
        if org_id is not None:
            query = query.where(db.User.org_id == org_id)
        rows = session.execute(query).scalars().all()
        return [_row_to_out(row) for row in rows]


@router.get(
    "/me",
    summary="Get the caller's own profile",
    response_model=UserOut,
    description="No user:manage required -- any authenticated database user may read their own row, even one "
    "that still has to change its password (see app/auth.py). "
    "404s for a break-glass login (PORTAL_USERNAME/PORTAL_PASSWORD): there's no database row behind it.",
)
def get_my_profile(context: AuthContext = Depends(get_current_user_allowing_password_change)) -> UserOut:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    return _row_to_out(context.user)


@router.patch(
    "/me",
    summary="Update the caller's own profile",
    response_model=UserOut,
    description="Self-service counterpart to PATCH /{user_id} -- no user:manage required, but deliberately "
    "narrower: no is_active/is_locked (a user can't unlock or reactivate themselves), and a password "
    "change must include the correct current_password, and must differ from it. Also the one write an account "
    "flagged must_change_password may make -- a successful password change lifts the flag.",
)
def update_my_profile(
    body: UserSelfUpdate, request: Request, context: AuthContext = Depends(get_current_user_allowing_password_change)
) -> UserOut:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    with db.SessionLocal() as session:
        row = session.get(db.User, context.user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        before = {"email": row.email, "display_name": row.display_name}
        password_changed = body.new_password is not None
        was_forced = row.must_change_password

        if body.email is not None:
            row.email = body.email
        if body.display_name is not None:
            row.display_name = body.display_name
        if body.new_password is not None:
            if row.auth_source != "local":
                raise HTTPException(status_code=400, detail="Password is managed by your identity provider")
            if not body.current_password or not verify_password(body.current_password, row.password_hash or ""):
                # 400, not 401 -- this isn't an authentication failure (Basic
                # Auth already re-proved the *session's* credential to reach
                # this endpoint at all); it's a wrong value in a secondary
                # confirmation field. api.ts's apiFetch treats *any* 401
                # globally as "you're signed out" and clears the cached
                # credential -- a 401 here would silently sign the caller
                # out instead of showing them an inline error.
                raise HTTPException(status_code=400, detail="Current password is incorrect")
            if body.new_password == body.current_password:
                # Otherwise a forced change could be "satisfied" by retyping
                # the temporary password an admin just handed out.
                raise HTTPException(status_code=400, detail="New password must be different from the current one")
            row.password_hash = hash_password(body.new_password)
            row.must_change_password = False
        if body.notify_new_signin is not None:
            row.notify_new_signin = body.notify_new_signin

        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        if password_changed:
            # Whoever knew the old password (or stole a session) is signed out everywhere else; this
            # session stays, so the person who just changed it isn't thrown out.
            auth_tokens.revoke_user_sessions(session, row.id, "password_changed", except_session_id=context.session_id)

        actor = audit.Actor.of(context, request)
        changes = audit.diff(before, {"email": row.email, "display_name": row.display_name}, ["email", "display_name"])
        if changes:
            audit.record(
                actor, "user.profile_update", "user", row.id, label=row.username, org_id=row.org_id,
                summary="Updated own profile", changes=changes,
            )
        if password_changed:
            audit.record(
                actor, "user.password_change", "user", row.id, label=row.username, org_id=row.org_id,
                summary="Changed own password" if not was_forced else "Changed own password (required at first sign-in)",
                details={"was_required": was_forced},
            )
        return _row_to_out(row)


@router.put(
    "/me/avatar",
    summary="Upload or replace the caller's own avatar",
    response_model=UserOut,
    description="Re-encoded and downscaled server-side (see app/avatar_store.py) -- the original upload's "
    "bytes/format/metadata are never stored as-is.",
)
async def upload_my_avatar(
    request: Request, file: UploadFile = File(...), context: AuthContext = Depends(get_current_user)
) -> UserOut:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    content = await file.read()
    try:
        content_type = avatar_store.save_avatar(context.user.id, content)
    except avatar_store.InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=f"Not a usable image: {exc}") from exc

    with db.SessionLocal() as session:
        row = session.get(db.User, context.user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        row.avatar_content_type = content_type
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        out = _row_to_out(row)
    audit.record(
        audit.Actor.of(context, request), "user.avatar_update", "user", out.id,
        label=out.username, org_id=out.org_id, summary=f"{out.username} changed their avatar",
    )
    return out


@router.delete("/me/avatar", summary="Remove the caller's own avatar", response_model=UserOut)
def delete_my_avatar(request: Request, context: AuthContext = Depends(get_current_user)) -> UserOut:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    avatar_store.delete_avatar(context.user.id)
    with db.SessionLocal() as session:
        row = session.get(db.User, context.user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        row.avatar_content_type = None
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        out = _row_to_out(row)
    audit.record(
        audit.Actor.of(context, request), "user.avatar_remove", "user", out.id,
        label=out.username, org_id=out.org_id, summary=f"{out.username} removed their avatar",
    )
    return out


@router.get(
    "/me/avatar",
    summary="Fetch the caller's own avatar image bytes",
    description="404s if no avatar has been uploaded -- callers (see AccountMenu.tsx's UserAvatar) treat that "
    "as \"show initials instead\", the same way ImageThumbnail treats a failed images.fileBlob().",
)
def get_my_avatar(context: AuthContext = Depends(get_current_user)) -> Response:
    if context.user is None or context.user.avatar_content_type is None:
        raise HTTPException(status_code=404, detail="No avatar set")
    content = avatar_store.get_avatar_bytes(context.user.id, context.user.avatar_content_type)
    return Response(content=content, media_type=context.user.avatar_content_type)


@router.post(
    "/me/totp/enroll",
    summary="Start enrolling a TOTP second factor",
    response_model=TotpEnrollOut,
    description="Generates a new secret and returns it (plus a ready-to-render QR code) -- not yet active. "
    "POST /me/totp/confirm with a code generated from it to turn 2FA on. 409s if already enabled -- disable "
    "first (proves you still hold the current device) before enrolling a new one. See app/totp.py.",
)
def enroll_totp(context: AuthContext = Depends(get_current_user)) -> TotpEnrollOut:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    if context.user.totp_enabled:
        raise HTTPException(status_code=409, detail="Two-factor authentication is already enabled -- disable it first")

    secret = totp.generate_secret()
    otpauth_url = totp.provisioning_uri(secret, context.user.username, totp.ISSUER)
    with db.SessionLocal() as session:
        row = session.get(db.User, context.user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        row.totp_secret = totp.seal(secret)
        row.totp_last_used_step = None
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()

    return TotpEnrollOut(secret=secret, otpauth_url=otpauth_url, qr_code_data_url=totp.qr_code_data_url(otpauth_url))


@router.post(
    "/me/totp/confirm",
    summary="Confirm TOTP enrollment with a code, turning 2FA on",
    response_model=UserOut,
)
def confirm_totp(body: TotpCodeRequest, request: Request, context: AuthContext = Depends(get_current_user)) -> UserOut:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    if context.user.totp_secret is None:
        raise HTTPException(status_code=400, detail="Call /me/totp/enroll first")

    step = totp.verify_totp_code(context.user.totp_secret, body.code, context.user.totp_last_used_step)
    if step is None:
        raise HTTPException(status_code=400, detail="That code didn't match -- check the time on your device and try again")

    with db.SessionLocal() as session:
        row = session.get(db.User, context.user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        row.totp_enabled = True
        row.totp_last_used_step = step
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "user.totp_enable", "user", row.id, label=row.username, org_id=row.org_id,
            summary="Turned on two-factor authentication",
        )
        return _row_to_out(row)


@router.post(
    "/me/totp/disable",
    summary="Disable TOTP, given a currently-valid code",
    response_model=UserOut,
    description="Requires a fresh code from the authenticator being removed, not just the account password -- "
    "the session is already proven by its access token, and the password was checked when it was opened, so the "
    "fresh code is what confirms it's still the account owner at the keyboard. Locked out with no working code? An admin "
    "can clear it via PATCH /users/{id} with reset_totp=true.",
)
def disable_totp(body: TotpCodeRequest, request: Request, context: AuthContext = Depends(get_current_user)) -> UserOut:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    if not context.user.totp_enabled or context.user.totp_secret is None:
        raise HTTPException(status_code=400, detail="Two-factor authentication isn't enabled")

    step = totp.verify_totp_code(context.user.totp_secret, body.code, context.user.totp_last_used_step)
    if step is None:
        raise HTTPException(status_code=400, detail="That code didn't match")

    with db.SessionLocal() as session:
        row = session.get(db.User, context.user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        row.totp_secret = None
        row.totp_enabled = False
        row.totp_last_used_step = None
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "user.totp_disable", "user", row.id, label=row.username, org_id=row.org_id,
            summary="Turned off two-factor authentication",
        )
        return _row_to_out(row)


@router.get(
    "/me/sessions",
    summary="List the caller's recent sign-in sessions",
    response_model=list[AuthEventOut],
    description="Recent sign-ins -- a row is an (ip, browser, device) fingerprint that signed in successfully within "
    "the last 30 days, not a live session. The live, revocable sessions are GET /auth/sessions. "
    "See app/db/auth_events.py.",
)
def list_my_sessions(request: Request, context: AuthContext = Depends(get_current_user)) -> list[AuthEventOut]:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    cutoff = (datetime.now(timezone.utc) - _SESSIONS_LOOKBACK).isoformat()
    ip_address = client_ip(request)
    user_agent = request.headers.get("user-agent")
    with db.SessionLocal() as session:
        rows = (
            session.execute(
                select(db.AuthEvent)
                .where(
                    db.AuthEvent.user_id == context.user.id,
                    db.AuthEvent.success.is_(True),
                    db.AuthEvent.last_seen_at >= cutoff,
                )
                .order_by(db.AuthEvent.last_seen_at.desc())
            )
            .scalars()
            .all()
        )
        return [_event_to_out(row, ip_address, user_agent) for row in rows]


@router.get(
    "/me/auth-log",
    summary="List the caller's recent authentication activity",
    response_model=list[AuthEventOut],
    description="Every recorded sign-in and failed attempt for this account (both by user_id and, for a "
    "failed attempt against this same username before it resolved to a user, by username), most recent first.",
)
def list_my_auth_log(request: Request, context: AuthContext = Depends(get_current_user)) -> list[AuthEventOut]:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    ip_address = client_ip(request)
    user_agent = request.headers.get("user-agent")
    with db.SessionLocal() as session:
        rows = (
            session.execute(
                select(db.AuthEvent)
                .where(
                    (db.AuthEvent.user_id == context.user.id) | (db.AuthEvent.username == context.user.username)
                )
                .order_by(db.AuthEvent.created_at.desc())
                .limit(_AUTH_LOG_LIMIT)
            )
            .scalars()
            .all()
        )
        return [_event_to_out(row, ip_address, user_agent) for row in rows]


@router.get(
    "/me/notifications",
    summary="Unacknowledged new-device sign-in alerts for the caller",
    response_model=list[AuthEventOut],
    description="Empty if the caller has turned off Settings > Notifications' new-sign-in-alert toggle "
    "(UserSelfUpdate.notify_new_signin) -- see app/auth_events.py's is_new_device.",
)
def list_my_notifications(context: AuthContext = Depends(get_current_user)) -> list[AuthEventOut]:
    if context.user is None or not context.user.notify_new_signin:
        return []
    with db.SessionLocal() as session:
        rows = (
            session.execute(
                select(db.AuthEvent)
                .where(
                    db.AuthEvent.user_id == context.user.id,
                    db.AuthEvent.is_new_device.is_(True),
                    db.AuthEvent.acknowledged.is_(False),
                )
                .order_by(db.AuthEvent.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [_event_to_out(row, None, None) for row in rows]


@router.post(
    "/me/notifications/ack",
    summary="Acknowledge every pending new-device sign-in alert",
    status_code=204,
    response_model=None,
)
def ack_my_notifications(context: AuthContext = Depends(get_current_user)) -> None:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    with db.SessionLocal() as session:
        rows = (
            session.execute(
                select(db.AuthEvent).where(
                    db.AuthEvent.user_id == context.user.id, db.AuthEvent.acknowledged.is_(False)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.acknowledged = True
        session.commit()


@router.get(
    "/me/settings",
    summary="Get all of the caller's own settings",
    response_model=dict[str, Any],
    description="A flat `{code: value}` map of every setting this account has saved (see app/db/user_settings.py) "
    "-- codes never set are simply absent, so a client falls back to its own default for them. 404s for a "
    "break-glass login: there's no database row to attach settings to.",
)
def list_my_settings(context: AuthContext = Depends(get_current_user)) -> dict[str, Any]:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    with db.SessionLocal() as session:
        rows = session.execute(select(db.UserSetting).where(db.UserSetting.user_id == context.user.id)).scalars().all()
        return {row.code: row.value for row in rows}


@router.put(
    "/me/settings/{code}",
    summary="Create or replace one of the caller's own settings",
    response_model=UserSettingOut,
    description="Upserts by (caller, code). The value is any non-null JSON, stored as-is -- this endpoint doesn't "
    "know what any particular code means or which values it allows; the client that reads it back validates it.",
)
def put_my_setting(
    body: UserSettingUpdate,
    code: str = Path(..., pattern=SETTING_CODE_PATTERN, description="Setting identifier, e.g. report_preview_layout"),
    context: AuthContext = Depends(get_current_user),
) -> UserSettingOut:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    try:
        check_setting_value(body.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user_id = context.user.id
    now = datetime.now(timezone.utc).isoformat()

    # Two attempts: the second exists only for two concurrent first-writes
    # of the same (user, code) -- the loser hits the unique constraint,
    # and on retry finds the winner's row and updates it instead.
    for _ in range(2):
        with db.SessionLocal() as session:
            row = session.execute(
                select(db.UserSetting).where(db.UserSetting.user_id == user_id, db.UserSetting.code == code)
            ).scalar_one_or_none()
            if row is None:
                held = session.scalar(
                    select(func.count()).select_from(db.UserSetting).where(db.UserSetting.user_id == user_id)
                )
                if held >= _MAX_SETTINGS_PER_USER:
                    raise HTTPException(
                        status_code=400, detail=f"Too many settings saved (limit {_MAX_SETTINGS_PER_USER})"
                    )
                row = db.UserSetting(user_id=user_id, code=code, value=body.value, created_at=now, updated_at=now)
                session.add(row)
            else:
                row.value = body.value
                row.updated_at = now
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                continue
            return UserSettingOut(code=row.code, value=row.value, updated_at=row.updated_at)
    raise HTTPException(status_code=409, detail="Conflicting update, try again")


@router.delete(
    "/me/settings/{code}",
    summary="Clear one of the caller's own settings",
    status_code=204,
    response_model=None,
    description="Idempotent -- clearing a code that was never set is not an error. The client then falls back to "
    "its own default for that code.",
)
def delete_my_setting(
    code: str = Path(..., pattern=SETTING_CODE_PATTERN, description="Setting identifier, e.g. report_preview_layout"),
    context: AuthContext = Depends(get_current_user),
) -> None:
    if context.user is None:
        raise HTTPException(status_code=404, detail="No profile for this credential")
    with db.SessionLocal() as session:
        row = session.execute(
            select(db.UserSetting).where(db.UserSetting.user_id == context.user.id, db.UserSetting.code == code)
        ).scalar_one_or_none()
        if row is not None:
            session.delete(row)
            session.commit()


@router.get("/{user_id}", summary="Get one user", response_model=UserOut)
def get_user(user_id: str, context: AuthContext = Depends(require_permission("user:manage"))) -> UserOut:
    with db.SessionLocal() as session:
        row = session.get(db.User, user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        ensure_org_scope(context, row.org_id)
        return _row_to_out(row)


@router.patch("/{user_id}", summary="Update a user", response_model=UserOut)
def update_user(
    user_id: str, body: UserUpdate, request: Request, context: AuthContext = Depends(require_permission("user:manage"))
) -> UserOut:
    with db.SessionLocal() as session:
        row = session.get(db.User, user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        ensure_org_scope(context, row.org_id)
        tracked = ("email", "display_name", "is_active", "is_locked", "must_change_password")
        before = {f: getattr(row, f) for f in tracked}
        had_totp = row.totp_enabled

        if body.email is not None:
            row.email = body.email
        if body.display_name is not None:
            row.display_name = body.display_name
        if body.is_active is not None:
            row.is_active = body.is_active
        if body.is_locked is not None:
            row.is_locked = body.is_locked
        if body.password is not None:
            if row.auth_source != "local":
                raise HTTPException(status_code=400, detail="Cannot set a password for a non-local user")
            row.password_hash = hash_password(body.password)
        if body.must_change_password is not None:
            if body.must_change_password and row.auth_source != "local":
                raise HTTPException(status_code=400, detail="Password is managed by the user's identity provider")
            row.must_change_password = body.must_change_password
        if body.reset_totp:
            row.totp_secret = None
            row.totp_enabled = False
            row.totp_last_used_step = None
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        if body.is_active is False or body.is_locked is True or body.password is not None or body.reset_totp:
            # Disabling, locking, re-keying or clearing 2FA ends the person's sign-ins now, not when
            # their access token would have expired.
            auth_tokens.revoke_user_sessions(session, row.id, "admin")

        actor = audit.Actor.of(context, request)
        changes = audit.diff(before, {f: getattr(row, f) for f in tracked}, list(tracked))
        if changes:
            status = {
                c["field"]: c["after"] for c in changes if c["field"] in ("is_active", "is_locked", "must_change_password")
            }
            audit.record(
                actor, "user.update", "user", row.id, label=row.username, org_id=row.org_id,
                summary=(
                    f"{'Activated' if status['is_active'] else 'Deactivated'} user {row.username}"
                    if "is_active" in status
                    else f"{'Locked' if status['is_locked'] else 'Unlocked'} user {row.username}"
                    if "is_locked" in status
                    else (
                        f"Required a password change from {row.username} at next sign-in"
                        if status["must_change_password"]
                        else f"Stopped requiring a password change from {row.username}"
                    )
                    if "must_change_password" in status
                    else f"Updated user {row.username}"
                ),
                changes=changes,
            )
        # Credential-affecting actions get their own event so they can be
        # found by action, not by reading every profile edit.
        if body.password is not None:
            audit.record(
                actor, "user.password_reset", "user", row.id, label=row.username, org_id=row.org_id,
                summary=f"Set a new password for {row.username}",
            )
        if body.reset_totp:
            audit.record(
                actor, "user.totp_reset", "user", row.id, label=row.username, org_id=row.org_id,
                summary=f"Cleared two-factor authentication for {row.username}",
                details={"was_enabled": had_totp},
            )
        return _row_to_out(row)


@router.post(
    "/{user_id}/reset-password",
    summary="Reset a user's password",
    response_model=PasswordResetOut,
    description="For a forgotten password or a new hire's first one. Send `password` to set it yourself, or "
    "omit it and the server generates a strong one, returned once in `generated_password` (never stored in "
    "readable form, never written to the audit trail, and the response isn't cacheable). By default the user "
    "must then choose their own password at next sign-in (`require_change`). `local` users only -- an `ldap` "
    "user's password lives in the directory. Every sign-in session the user has is ended, so the old password "
    "(and any token issued with it) stops working at once.",
)
def reset_user_password(
    user_id: str,
    body: PasswordResetRequest,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_permission("user:manage")),
) -> PasswordResetOut:
    with db.SessionLocal() as session:
        row = session.get(db.User, user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        ensure_org_scope(context, row.org_id)
        if row.auth_source != "local":
            raise HTTPException(status_code=400, detail="Password is managed by the user's identity provider")

        generated = body.password is None
        password = generate_password() if generated else body.password
        row.password_hash = hash_password(password)
        row.must_change_password = body.require_change
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        auth_tokens.revoke_user_sessions(session, row.id, "password_reset")

        audit.record(
            audit.Actor.of(context, request), "user.password_reset", "user", row.id, label=row.username,
            org_id=row.org_id,
            summary=f"Reset the password for {row.username}"
            + (" (temporary, must be changed at next sign-in)" if body.require_change else ""),
            details={"generated": generated, "require_change": body.require_change},
        )
        response.headers["Cache-Control"] = "no-store"
        return PasswordResetOut(user=_row_to_out(row), generated_password=password if generated else None)


@router.get(
    "/{user_id}/permissions",
    summary="Resolve a user's effective (expiry-filtered) permission set",
    response_model=EffectivePermissions,
)
def get_user_permissions(
    user_id: str, context: AuthContext = Depends(require_permission("user:manage"))
) -> EffectivePermissions:
    with db.SessionLocal() as session:
        row = session.get(db.User, user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        ensure_org_scope(context, row.org_id)
        permissions = get_effective_permissions(session, row)
        return EffectivePermissions(user_id=user_id, permissions=sorted(permissions))
