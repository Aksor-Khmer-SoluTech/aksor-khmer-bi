"""API clients -- machine identities (client id + secret) that may run specific
reports without a user login. See specs/api_clients_design.md.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class ApiClient(Base):
    """One row per client. The secret itself is never stored: `secret_hash` is
    its SHA-256 (the secret is 256 random bits, so a fast hash is enough -- see
    app/clients.py) and `secret_prefix` is just its first characters, so an
    admin can tell two secrets apart in a list.

    `client_id` is what a caller sends alongside the secret. It is unique
    across organizations because the run endpoint has no org to scope by.
    """

    __tablename__ = "api_clients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    client_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    secret_hash: Mapped[str] = mapped_column(String, nullable=False)
    secret_prefix: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    secret_rotated_at: Mapped[str | None] = mapped_column(String, nullable=True)
    last_used_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ApiClientReport(Base):
    """A client may run this report. Same organization as the client -- enforced
    when the grant is made and re-checked on every run."""

    __tablename__ = "api_client_reports"
    __table_args__ = (UniqueConstraint("client_pk", "report_id", name="uq_api_client_reports"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    client_pk: Mapped[str] = mapped_column(ForeignKey("api_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False, index=True)
    granted_at: Mapped[str] = mapped_column(String, nullable=False)
    granted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
