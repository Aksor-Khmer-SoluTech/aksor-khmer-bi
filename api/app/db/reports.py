from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ReportRow(Base):
    """One row per registered report -- mirrors ReportMeta in models.py
    field-for-field. created_at/updated_at stay plain ISO 8601 strings
    (not a DateTime column) so the API's JSON response shape is unchanged
    by this migration -- report_store.py generates them exactly as before
    (`datetime.now(timezone.utc).isoformat()`), just persists them here
    instead of in meta.json.
    """

    __tablename__ = "reports"

    report_id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    folder_id: Mapped[str | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    template_ext: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    sample_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Only set for template_ext="html": maps each `{{ resource('name') }}`
    # reference found in the template (see app/html_template.py) to the
    # uploaded resource it resolves to at render time --
    # {"logo.png": {"kind": "image", "id": "<image_resource id>"}, ...}.
    # Null for docx/xlsx, which have no such references.
    resource_bindings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Filter-parameter definitions for the end-user run form:
    # [{"name": "p_branch", "label": "Branch", "options": [{"value": "BR01", "label": "Phnom Penh"}, ...]}, ...].
    # A parameter with an `options` list is the kind a grant can limit
    # (see ReportAccessGrant.parameter_limits); one without is free text.
    # Never returned by the public GET /reports routes -- managers read/
    # write it through /reports/{id}/data-config, users get only the
    # options they may use through /reports/{id}/run-form.
    parameters: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Where the server fetches this report's data when a user runs it:
    # {"url": ..., "method": "GET"|"POST", "headers": {...}, "body_template": ..., "auth": {...}}.
    # May carry header values, so it's manager-only like `parameters`
    # (see app/report_data.py for the shape, validation and fetch).
    data_source: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # This report's own extra Khmer protected-terms layer, on top of the
    # deployment-wide default (aksor_khmer_ocr_segmenter's built-ins +
    # AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE/_DIR): {"set_ids": [...] (a
    # ProtectedTermSet's id -- app/db/protected_terms.py, live reference
    # not a copy), "terms": [...] (this report's own inject list),
    # "exclude_terms": [...] (this report's own exclude list)}. Manager-
    # only like parameters/data_source; resolved at render time by
    # app/protected_terms_config.py's resolve_protected_terms. See
    # specs/protected_terms_design.md.
    protected_terms_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # If true, every user in this report's own organization automatically
    # gets "view" access, as if they held a report:view grant -- see
    # app/rbac.py's has_report_access. Never implies render/manage: running
    # a report still needs an explicit grant, same as today.
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Made with the New report wizard and not yet published: only people who manage the report see it, in lists or
    # runs (app/routers/report_wizard.py). Registering a finished template directly publishes it at once.
    is_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # Optional report code -- an alternative to `report_id` in every
    # /api/v1/reports/{ref}/... route, so an integration or an <iframe> can say
    # `revenue-comparison` instead of an id that differs per environment. Globally
    # unique (the public render routes have no org to scope by), lowercase; rules
    # and resolution in app/report_ref.py, design in specs/report_codes_design.md.
    code: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)


class CodeReservation(Base):
    """The first organization to claim a report code keeps it permanently -- kept
    after the report is renamed or deleted -- so a freed code can't be claimed by
    another tenant and start receiving the first tenant's integration traffic.
    No foreign keys: the record has to outlive the report (and org) it names."""

    __tablename__ = "report_code_reservations"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
