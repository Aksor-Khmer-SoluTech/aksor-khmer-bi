"""Analyze (app/analyze.py): pivot a dataset, export it, keep the view."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnalyzeDataset(BaseModel):
    name: str
    title: str
    description: str | None = None
    access_mode: Literal["open", "restricted"]
    field_count: int
    measure_count: int


class PivotLayout(BaseModel):
    source: str | None = Field(None, description="Which of the dataset's lists to analyze; omitted: the first")
    rows: list[str] = Field(default_factory=list, description="Fields down the side (up to 3)")
    columns: list[str] = Field(default_factory=list, description="Fields across the top (up to 3)")
    values: list[str] = Field(default_factory=list, description="Measure keys, or __rows for the row count (up to 6)")
    buckets: dict[str, Literal["day", "month", "year"]] = Field(default_factory=dict, description="Group a date field by day, month or year")


class PivotRequest(BaseModel):
    dataset: str
    org_id: str | None = None
    values: dict[str, str] = Field(default_factory=dict, description="The dataset's filter values")
    layout: PivotLayout


class ExportRequest(PivotRequest):
    format: Literal["pdf", "docx", "xlsx"]
    chart: Literal["table", "bar", "line"] = "table"
    title: str | None = Field(None, max_length=200)


class AnalysisConfig(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    layout: PivotLayout
    view: Literal["table", "bar", "line"] = "table"


class AnalysisWrite(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    dataset: str
    config: AnalysisConfig


class AnalysisOut(BaseModel):
    id: str
    org_id: str
    title: str
    dataset: str
    config: AnalysisConfig
    created_at: str
    updated_at: str


class DashboardTile(BaseModel):
    id: str
    title: str
    dataset: str
    values: dict[str, str] = Field(default_factory=dict)
    layout: PivotLayout
    view: Literal["table", "bar", "line", "kpi"] = "table"
    width: Literal[1, 2, 3] = 2


class DashboardCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    org_id: str | None = None


class DashboardUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    tiles: list[DashboardTile] = Field(default_factory=list)
    filters: dict[str, str] = Field(default_factory=dict, description="Shared filter values, by filter name")


class DashboardSharing(BaseModel):
    role_ids: list[str] = Field(default_factory=list, description="The roles that may view it; empty = yours alone")


class TileRun(BaseModel):
    filters: dict[str, str] = Field(default_factory=dict, description="Filter values changed on the page, by name")


class DashboardSummary(BaseModel):
    id: str
    title: str
    description: str | None = None
    tile_count: int
    owner: str
    mine: bool
    shared: bool
    updated_at: str


class DashboardOut(BaseModel):
    id: str
    org_id: str
    title: str
    description: str | None = None
    tiles: list[DashboardTile]
    filters: dict[str, str]
    shared_role_ids: list[str]
    owner: str
    can_edit: bool
    filter_bar: list[dict] = Field(default_factory=list, description="The tiles' filters, merged by name, narrowed to your values")
    created_at: str
    updated_at: str
