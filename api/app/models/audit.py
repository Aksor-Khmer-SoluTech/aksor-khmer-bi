from typing import Any, Literal

from pydantic import BaseModel, Field


class AuditEventOut(BaseModel):
    """One row of the change audit trail -- see app/db/audit.py."""

    id: str
    created_at: str = Field(..., description="ISO 8601 UTC timestamp")
    actor_username: str
    actor_user_id: str | None = None
    ip_address: str | None = None
    org_id: str | None = None
    action: str = Field(..., description="'<entity_type>.<verb>', e.g. 'report.file_replace'")
    entity_type: str
    entity_id: str
    entity_label: str | None = Field(None, description="What the entity was called at the time -- survives its deletion")
    summary: str
    changes: list[dict[str, Any]] | None = Field(
        None,
        description="Field-level before/after. Each entry has `field` plus either `before`/`after`, or -- for a "
        "list of plain values -- `added`/`removed`. A secret is reported as changed (`redacted: true`), never with its value.",
    )
    details: dict[str, Any] | None = None


class AuditPage(BaseModel):
    """GET /audit -- one page, newest first, plus how many rows matched in all."""

    items: list[AuditEventOut]
    total: int
    limit: int
    offset: int


class ReportVersionOut(BaseModel):
    """One version of a report's template file -- see app/db/report_versions.py."""

    version: int
    version_label: str | None = Field(None, description="The uploader's own name for this version, e.g. '1.0.1'; null -> show v<version>")
    template_ext: str
    size_bytes: int
    size_delta: int | None = Field(None, description="Bytes gained/lost against the previous retained version; null for the first")
    sha256: str
    original_filename: str | None = Field(None, description="What the uploader's file was called on their machine")
    note: str | None = Field(None, description="The uploader's own description of what changed")
    created_by: str | None = Field(None, description="Null when unknown (a version backfilled from before history was kept)")
    created_at: str
    backfilled: bool = Field(False, description="True if this row was reconstructed from the live file, not recorded at upload")
    fields: list[str] | None = Field(None, description="Placeholder names detected in this version; null if detection failed")
    fields_added: list[str] | None = Field(None, description="Placeholders this version added vs. the previous one; null if unknown")
    fields_removed: list[str] | None = None
    identical_to_previous: bool = Field(False, description="Byte-for-byte the same file as the previous version")
    available: bool = Field(True, description="Whether the file can still be downloaded")


class ChangelogEntry(BaseModel):
    """One line of a report's timeline: either a template file version
    (`kind='version'`) or another recorded change to the report (`kind='event'`)."""

    kind: Literal["version", "event"]
    at: str
    version: ReportVersionOut | None = None
    event: AuditEventOut | None = None
    # For a version entry: the audit event that recorded the upload (who,
    # from where) -- absent for a backfilled version, which has none.
    upload_event: AuditEventOut | None = None


class ReportChangelog(BaseModel):
    """GET /reports/{id}/changelog -- the template file's version history
    merged with every other recorded change to the report, newest first."""

    report_id: str
    current_version: int
    first_retained_version: int | None = Field(
        None, description="The oldest version whose file is still held; anything below it was overwritten before history was kept"
    )
    original_available: bool = Field(..., description="Whether version 1 -- the file as first uploaded -- can be downloaded")
    entries: list[ChangelogEntry]
