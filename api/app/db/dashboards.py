"""Dashboards (app/dashboards.py): saved Analyze views as tiles on one page, with filters shared across them, kept by
their owner and shared with roles. Each viewer sees each tile with their own access to its dataset."""
from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # [{id, title, dataset, values, layout, view (table|bar|line|kpi), width (1-3)}], in order.
    tiles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # {filter name: value}: applied to every tile whose dataset has a filter of that name.
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # The roles it's shared with (view only); empty = the owner's alone.
    shared_role_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
