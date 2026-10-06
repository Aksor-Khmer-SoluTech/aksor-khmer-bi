"""Secrets: a named, org-scoped credential value -- a bearer token, a basic-auth
password, or any other value a report's data source or a connection used to
need an environment variable for. See app/secrets.py for what a secret is and
how it's referenced and resolved.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class Secret(Base):
    """One row per credential.

    `name` is what a data source's or connection's `auth` refers to
    (`token_secret`/`password_secret` -- app/models/reports.py's
    DataSourceAuth), so it is fixed once created and unique within the
    organization, the same convention as DataConnection.name. `value_encrypted`
    is never read back by any endpoint (app/secret_store.py); a
    rotate/revoke/delete is the only way to change what it resolves to.

    `is_active=False` (revoked) is deliberately different from deleting the
    row: whatever still names this secret keeps existing, but resolving it at
    run time now fails with a readable error (app/secrets.py's resolve) --
    the same "gone out from under a report" posture app/connections.py's
    materialize already has for a deleted connection. Reactivating (setting
    it back to True) is just as simple, for a revoke that turns out to be a
    false alarm.
    """

    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_secrets_org_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    value_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
