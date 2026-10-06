from pydantic import BaseModel, Field


class ProtectedTermSetCreate(BaseModel):
    org_id: str = Field(..., description="Organization the new set belongs to")
    name: str
    description: str | None = None
    terms: list[str] = Field(default_factory=list, description="Terms ICU should never split")
    exclude_terms: list[str] = Field(default_factory=list, description="Terms to revert to ICU's default (unprotected) behavior")


class ProtectedTermSetUpdate(BaseModel):
    """Replaced wholesale, not partially patched -- same posture
    report_store.update_data_config uses for parameters/data_source."""

    name: str
    description: str | None = None
    terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)


class ProtectedTermSetOut(BaseModel):
    id: str
    org_id: str
    name: str
    description: str | None = None
    terms: list[str]
    exclude_terms: list[str]
    created_by: str | None = None
    created_at: str
    updated_at: str


class DeploymentProtectedTermsOut(BaseModel):
    """GET /protected-term-sets/deployment-floor -- the deployment-wide
    floor (env-var-pointed files aksor_khmer_ocr_segmenter reads once at
    its own import time), as last synced into the database at API boot.
    Read-only mirror, not an input to rendering -- see
    app/deployment_terms_sync.py."""

    id: str
    version: int
    terms: list[str]
    exclude_terms: list[str]
    source_paths: dict[str, str | None]
    synced_at: str


class ProtectedTermsConfig(BaseModel):
    """A report's own protected-terms layer -- GET/PUT
    /reports/{report_id}/protected-terms-config, manager-only like
    DataConfig. `set_ids` are live references to ProtectedTermSet rows
    (this report's org only), not copies -- editing a set later changes
    every report that selects it. See specs/protected_terms_design.md."""

    set_ids: list[str] = Field(default_factory=list, description="Selected ProtectedTermSet ids, resolved fresh at render time")
    terms: list[str] = Field(default_factory=list, description="This report's own extra inject terms")
    exclude_terms: list[str] = Field(default_factory=list, description="This report's own extra exclude terms")
