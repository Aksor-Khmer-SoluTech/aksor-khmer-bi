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


class FolderOut(BaseModel):
    id: str
    org_id: str
    parent_folder_id: str | None = None
    name: str
    description: str | None = None
    created_by: str | None = None
    created_at: str
    updated_at: str


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
    created_by: str | None = None
    created_at: str
    updated_at: str


class StylesheetOut(BaseModel):
    id: str
    org_id: str
    folder_id: str | None = None
    name: str
    content_type: str
    size_bytes: int
    created_by: str | None = None
    created_at: str
    updated_at: str
