"""A named, reusable, org-scoped list of Khmer protected terms (see
aksor_khmer_ocr_segmenter's own protected_terms package for what "protected
term" means) -- a manager creates one of these once and selects it into
any number of reports by id (ReportRow.protected_terms_config's
`set_ids`, see app/db/reports.py), rather than copying the same list into
every report's own config. No folder_id -- unlike ImageResource/
StylesheetResource, these aren't filed in the Resources folder tree, just
a flat per-org list (same shape as Job in app/db/jobs.py in that regard).

See specs/protected_terms_design.md for the full design and
app/protected_term_sets_store.py for the plain-CRUD store module.
"""
from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class ProtectedTermSet(Base):
    __tablename__ = "protected_term_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # inject
    exclude_terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # exclude
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
