"""GET /api/v1/users/{id}/overview -- see app/user_overview.py."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Level = Literal["view", "render", "manage"]


class OverviewRole(BaseModel):
    name: str
    expires_at: str | None = None


class OverviewTemplate(BaseModel):
    report_id: str
    name: str
    template_ext: str
    folder_path: list[str]
    is_draft: bool
    versions: int  # versions this user uploaded
    last_upload_at: str | None = None
    started: bool  # they uploaded its first version
    access_level: Level | None = None  # what they hold on it now (None: they uploaded it but can no longer open it)


class OverviewTemplates(BaseModel):
    contributed: int
    started: int
    versions: int
    by_type: dict[str, int]
    items: list[OverviewTemplate]  # most recent upload first, at most 50


class OverviewReach(BaseModel):
    total: int  # templates in their organization
    org_wide: str | None = None  # the permission that opens every template (report:manage...), if any
    manage: int
    render: int
    view: int


class PermissionSource(BaseModel):
    kind: Literal["role", "direct"]
    name: str | None = None  # the role's name
    expires_at: str | None = None


class OverviewPermission(BaseModel):
    code: str
    description: str
    sources: list[PermissionSource]


class OverviewFolderGrant(BaseModel):
    grant_id: str
    folder_id: str
    path: list[str]
    is_project: bool
    level: Literal["view", "manage"]
    via_role: str | None = None  # None: granted to the user directly
    expires_at: str | None = None
    templates: int  # templates in that folder and below


class OverviewReportGrant(BaseModel):
    grant_id: str
    report_id: str
    name: str
    template_ext: str
    level: Level
    via_role: str | None = None
    expires_at: str | None = None
    parameter_limits: dict[str, list[str]] | None = None  # the filter values this grant is narrowed to


class UserOverview(BaseModel):
    user_id: str
    is_system_admin: bool
    roles: list[OverviewRole]
    templates: OverviewTemplates
    reach: OverviewReach
    permissions: list[OverviewPermission]
    folder_grants: list[OverviewFolderGrant]
    report_grants: list[OverviewReportGrant]
