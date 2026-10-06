"""Access-denied audit trail -- app/auth.py's require_permission/
require_folder_permission/require_report_permission each write one row
here right before raising their 403 (see app/security_events.py for the
best-effort writer), same posture app/auth_events.py's login rows have:
a write failure here must never interfere with the 403 (or the render)
it sits alongside.

Deliberately a *separate* table from AuthEvent, not a shared one with a
type discriminator: AuthEvent's shape (session fingerprint, renewal
window, is_new_device) is specific to *authentication*; this is about
*authorization* denials on an already-authenticated (or break-glass)
request -- a structurally different event, and AuthEvent is already
relied on/tested, safer left alone than reshaped to carry a second
concern. The two are merged back into one feed only at the query layer
(routers/security.py's GET /security/activity), not in storage.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class AccessDeniedEvent(Base):
    __tablename__ = "access_denied_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    # Null for a break-glass superuser (no user row backs it) -- username
    # is always kept regardless, same convention AuthEvent uses.
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    permission_code: Mapped[str] = mapped_column(String, nullable=False)
    resource: Mapped[str | None] = mapped_column(String, nullable=True)  # report_id, folder_id, etc.
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
