"""Change audit trail -- one row per administrative mutation ("who changed
what, when, from where, and what the values were before and after"), the
counterpart to AuthEvent (who signed in) and AccessDeniedEvent (who was
refused) for the third question an investigation asks: what actually got
changed. See app/audit.py for the writer and the field-diff/redaction
helpers, and routers/audit.py for the admin feed.

Deliberately *no* foreign keys (not even org_id/user_id, which every
sibling event table does declare): an audit record has to outlive the
thing it describes. A deleted user, report or organization is exactly the
case an investigator most needs the trail for, and a real FK would either
block the delete or (with ON DELETE CASCADE) erase the evidence with it.
`entity_label` and `actor_username` are denormalized for the same reason
-- they say what the row *was called* at the time, whatever it's called
(or whether it exists) now.

Append-only by convention: no route updates or deletes these rows.
"""
from __future__ import annotations

from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_events_org_created", "org_id", "created_at"),
        Index("ix_audit_events_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    created_at: Mapped[str] = mapped_column(String, nullable=False)  # ISO 8601 UTC, like every timestamp here
    # Who. Null user id for the break-glass superuser (no row backs it) or
    # for work the platform did on its own; the username is always kept.
    actor_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_username: Mapped[str] = mapped_column(String, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    # Whose data. Null only for platform-wide things (e.g. creating an org).
    org_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # What. `action` is "<entity_type>.<verb>", e.g. "report.file_replace".
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    entity_label: Mapped[str | None] = mapped_column(String, nullable=True)
    # One human sentence, written at the time -- what the feed shows.
    summary: Mapped[str] = mapped_column(String, nullable=False)
    # [{"field": "name", "before": "A", "after": "B"}, ...] -- secrets are
    # redacted before they get here (app/audit.py), never stored raw.
    changes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Anything else worth having when investigating (version numbers,
    # checksums, the role/permission that was granted, ...). Named
    # `details` because `metadata` is reserved on a declarative class.
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
