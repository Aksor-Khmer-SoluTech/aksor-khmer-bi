from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class ReportVersion(Base):
    """One row per version of a report's template *file* -- the change log
    of "each file". The bytes live next to the live template at
    data/report_templates/<report_id>/versions/v<N>.<ext> (immutable
    snapshots; the live template.<ext> stays exactly where the render
    path already reads it), this row says who put them there and what
    changed.

    `fields` is the placeholder names detected in that version's file
    (see app/template_fields.py). A .docx/.xlsx can't be diffed as text,
    but "this version added {{ branch }} and dropped {{ region }}" is
    the change a person actually needs, and it falls out of comparing
    two adjacent rows' `fields` -- computed at read time, not stored.
    Null when detection failed (a malformed template must still be
    uploadable/downloadable; it just has no field summary).

    A report registered before this table existed has no rows until it's
    first looked at or replaced; report_store then backfills its current
    version (`backfilled=True`, uploader unknown). Earlier versions of
    such a report were overwritten in place and are gone -- there is
    nothing to reconstruct them from, and the changelog says so rather
    than pretending.
    """

    __tablename__ = "report_versions"
    __table_args__ = (
        UniqueConstraint("report_id", "version", name="uq_report_versions_report_version"),
        # Nulls never collide, so unlabelled versions are unaffected.
        UniqueConstraint("report_id", "version_label", name="uq_report_versions_report_label"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # What the uploader chose to call this version ("1.0.1"). `version` stays
    # the gap-free sequence that keys the stored file; the label is only what
    # people read. Null -> shown as v<version>. Unique per report (see report_store).
    version_label: Mapped[str | None] = mapped_column(String, nullable=True)
    template_ext: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    # The name the uploader's file had on their machine -- lets a person
    # recognise "Q3-notice-FINAL2.docx" in the log. Not used for storage.
    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Free text from the uploader: "what changed?" -- the one thing a
    # binary file can't tell you about itself.
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)  # username; null when unknown (backfilled)
    created_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    backfilled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
