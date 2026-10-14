"""Request/response models for datasets (routers/datasets.py, app/datasets.py)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .reports import DataSource, OptionsSource, ReportParameter


class DatasetField(BaseModel):
    """What one column means and how it reads. `source` is the query result it's in (rows, info…), or null for a
    single top-level value."""

    source: str | None = None
    name: str
    type: Literal["text", "number", "money", "date", "datetime", "boolean"] = "text"
    label: str | None = None
    label_km: str | None = Field(None, description="The label in Khmer")
    format: str | None = Field(None, description="How it's shown: #,##0.00 ៛, 0.0%, DD/MM/YYYY…")
    hidden: bool = Field(False, description="Hidden from report authors (an ID only joins rows, say)")


class MeasureWhere(BaseModel):
    field: str
    value: str


class DatasetMeasure(BaseModel):
    """A named calculation over the dataset's rows. Templates read it as {{ measures.<key> }} (formatted) and
    {{ measure_values.<key> }} (the number)."""

    key: str = Field(..., description="e.g. net_sales")
    label: str
    label_km: str | None = None
    kind: Literal["sum", "count", "count_distinct", "avg", "min", "max", "ratio"]
    source: str | None = Field(None, description="The result it counts over (rows…); the first list when omitted")
    field: str | None = Field(None, description="The column (not for a plain count or a ratio)")
    where: MeasureWhere | None = Field(None, description="Only rows where this field has this value")
    numerator: str | None = Field(None, description="ratio: the measure on top")
    denominator: str | None = Field(None, description="ratio: the measure below")
    format: str | None = None


class DatasetWrite(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    parameters: list[ReportParameter] = Field(default_factory=list)
    data_source: DataSource
    fields: list[DatasetField] = Field(default_factory=list)
    measures: list[DatasetMeasure] = Field(default_factory=list)


class DatasetCreate(DatasetWrite):
    org_id: str | None = Field(None, description="Organization it belongs to; defaults to the caller's own")
    name: str = Field(..., description="What reports refer to it by: lowercase letters, digits, single hyphens/underscores. Fixed once created")


class DatasetReportRef(BaseModel):
    report_id: str
    name: str
    code: str | None = None


class DatasetSummary(BaseModel):
    id: str
    org_id: str
    name: str
    title: str
    description: str | None = None
    source_type: str
    connection: str | None = None
    parameter_count: int
    field_count: int
    measure_count: int
    report_count: int
    access_mode: Literal["open", "restricted"] = "open"
    grant_count: int = 0
    updated_at: str


class DatasetOut(BaseModel):
    id: str
    org_id: str
    name: str
    title: str
    description: str | None = None
    parameters: list[ReportParameter]
    data_source: DataSource
    fields: list[DatasetField]
    measures: list[DatasetMeasure]
    reports: list[DatasetReportRef]
    access_mode: Literal["open", "restricted"] = "open"
    created_at: str
    updated_at: str


class DatasetPreviewRequest(BaseModel):
    """Run a dataset's source once -- saved or not -- with test values for its filters."""

    org_id: str | None = None
    parameters: list[ReportParameter] = Field(default_factory=list)
    data_source: DataSource
    fields: list[DatasetField] = Field(default_factory=list)
    measures: list[DatasetMeasure] = Field(default_factory=list)
    values: dict[str, str] = Field(default_factory=dict)


class MeasureResult(BaseModel):
    text: str
    value: float | None = None


class DatasetPreview(BaseModel):
    data: dict = Field(..., description="What the source returned, lists cut to their first rows")
    fields: list[DatasetField] = Field(..., description="Every column found, merged with the ones already described")
    measures: dict[str, MeasureResult] = Field(default_factory=dict)
    parameters: list[ReportParameter]
    missing: list[str] = Field(default_factory=list, description="Filters that need a test value first")
    elapsed_ms: int = 0
    truncated: bool = False


class DatasetOptionsPreviewRequest(BaseModel):
    org_id: str | None = None
    options_source: OptionsSource


class DatasetFromReport(BaseModel):
    report_id: str
    name: str
    title: str = Field(..., min_length=1, max_length=120)


class DatasetAccessMode(BaseModel):
    mode: Literal["open", "restricted"]


class DatasetGrantCreate(BaseModel):
    subject_type: Literal["user", "role"]
    subject_id: str
    level: Literal["run", "build"] = "run"
    parameter_limits: dict[str, list[str]] | None = Field(
        None, description='{"p_branch": ["BR02"]}: may only use it with those values; a filter left out is unrestricted'
    )
    expires_at: str | None = Field(None, description="ISO 8601 UTC timestamp; omit for a permanent grant")


class DatasetGrantOut(BaseModel):
    id: str
    subject_type: str
    subject_id: str
    subject_name: str
    level: str
    parameter_limits: dict[str, list[str]] | None = None
    granted_at: str
    granted_by: str | None = None
    expires_at: str | None = None
    is_active: bool


class DatasetAccess(BaseModel):
    mode: Literal["open", "restricted"]
    grants: list[DatasetGrantOut]
