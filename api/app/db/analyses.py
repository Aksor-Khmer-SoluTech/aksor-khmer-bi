"""Saved Analyze views: a dataset, its filter values and a pivot layout, kept by the person who made it
(app/analyze.py). Private to that person for now; Phase 4 puts them on dashboards."""
from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    # The dataset's name (what reports refer to it by) -- a view of a dataset that's gone just can't run.
    dataset: Mapped[str] = mapped_column(String, nullable=False)
    # {source, values, rows, columns, measures, buckets, view}: everything to run it again.
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
