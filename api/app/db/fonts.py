"""Fonts added at runtime (Resources > Fonts), kept on disk (app/font_store.py), described here.

A font is installed for the whole server, not for one organization: LibreOffice, WeasyPrint and the chart renderer
all draw with it, whichever organization's template names it. So there is no org column; who may add or remove one is
the `font:manage` permission, which only system administrators hold by default."""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class FontResource(Base):
    """One row per uploaded font file.

    The file lives at data/font_resources/<id>.<ttf|otf> -- named by id, never by the uploaded filename. `sha256`
    is unique, so the same file can't be uploaded twice; (`family_key`, `subfamily_key`) is unique, so two files
    can't both claim to be "Khmer OS Siemreap Regular" (which of them a template got would be a coin toss)."""

    __tablename__ = "font_resources"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_font_resources_sha256"),
        UniqueConstraint("family_key", "subfamily_key", name="uq_font_resources_family_style"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    family: Mapped[str] = mapped_column(String, nullable=False)  # what a template names it by
    family_key: Mapped[str] = mapped_column(String, nullable=False)  # lower-cased
    subfamily: Mapped[str] = mapped_column(String, nullable=False)  # Regular, Bold, Italic ...
    subfamily_key: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    postscript_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    version: Mapped[str] = mapped_column(String, nullable=False, default="")
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=400)
    italic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    glyph_count: Mapped[int] = mapped_column(Integer, nullable=False)
    khmer_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latin_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    has_layout_tables: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    copyright: Mapped[str] = mapped_column(String, nullable=False, default="")
    license: Mapped[str] = mapped_column(String, nullable=False, default="")
    license_url: Mapped[str] = mapped_column(String, nullable=False, default="")
    embedding: Mapped[str] = mapped_column(String, nullable=False, default="")
    note: Mapped[str] = mapped_column(String, nullable=False, default="")
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_ext: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
