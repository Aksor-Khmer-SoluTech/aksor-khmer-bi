"""The Resources repository -- folders (nested, hold reports and images)
and uploaded images. See app/db/folders.py for the underlying tables and
app/rbac.py's `has_folder_access` for the authorization logic these are
shaped around.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FolderCreate(BaseModel):
    org_id: str = Field(..., description="Organization the new folder belongs to")
    name: str
    description: str | None = None
    parent_folder_id: str | None = Field(None, description="Omit/null for a root-level folder")


class FolderUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    # Same UNSET-vs-null distinction as ReportUpdate.folder_id — the
    # router checks `"parent_folder_id" in body.model_fields_set` rather
    # than `is not None`, since "move to root" (explicit null) is a real
    # operation, not just "don't touch."
    parent_folder_id: str | None = None
    is_project: bool | None = Field(None, description="Mark a top-level folder as a project (export/import as one package), or unmark it")


class FolderOut(BaseModel):
    id: str
    org_id: str
    parent_folder_id: str | None = None
    name: str
    description: str | None = None
    created_by: str | None = None
    created_at: str
    updated_at: str
    can_manage: bool = Field(False, description="List endpoint only: whether the caller may file things into this folder")
    is_project: bool = Field(False, description="A top-level folder whose contents export and import as one package")


class ResourceDuplicate(BaseModel):
    id: str
    name: str
    where: str = Field(..., description='Where it lives: "Receipts/Forms", or "(top level)"')


class ImageOut(BaseModel):
    id: str
    org_id: str
    folder_id: str | None = None
    name: str
    content_type: str
    file_ext: str
    width_px: int
    height_px: int
    size_bytes: int
    sha256: str | None = None
    created_by: str | None = None
    created_at: str
    updated_at: str
    duplicates: list[ResourceDuplicate] = Field(
        default_factory=list, description="Upload only: other files here with exactly this content -- the same file uploaded twice"
    )


class StylesheetOut(BaseModel):
    id: str
    org_id: str
    folder_id: str | None = None
    name: str
    content_type: str
    size_bytes: int
    sha256: str | None = None
    source_format: str = Field("css", description="What was uploaded: css, scss, sass or less (templates always get the compiled CSS)")
    created_by: str | None = None
    created_at: str
    updated_at: str
    duplicates: list[ResourceDuplicate] = Field(
        default_factory=list, description="Upload only: other files here with exactly this content -- the same file uploaded twice"
    )
