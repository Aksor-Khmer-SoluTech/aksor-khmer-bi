"""The Resources repository -- a nested folder tree (JasperReports
Server's own term for this) that report templates and uploaded images
can both live in, plus a fourth grant table alongside the three in
app/db/rbac.py: folder-scoped access, independent of the global
`report:*`/`folder:*` permissions. See app/rbac.py's `has_folder_access`
for why folder grants (unlike Organization.parent_org_id) *do* inherit
down the tree -- the whole point of granting access to a folder is
covering everything filed under it.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class Folder(Base):
    """`parent_folder_id` NULL means a root-level folder. Sibling-name
    uniqueness (no two folders with the same name under the same parent)
    is enforced in application code (see routers/folders.py), not a DB
    constraint -- NULL `parent_folder_id` values aren't reliably treated
    as "equal to each other" for a UNIQUE constraint's purposes across
    backends, so a DB-level constraint would under-enforce at the root.
    """

    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    parent_folder_id: Mapped[str | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class ReportShortcut(Base):
    """A report listed in a second folder, without a second copy: the shortcut is only a *placement*.
    Why: one report is often used by several departments or teams, and each wants it in its own folder so they can
    arrange (beautify) their own space; the report, its template and its permissions stay single.
    Opening it opens the original, so it carries exactly the original's permissions -- nothing here grants
    anything, and a grant on the folder holding a shortcut does not reach the report (access is only ever
    decided from the report's own grants and its own folder chain; see routers/reports.py)."""

    __tablename__ = "report_shortcuts"
    __table_args__ = (UniqueConstraint("report_id", "folder_id", name="uq_report_shortcuts_report_folder"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.report_id"), nullable=False, index=True)
    folder_id: Mapped[str] = mapped_column(ForeignKey("folders.id"), nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class FolderAccessGrant(Base):
    """Grant table #4 (see app/db/rbac.py's three) -- same shape as
    ReportAccessGrant, scoped to a folder instead of a report, with
    `permission_level` `"view"|"manage"` instead of
    `"view"|"render"|"manage"` (a folder isn't itself renderable).
    """

    __tablename__ = "folder_access_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    subject_type: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "role"
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    folder_id: Mapped[str] = mapped_column(ForeignKey("folders.id"), nullable=False)
    permission_level: Mapped[str] = mapped_column(String, nullable=False)  # "view" | "manage"
    granted_at: Mapped[str] = mapped_column(String, nullable=False)
    granted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ImageResource(Base):
    """One uploaded image -- metadata here, bytes on disk (see
    app/image_store.py, same file-on-disk + DB-row split as reports/
    report_store.py). `width_px`/`height_px` are captured at upload time
    (Pillow) purely for the library UI's thumbnail grid; they're not used
    by the render path, which reads the file fresh and lets python-docx
    auto-scale height from a given `width_mm` alone.
    """

    __tablename__ = "image_resources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    folder_id: Mapped[str | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    file_ext: Mapped[str] = mapped_column(String, nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class StylesheetResource(Base):
    """One uploaded CSS file -- same file-on-disk + DB-row split as
    ImageResource/app/stylesheet_store.py, filed in the same folder tree.
    Kept as its own table rather than folding into ImageResource (a
    `kind` discriminator column there would also force width_px/height_px
    to become nullable, touching a model several other features already
    depend on) -- a plain-text asset has no dimensions and validates
    differently (decodes as UTF-8, not Pillow), so a separate small table
    mirroring ImageResource's shape is the lower-risk change.

    Exists to back an HTML report template's `{{ resource('name.css') }}`
    references (see app/html_template.py) -- the other half of "point
    href at an uploaded resource," alongside ImageResource for `<img>`.
    """

    __tablename__ = "stylesheet_resources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    folder_id: Mapped[str | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
