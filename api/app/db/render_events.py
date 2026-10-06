"""Per-render telemetry -- one row per doc_render() call, written from
routers/reports.py's `_render_one` (shared by `/render`, `/render/batch`,
and `/run`) so "how many times has this template been rendered" and "how
long does it take" reflect every entry point, not just the authenticated
`/run` route. See app/render_log.py for the (best-effort) writer, and
specs/admin_dashboard_design.md for why this didn't exist before and
what it feeds (the "popular templates"/render-time-stats dashboard
panel).
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class RenderEvent(Base):
    __tablename__ = "report_render_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.report_id"), nullable=False)
    # Denormalized off the report at write time (reports can move
    # orgs/be deleted; this keeps historical rows queryable by org
    # without a join, matching AuthEvent's own org_id column).
    org_id: Mapped[str | None] = mapped_column(String, nullable=True)
    format: Mapped[str] = mapped_column(String, nullable=False)  # "docx" | "pdf" | "png" | "xlsx"
    backend: Mapped[str | None] = mapped_column(String, nullable=True)  # "libreoffice" | "weasyprint"
    status: Mapped[str] = mapped_column(String, nullable=False)  # "success" | "error"
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null on error
    triggered_by: Mapped[str] = mapped_column(String, nullable=False)  # "public" (/render, /render/batch) | "run" | "embed" (/embed-run, a signed ticket)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # only set for triggered_by="run"
    created_at: Mapped[str] = mapped_column(String, nullable=False)
