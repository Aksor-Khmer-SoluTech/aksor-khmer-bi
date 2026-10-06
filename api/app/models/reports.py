from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ResourceBinding(BaseModel):
    kind: str = Field(..., description="'image' or 'stylesheet' — which store `id` resolves against")
    id: str = Field(..., description="The image_resources or stylesheet_resources id this reference resolves to")


class ReportMeta(BaseModel):
    report_id: str = Field(..., description="Generated id — pass this to /render")
    org_id: str | None = Field(None, description="Owning organization — see app/rbac.py")
    folder_id: str | None = Field(None, description="Resources folder this report is filed in, if any — see app/routers/folders.py")
    name: str
    description: str | None = None
    template_ext: str = Field(..., description="'docx', 'xlsx', or 'html'")
    version: int = Field(..., description="Increments each time the template file is replaced")
    version_label: str | None = Field(None, description="The current version's uploader-chosen name, e.g. '1.0.1'; null when none was given")
    created_at: str = Field(..., description="ISO 8601 UTC timestamp")
    updated_at: str = Field(..., description="ISO 8601 UTC timestamp")
    sample_context: dict | None = Field(
        None,
        description="A known-good example render payload, saved via PATCH — "
        "used to seed the portal's Try-it/Integrate panels, not required for rendering",
    )
    resource_bindings: dict[str, ResourceBinding] | None = Field(
        None,
        description="template_ext='html' only — maps each {{ resource('name') }} reference "
        "found in the template to the uploaded image/stylesheet resource it resolves to",
    )
    is_public: bool = Field(
        False,
        description="If true, every user in this report's organization automatically gets 'view' "
        "access (running it still needs an explicit grant) — see app/rbac.py's has_report_access",
    )
    code: str | None = Field(
        None,
        description="Optional code: use it in place of `report_id` in any /api/v1/reports/{ref}/... "
        "path, or in #/embed/{ref}. Lowercase letters, digits and single hyphens, 3-64 chars, globally unique.",
    )


class ParameterOption(BaseModel):
    value: str
    label: str | None = None


# The HTML input shape a free-text parameter (no options/options_source)
# renders as -- see ParameterField in portal/src/components/RunReportPage.tsx.
# Meaningless once options/options_source is set (always a <select> then);
# stored regardless so switching a parameter back to free text doesn't lose
# a manager's previous choice.
ParameterType = Literal["text", "number", "date", "datetime", "time"]


class DataSourceAuth(BaseModel):
    type: Literal["basic", "bearer"]
    username: str | None = None
    # A credential is exactly one of two things, never a value here: the
    # *name* of an environment variable on the API server (same convention
    # scheduled jobs' rest_call uses, app/job_executors.py), or the *name* of
    # a Secret -- a credential created, rotated and revoked in the portal
    # (Admin > Secrets; app/secrets.py), resolved only for the one call that
    # needs it. Which one is a deployment's choice, made per data source.
    password_env: str | None = None
    token_env: str | None = None
    password_secret: str | None = None
    token_secret: str | None = None


class OptionsSource(BaseModel):
    """Where a parameter's choices come from, fetched by the *server* at
    run-form/run time instead of being a static `options` list saved on
    the report -- same connection/url/method/headers/auth conventions as
    DataSource (see app/report_data.py for the shared fetch/validation
    logic), deliberately with no Jinja templating step: unlike a report's
    own data_source, this never sees the caller's other filter values, so
    there's no cross-parameter (cascading-dropdown) ordering to solve for
    now -- it's an independent lookup, the same on every request.

    The response is read with JSONPath (app/jsonpath.py): `items_path` finds
    the list of choices, `value_field` and `label_field` say where each one's
    value and label are.
    """

    connection: str | None = Field(
        None,
        description="Name of a connection (Admin > Connections): its base URL, headers and authentication are used, "
        "and `url` is then only the path after the base URL (starting with /)",
    )
    url: str = Field("", description="A complete http(s) URL, or -- with a connection -- just the path after its base URL")
    method: Literal["GET", "POST"] = "GET"
    headers: dict[str, str] | None = Field(None, description="Extra headers; with a connection, added to (and overriding) the connection's own")
    body: dict | None = None  # POST only, sent as-is -- no substitution
    auth: DataSourceAuth | None = Field(None, description="Not allowed with a connection: authentication comes from the connection")
    items_path: str | None = Field(
        None,
        description="JSONPath to the list of choices in the response, e.g. $.data or $.data[*]. "
        "Omitted: the response itself must be the list",
    )
    value_field: str = Field(
        ...,
        description="Where each item's value is, relative to the item: a key (code), a path (name.en), "
        "or a template (${code}-${branch}). Kept named `value_field` for configs saved before JSONPath",
    )
    label_field: str | None = Field(
        None, description="Where each item's label is, same forms as value_field, e.g. ${code} - ${nameEn}; omitted falls back to the value"
    )


