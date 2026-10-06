"""Login/session audit trail -- see app/auth_events.py for the domain
logic that writes and interprets these rows.

Basic Auth has no server-side session to revoke (see app/auth.py's
module docstring), so a row here isn't literally "a session" the way a
cookie-session app would mean it -- it's a (user, ip_address, user_agent)
fingerprint, opened on first sight and its `last_seen_at` bumped on later
sightings within app/auth_events.py's SESSION_RENEW_WINDOW. That's what
lets the portal's user-settings modal show both "Active sessions" and
"Sign-in activity" off the same table instead of needing two: the former
is success=True rows within a recency window, the latter is every row
(success and failure) ordered by created_at.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class AuthEvent(Base):
    __tablename__ = "auth_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    # Null for a failed attempt against a username that doesn't resolve
    # to any user -- the raw `username` attempted is still kept below.
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    # True only for a success row whose (user_id, ip_address, user_agent)
    # fingerprint has never been seen before -- what the Notifications
    # tab's "new sign-in" alert and the bell in TopBar key off.
    is_new_device: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    last_seen_at: Mapped[str] = mapped_column(String, nullable=False)
