"""Datasets: one governed definition of a body of data -- its source (the same shape as a report's data source),
its filters, and what its fields and measures mean -- that many reports build on. See app/datasets.py."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_datasets_org_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    # What a report refers to it by: lowercase letters, digits, single hyphens/underscores -- fixed once created.
    name: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    parameters: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_source: Mapped[dict] = mapped_column(JSON, nullable=False)
    # [{name, type, label, label_km, format, hidden}] -- what each column means and how it reads.
    fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # [{key, label, label_km, kind, field, list, where, numerator, denominator, format}] -- named calculations.
    measures: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # "open": anyone who may run a report built on it may use it (the report's own grants decide). "restricted": only
    # the people and roles in dataset_access_grants, each within their filter limits -- on top of the report's grants.
    # A switch of its own, so revoking the last grant never quietly opens a restricted dataset up.
    access_mode: Mapped[str] = mapped_column(String, nullable=False, default="open", server_default="open")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class DatasetAccessGrant(Base):
    """Who may use a restricted dataset (Dataset.access_mode == "restricted") and with which filter values -- the
    dataset's row-level access, applied to every report built on it (app/datasets.py effective_limits). Same shape
    and semantics as ReportAccessGrant: a user or a role, additive (the union of a person's grants counts), an
    optional expiry, revoked by is_active=False so the audit trail keeps what was granted."""

    __tablename__ = "dataset_access_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "role"
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    # "run": reports built on it run for them. "build": also may choose it as a report's data source.
    level: Mapped[str] = mapped_column(String, nullable=False)
    # {"p_branch": ["BR02"]}: may only use it with those values; a filter left out is unrestricted by this grant.
    parameter_limits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    granted_at: Mapped[str] = mapped_column(String, nullable=False)
    granted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