class ReportParameter(BaseModel):
    """A filter parameter the end-user run form asks for. With `options`
    it's a static choice list a grant can narrow (e.g. p_branch -> the
    branches a user may run the report for); with `options_source`, the
    same kind of choice list but fetched from a REST API at run-form/run
    time instead (mutually exclusive with `options` -- enforced in
    app/report_data.py's validate_data_config, not here). Without either,
    a free-text value. Structural only -- the limits/uniqueness/name
    rules live in app/report_data.py's validate_data_config, which raises
    readable 400s (FastAPI's own 422 for a Pydantic constraint has an
    array `detail` the portal can't show).
    A free-text parameter (no `options`/`options_source`) may carry a
    `default_value`: a literal, or `now()` on a date/datetime/time one. The
    run form starts with it, and a run that leaves the parameter out entirely
    uses it (a value sent as "" stays empty) -- see app/report_data.py's
    resolve_default.
    A parameter can also be marked `required=False` -- but only a
    free-text one (no `options`/`options_source`): a choice list can be
    narrowed by a grant, and letting a restricted caller simply omit it
    would bypass that restriction entirely (see
    app/report_data.py's resolve_run_parameters), so a select-shaped
    parameter always stays mandatory regardless of this flag.
    """

    name: str
    label: str | None = None
    type: ParameterType = "text"
    required: bool = True
    default_value: str | None = Field(
        None,
        description="Free-text/number/date/time parameters only: the value the run form starts with, and the one a "
        "run that leaves this parameter out uses. `now()` on a date, datetime or time parameter means the moment of the run",
    )
    options: list[ParameterOption] | None = None
    options_source: OptionsSource | None = None


class DataSource(BaseModel):
    """Where the server gets a report's data when a user runs it, by `type`:

    * `rest` -- fetch it from a REST API. `url` and `body_template` may
      reference the report's filter parameters as `{{ p_branch }}`.
    * `jdbc` -- run a read-only SQL `query` against a database connection
      (Admin > Connections). Filter parameters are bound as `:p_branch`.
    * `static` -- fixed sample data (`static_data`), for building a template
      before any real source exists.

    See app/report_data.py."""

    type: Literal["rest", "jdbc", "static"] = Field("rest", description="How the data is obtained")
    connection: str | None = Field(
        None,
        description="Name of a connection (Admin > Connections): for `rest`, its base URL, headers and authentication "
        "are used and `url` is then only the path after the base URL (starting with /); for `jdbc`, the database to query",
    )
    url: str = Field("", description="rest: a complete http(s) URL, or -- with a connection -- just the path after its base URL")
    method: Literal["GET", "POST"] = "GET"
    headers: dict[str, str] | None = None
    body_template: dict | str | None = None
    auth: DataSourceAuth | None = Field(None, description="Not allowed with a connection: authentication comes from the connection")
    query: str | None = Field(None, description="jdbc: one SELECT (or WITH ... SELECT); `:name` binds a filter parameter's value")
    root_key: str | None = Field(None, description="jdbc: the key the rows are returned under for the template to loop over (default rows)")
    typed_binding: bool = Field(
        False,
        description="jdbc: hand a built-in driver each filter as its declared type (a real date or number) instead of text, "
        "so the query needs no CAST. Uploaded drivers always get text.",
    )
    static_data: dict | None = Field(None, description="static: the JSON object the template is rendered with")


class DataConfig(BaseModel):
    """Manager-only view of a report's run configuration (GET/PUT
    /reports/{id}/data-config). Deliberately not part of ReportMeta:
    that's returned by the public GET routes, and this can hold header
    values and the full option lists a grant is meant to narrow."""

    parameters: list[ReportParameter] = Field(default_factory=list)
    data_source: DataSource | None = None


class RunFormParameter(BaseModel):
    name: str
    label: str | None = None
    type: ParameterType = Field("text", description="Which HTML input a free-text parameter (options is null) renders as; ignored otherwise")
    required: bool = Field(True, description="A choice-list parameter (options isn't null) is always required regardless of this flag")
    default_value: str | None = Field(
        None,
        description="What to start the field with, as configured -- a literal, or `now()` for the moment the form is opened. "
        "The portal resolves `now()` from the viewer's own clock. Null for a choice list",
    )
    options: list[ParameterOption] | None = Field(
        None, description="Only the options the caller may use; null means a free-text parameter"
    )


class RunForm(BaseModel):
    """GET /reports/{id}/run-form -- what the run page renders. Option lists
    arrive already narrowed to the caller's grants, so a value they may not
    use is never sent to the browser at all."""

    report_id: str
    name: str
    description: str | None = None
    template_ext: str
    access_level: Literal["render", "manage"]
    formats: list[str]
    parameters: list[RunFormParameter]


