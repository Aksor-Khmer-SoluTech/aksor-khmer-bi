"""Sign-in sessions: one row per sign-in, the server-side half of the access-token /
refresh-token flow (see app/auth_tokens.py for how the rows are used).

A short-lived access token (a JWT) is what every API call carries. It names a session
here; the session is what can be revoked, so signing out, "sign out everywhere", a
password change, or an admin disabling the account takes effect on the very next request
instead of when a token happens to expire.

The refresh token -- the long-lived credential that earns new access tokens -- is never
stored, only its SHA-256. It rotates on every use: `refresh_hash` is the current one and
`previous_hash` the one it replaced, which is how a stolen-and-replayed token is noticed
(see auth_tokens.rotate).

`user_id` is null for the break-glass superuser (PORTAL_USERNAME/PORTAL_PASSWORD), who has no
user row; `username` is kept either way so the session list can say whose it is.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_active", "user_id", "revoked_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    # Unique: the lookup key for a refresh request. SHA-256 hex of the opaque refresh token.
    refresh_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    previous_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    rotated_at: Mapped[str | None] = mapped_column(String, nullable=True)
    remember: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    # The browser's own name when its User-Agent hides it (Brave reads as Chrome) -- see auth_events.browser_brand.
    browser_brand: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    last_used_at: Mapped[str] = mapped_column(String, nullable=False)
    # Absolute end of the session: refreshing never extends it.
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    revoked_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # "logout", "logout_all", "password_changed", "admin", "reuse_detected", ... -- for the audit trail.
    revoked_reason: Mapped[str | None] = mapped_column(String, nullable=True)
