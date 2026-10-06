from pydantic import BaseModel, Field


class AuthVerifyOut(BaseModel):
    authenticated: bool
    username: str
    org_id: str | None = Field(None, description="None for a break-glass superuser")
    is_superuser: bool
    permissions: list[str] = Field(
        default_factory=list, description="Effective permission codes; meaningless (empty) for a superuser -- see is_superuser"
    )
    must_change_password: bool = Field(
        False,
        description="True when this account has to pick a new password first -- every other endpoint answers "
        "403 PASSWORD_CHANGE_REQUIRED until PATCH /users/me changes it. Always false for a break-glass superuser.",
    )


class LoginRequest(BaseModel):
    username: str = Field(..., description="The user name, or `name|organization-id` when the same name exists in several organizations")
    password: str
    totp_code: str | None = Field(None, description="The 6-digit code from the authenticator app, once the account has 2FA enabled")
    remember: bool = Field(
        False,
        description="Keep this browser signed in for REFRESH_TOKEN_TTL_DAYS (30 by default) instead of REFRESH_TOKEN_SESSION_HOURS "
        "(12) -- and keep the refresh cookie across browser restarts.",
    )


class TokenOut(BaseModel):
    """What signing in or refreshing answers: the access token to send as `Authorization: Bearer ...`, when it
    expires, and who it is (the same shape /auth/verify gives, so the portal needs no second call). The refresh
    token is deliberately not here -- it travels only as an HttpOnly cookie."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Seconds until the access token expires")
    user: AuthVerifyOut


class SessionOut(BaseModel):
    id: str
    current: bool = Field(..., description="The session this request belongs to")
    browser: str
    os: str
    device_type: str
    ip_address: str | None
    remember: bool
    created_at: str
    last_used_at: str
    expires_at: str


class AuthEventOut(BaseModel):
    """One row of app/db/auth_events.py's AuthEvent, with the raw
    user_agent parsed server-side (app/auth_events.py's parse_user_agent)
    rather than shipping the raw string for the portal to sniff itself.
    Backs three endpoints (users.py's /me/sessions, /me/auth-log,
    /me/notifications) that all read the same table differently -- see
    that table's own docstring for why a "session" here means a
    (user, ip, user_agent) fingerprint, not a literal server session.
    """

    id: str
    success: bool
    username: str
    ip_address: str | None
    browser: str
    os: str
    device_type: str
    is_current: bool = Field(False, description="True if this fingerprint matches the request that asked for this list")
    is_new_device: bool
    created_at: str
    last_seen_at: str