class RunRequest(BaseModel):
    parameters: dict[str, str] = Field(default_factory=dict)
    format: Literal["docx", "pdf", "png", "xlsx"] = "pdf"
    part: int | None = Field(
        None,
        ge=1,
        description="If the report is split into several files, return only this one (1-based) instead of a ZIP of all of them",
    )


class EmbedRunRequest(RunRequest):
    """POST /reports/{id}/embed-run -- what an embedded viewer posts: the report's
    parameter values (the same ones /run takes) plus what authorizes them, one of:

    * a signed `ticket` for exactly these values (app/embed_tickets.py);
    * an API client's `client_id` + `client_secret` (app/clients.py), which
      must have been granted this report.

    Otherwise the request is refused."""

    ticket: str | None = Field(None, min_length=1, max_length=8192)
    client_id: str | None = Field(None, min_length=1, max_length=64)
    client_secret: str | None = Field(None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def _one_way_to_authorize(self) -> "EmbedRunRequest":
        if (self.client_id is None) != (self.client_secret is None):
            raise ValueError("client_id and client_secret go together")
        if self.client_id is not None and self.ticket is not None:
            raise ValueError("Send a ticket or client credentials, not both")
        return self


class BatchLimits(BaseModel):
    """GET /reports/batch-limits -- the most records one batch-render request
    may hold, per output format, and roughly how long each record takes (so a
    client can say "about a minute" before sending)."""

    max_records: dict[str, int]
    seconds_per_record: dict[str, float]


class AccessibleReport(BaseModel):
    """One row of GET /reports/accessible -- the portal's end-user
    "Reports" page. Deliberately leaner than ReportMeta: no sample_context,
    resource_bindings, org/folder ids, or anything else that's about
    *integrating* a template rather than opening a report someone was
    granted -- least data for the least-privileged audience.
    """

    report_id: str
    name: str
    description: str | None = None
    template_ext: str
    version: int
    version_label: str | None = None
    updated_at: str
    access_level: Literal["view", "render", "manage"] = Field(
        ..., description="The highest level the caller holds on this report -- via a global report:* permission, a report grant, or a folder grant"
    )


class TemplateSyntaxIssue(BaseModel):
    message: str
    line: int | None = None
    column: int | None = None


class ParsedTemplate(BaseModel):
    """Response of POST /reports/parse-template — a pre-flight look at an
    HTML template before it's registered: does it parse as valid Jinja2,
    what top-level variables does it expect, and which resource() names
    does it reference (so the register dialog can show a mapping step
    before the user commits to registering it). See app/html_template.py.
    """

    fields: list[str] = Field(..., description="Best-effort list of Jinja2 placeholder names found in the template")
    resources: list[str] = Field(..., description="Literal names passed to resource(...) calls in the template")
    errors: list[TemplateSyntaxIssue] = Field(default_factory=list, description="Jinja2 syntax errors, if any")


class VersionUpdate(BaseModel):
    """PATCH /reports/{id}/versions/{n}. Send only what changes; `null` or an
    empty string clears the label (back to v<N>) or the note."""

    version_label: str | None = None
    note: str | None = Field(None, max_length=1000)


class ReportUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    sample_context: dict | None = None
    # Unlike the fields above (where `None` always means "leave
    # unchanged" -- there's no way to clear name/description/
    # sample_context via this endpoint today), `folder_id` needs a third
    # state: "move to root" is a real, expected operation (dragging a
    # report out of every folder), not just "don't touch." The router
    # checks `"folder_id" in body.model_fields_set` rather than `is not
    # None` for this one field, so `{"folder_id": null}` in the request
    # body actually clears it instead of being indistinguishable from
    # omitting the field entirely.
    folder_id: str | None = None
    is_public: bool | None = None
    # Same third state as folder_id: omitted = leave the code alone, null (or "")
    # = remove it. Checked via `"code" in body.model_fields_set`.
    code: str | None = None


class ReportSchema(BaseModel):
    fields: list[str] = Field(..., description="Best-effort list of Jinja2 placeholder names found in the template")
    engine: str = Field(..., description="How the fields were detected: 'docxtpl' or 'regex-scan'")
    note: str = Field(
        ...,
        description="Caveat about detection confidence — this is best-effort, not a guaranteed-complete schema",
    )


class OptionsPreviewRequest(BaseModel):
    """POST /reports/{id}/data-config/preview-options -- try an options source (saved or not) and see the choices it would give."""

    options_source: OptionsSource


class OptionsPreview(BaseModel):
    total: int = Field(..., description="How many choices the source produced")
    options: list[ParameterOption] = Field(..., description="The first few of them")
