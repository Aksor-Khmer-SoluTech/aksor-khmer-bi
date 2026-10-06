"""Generic per-user settings -- one row per (user, code), the value stored
as JSON, so a new preference is a new `code` string rather than a new
column on `users` plus a migration (which is how `notify_new_signin`
and the avatar/TOTP fields got here). The store deliberately knows
nothing about what any individual code means or which values it allows:
each consumer (the portal's Preferences tab today) validates what it
reads back and falls back to its own default, so an unknown or stale
value degrades to "use the default" instead of failing.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class UserSetting(Base):
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_user_settings_user_code"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Lowercase dotted/snake identifier, e.g. "report_preview_layout" --
    # format enforced at the API boundary (models/settings.py).
    code: Mapped[str] = mapped_column(String, nullable=False)
    # Any non-null JSON value (string, number, bool, list, object). "Unset"
    # is the absence of the row, never a stored null -- see
    # models/settings.py's UserSettingUpdate.
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
