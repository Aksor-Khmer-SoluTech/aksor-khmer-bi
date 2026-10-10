export type TemplateExt = "docx" | "xlsx" | "html";
export type RenderFormat = "docx" | "pdf" | "png" | "xlsx";

/** GET /reports/batch-limits: the most records one batch-render request may
 * hold per output format (pdf/png cost ~2 s a record -- each is a LibreOffice
 * conversion -- docx/xlsx ~10 ms), and roughly how long each takes. */
export interface BatchLimits {
  max_records: Record<RenderFormat, number>;
  seconds_per_record: Record<RenderFormat, number>;
}

/** What a render/run call hands back. A report whose table is over the
 * server's per-file row limit is split into `parts` files: asked for as a
 * whole it comes back as one ZIP (`parts` > 1, no `part`); asked for one
 * `part` it comes back as just that file. `parts` is 1 for an ordinary report. */
export interface RenderResult {
  blob: Blob;
  filename: string;
  parts: number;
  part: number | null;
  /** What the server says it rendered -- the report's name and template type. Sent by the
   * parameter-driven routes (/run, /embed-run), so a caller needn't look the report up first. */
  report?: { name: string; ext: TemplateExt };
}

export const FORMATS_BY_EXT: Record<TemplateExt, RenderFormat[]> = {
  docx: ["pdf", "png", "docx"],
  xlsx: ["xlsx"],
  html: ["pdf", "png"],
};

// A single `{{ resource('name') }}` reference inside an html-ext report's
// template, resolved to the uploaded image/stylesheet it should render as
// — see api/app/html_template.py. Set at register time (RegisterDialog's
// resource-mapping step), stored on the report, and resolved to real
// bytes again at render time server-side.
export interface ResourceBinding {
  kind: "image" | "stylesheet";
  id: string;
}

export interface ReportMeta {
  report_id: string;
  org_id: string | null;
  folder_id: string | null;
  name: string;
  description: string | null;
  template_ext: TemplateExt;
  version: number;
  /** The current version's uploader-chosen name ("1.0.1"); null -> show v{version}. */
  version_label: string | null;
  created_at: string;
  updated_at: string;
  sample_context: Record<string, unknown> | null;
  resource_bindings: Record<string, ResourceBinding> | null;
  is_public: boolean;
  /** Optional code: usable in place of report_id in any /reports/{ref}/... path and in #/embed/{ref}. */
  code: string | null;
  /** Made with the New report wizard and not published yet: only people who manage it see or run it. */
  is_draft?: boolean;
}

export type ReportAccessLevel = "view" | "render" | "manage";

// One row of GET /reports/accessible -- what the end-user Reports page
// lists: only reports the caller holds a route to, with the highest level
// they hold on each. Leaner than ReportMeta on purpose (no sample_context,
// bindings, ids of org/folder): see api/app/models/reports.py.
export interface AccessibleReport {
  report_id: string;
  name: string;
  description: string | null;
  template_ext: TemplateExt;
  version: number;
  version_label: string | null;
  updated_at: string;
  access_level: ReportAccessLevel;
  /** The Resources folders it is filed in, outermost first -- only those the viewer may open. */
  folder_path: { id: string; name: string }[];
  /** Other folders it is listed in -- links to this report, carrying its access and no more. */
  shortcuts: { id: string; folder_path: { id: string; name: string }[] }[];
  /** Not published yet -- only listed for people who manage it. */
  is_draft?: boolean;
}

/** A report listed in a second folder (see api/app/db/folders.py's ReportShortcut). */
export interface ReportShortcut {
  id: string;
  report_id: string;
  folder_id: string;
  created_at: string;
}

// --- Filter parameters, data source, and the end-user run form ------------
// See api/app/report_data.py: a report's manager defines filter parameters
// (an option list is what a grant can narrow) and a REST data source the
// server calls -- after checking the user's limits -- when they run it.

export interface ParameterOption {
  value: string;
  label: string | null;
}

/** Which HTML input a free-text parameter (no options/options_source)
 * renders as -- meaningless once either is set (always a <select> then).
 * See api/app/report_data.py's PARAMETER_TYPES. */
export type ParameterType = "text" | "number" | "date" | "datetime" | "time";

export interface DataSourceAuth {
  type: "basic" | "bearer";
  username?: string | null;
  // A credential is exactly one of two things, never a value here: the name
  // of an environment variable on the API server, or the name of a Secret
  // (Admin > Secrets -- see types.ts's own Secret) resolved at run time.
  password_env?: string | null;
  token_env?: string | null;
  password_secret?: string | null;
  token_secret?: string | null;
}

// Where a parameter's own choices come from, fetched by the *server* at
// run-form/run time instead of being the static `options` list below --
// see api/app/models/reports.py's OptionsSource. Edited on the Parameters
// tab (ParametersTab.tsx).
export interface OptionsSource {
  /** Name of a connection (Admin > Connections); its base URL, headers and
   * authentication are used and `url` is just the path after the base URL. */
  connection: string | null;
  url: string;
  method: "GET" | "POST";
  headers: Record<string, string> | null;
  body: Record<string, unknown> | null;
  auth: DataSourceAuth | null;
  /** JSONPath to the list of choices in the response; null = the response is the list. */
  items_path: string | null;
  /** Where each item's value is: a key (`code`), a path (`name.en`) or a template (`${code}-${branch}`).
   * Named `value_field` for configs saved before JSONPath. */
  value_field: string;
  label_field: string | null;
}

export interface ReportParameter {
  name: string;
  label: string | null;
  type: ParameterType;
  /** Only a free-text parameter (no options/options_source) can be
   * false -- a choice list stays mandatory regardless, since a grant
   * narrowing it could otherwise be bypassed by skipping it entirely. */
  required: boolean;
  /** Free-text/number/date/time only: what the run form starts with -- a
   * literal, or `now()` (date, datetime, time) for the moment it's opened. */
  default_value: string | null;
  /** null = either free text (see `type`) or options_source-driven */
  options: ParameterOption[] | null;
  options_source: OptionsSource | null;
}

export type DataSourceType = "static" | "rest" | "jdbc";

/** Where the server gets a report's data when it's run, by `type`: fixed sample
 * data, a REST API, or a read-only SQL query against a database connection.
 * See api/app/models/reports.py's DataSource -- fields that don't belong to the
 * chosen type come back null/empty. */
export interface DataSource {
  type: DataSourceType;
  /** Name of a connection (Admin > Connections). rest: `url` is then just the path. jdbc: the database to query. */
  connection: string | null;
  url: string;
  method: "GET" | "POST";
  headers: Record<string, string> | null;
  body_template: Record<string, unknown> | string | null;
  auth: DataSourceAuth | null;
  /** jdbc: one SELECT; `:name` binds a filter parameter's value. */
  query?: string | null;
  /** jdbc: the key the rows are returned under for the template to loop over (default `rows`). */
  root_key?: string | null;
  /** jdbc: bind each filter as its declared type (a built-in driver gets a real date / number). */
  typed_binding?: boolean;
  /** static: the JSON object the template is rendered with. */
  static_data?: Record<string, unknown> | null;
}

export interface DataConfig {
  parameters: ReportParameter[];
  data_source: DataSource | null;
}

/** POST /reports/{id}/data-config/preview-options -- the choices a source would give. */
export interface OptionsPreview {
  total: number;
  options: ParameterOption[];
}

// --- Connections: a named base URL + headers + authentication (api/app/connections.py) ---

export interface ConnectionConfig {
  base_url: string;
  headers: Record<string, string> | null;
  auth: DataSourceAuth | null;
}

export type SslMode = "disable" | "require" | "verify-ca" | "verify-full";

/** A database connection (kind "jdbc"; api/app/jdbc.py). The password is never in
 * here: `auth` names a Secret (or an environment variable) that holds it. */
export interface JdbcConnectionConfig {
  engine: string;
  host: string;
  port: number;
  database: string;
  service_type: "service_name" | "sid" | null;
  ssl_mode: SslMode;
  /** An uploaded JDBC driver; null = the engine's built-in one. */
  driver_id: string | null;
  /** A complete JDBC URL used instead of one built from the fields; uploaded drivers only. */
  jdbc_url: string | null;
  auth: DataSourceAuth;
}

export interface JdbcEngine {
  id: string;
  label: string;
  default_port: number;
  driver_class: string;
  /** Runs without an uploaded driver. */
  built_in: boolean;
  /** Where the vendor publishes its JDBC driver. */
  driver_url: string;
  ssl_note: string;
  database_label: string;
  ssl_modes: SslMode[];
}

export interface JdbcDriver {
  id: string;
  org_id: string;
  name: string;
  engine: string;
  driver_class: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  used_by: string[];
  created_at: string;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
  elapsed_ms: number | null;
}

/** What a report author needs to pick a connection -- no header values. */
export interface ConnectionSummary {
  id: string;
  org_id: string;
  name: string;
  kind: string;
  description: string | null;
  /** A REST connection's base URL, or a database connection's JDBC URL (neither holds a credential). */
  base_url: string;
  /** Database connections only. */
  engine: string | null;
  auth_type: "none" | "bearer" | "basic";
  /** Where the credential comes from: a Secret managed in the portal, or an environment variable on the server. */
  credential: "none" | "secret" | "env";
  /** The Secret's name, when `credential` is "secret". */
  secret_name: string | null;
  header_names: string[];
  report_count: number;
  updated_at: string;
}

export interface ConnectionReportRef {
  report_id: string;
  name: string;
  code: string | null;
}

export interface Connection {
  id: string;
  org_id: string;
  name: string;
  kind: string;
  description: string | null;
  config: ConnectionConfig | JdbcConnectionConfig;
  reports: ConnectionReportRef[];
  created_at: string;
  updated_at: string;
}

// --- Secrets (Admin > Secrets) -- named credentials a data source's or a
// connection's own auth can refer to instead of an environment variable. The
// value is never part of any of these shapes; see api/app/secret_store.py.

export interface SecretRef {
  kind: "report" | "connection";
  name: string;
  report_id: string | null;
  code: string | null;
  connection_id: string | null;
}

export interface SecretSummary {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  used_by_count: number;
  created_at: string;
  updated_at: string;
}

export interface Secret extends SecretSummary {
  used_by: SecretRef[];
}

/** What GET /reports/{id}/run-form returns: `options` are already narrowed
 * to what the caller's grants allow -- a value they may not use is never sent. */
export interface RunFormParameter {
  name: string;
  label: string | null;
  /** Which input to render when `options` is null; ignored otherwise. */
  type: ParameterType;
  /** A choice-list parameter (options isn't null) is always true here. */
  required: boolean;
  /** As configured: a literal, or `now()` -- read from the viewer's own clock. */
  default_value: string | null;
  options: ParameterOption[] | null;
}

export interface RunForm {
  report_id: string;
  name: string;
  description: string | null;
  template_ext: TemplateExt;
  access_level: "render" | "manage";
  formats: RenderFormat[];
  parameters: RunFormParameter[];
}

export interface ReportSchema {
  fields: string[];
  engine: "docxtpl" | "regex-scan" | "jinja2-ast";
  note: string;
}

export interface TemplateSyntaxIssue {
  message: string;
  line: number | null;
  column: number | null;
}

// POST /reports/parse-template's response — a pre-flight look at an
// uploaded html template before RegisterDialog commits to registering it:
// does it parse, what fields does it expect, and which resource() names
// need mapping. See api/app/html_template.py.
export interface ParsedTemplate {
  fields: string[];
  resources: string[];
  errors: TemplateSyntaxIssue[];
}

/** Why a report failed to render (api/app/render_errors.py). Everyone gets `stage` and `reference`;
 * only someone who manages the report also gets the engine's own message, the template text around the
 * failing line, a hint and the technical traceback. */
export interface RenderErrorInfo {
  stage: "template" | "render";
  /** Matches the line in the server log next to the full traceback. */
  reference: string;
  type?: string;
  message?: string;
  line?: number | null;
  hint?: string | null;
  context?: { line: number; text: string; hit: boolean }[] | null;
  tag_counts?: { for: number; endfor: number; if: number; endif: number } | null;
  /** Paragraphs where a {%p %}/{%tr %} tag shares its paragraph with other text or tags -- those tags must be alone. */
  shared_tags?: { where: string; paragraph: number; text: string }[] | null;
  traceback?: string;
}

export interface ApiErrorBody {
  detail?: string;
  render_error?: RenderErrorInfo;
}

// --- Auth / whoami -----------------------------------------------------

export interface AuthInfo {
  authenticated: boolean;
  username: string;
  orgId: string | null;
  isSuperuser: boolean;
  permissions: string[];
  /** The account must choose a new password before anything else works --
   * App.tsx shows ForcePasswordChange instead of the console. */
  mustChangePassword: boolean;
  /** The built-in admin from .env while no administrator account exists: its password was generated at install
   * time, and ForcePasswordChange runs the first-run setup (api.setupAdmin) instead of a password change. */
  setupRequired: boolean;
}

// --- Organizations, users, roles, permissions, grants -------------------
// Mirrors api/app/models.py 1:1 (see that file for the authoritative shape).

export interface Organization {
  id: string;
  name: string;
  parent_org_id: string | null;
  is_active: boolean;
  created_at: string;
}

export type AuthSource = "local" | "ldap";

export interface User {
  id: string;
  org_id: string;
  username: string;
  email: string | null;
  display_name: string | null;
  auth_source: AuthSource;
  is_active: boolean;
  is_locked: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
  notify_new_signin: boolean;
  avatar_content_type: string | null;
  totp_enabled: boolean;
  /** Set on admin-created accounts and by an admin password reset; cleared when the user picks their own. */
  must_change_password: boolean;
}

export interface PasswordResetResult {
  user: User;
  /** Only present when the server generated the password -- shown once, never retrievable again. */
  generated_password: string | null;
}

// --- Two-factor authentication (Settings > Access) -- see
// api/app/totp.py's module docstring: the code is asked for at sign-in, and an
// account that has it can't authenticate with a password alone.

export interface TotpEnrollment {
  secret: string;
  otpauth_url: string;
  qr_code_data_url: string;
}

// --- Sign-in history / auth log (see api/app/routers/users.py's
// /me/sessions, /me/auth-log, /me/notifications, api/app/db/auth_events.py) --
// A row here is a record of a sign-in attempt, or an (ip, browser, device)
// fingerprint that signed in successfully within a recency window -- history,
// not a live session (those are UserSession above). The same shape backs the
// sign-in activity log and the Notifications bell's new-device alerts.

export type DeviceType = "desktop" | "mobile" | "tablet";

/** One live sign-in session of the signed-in account (GET /auth/sessions). */
export interface UserSession {
  id: string;
  /** The session this request belongs to. */
  current: boolean;
  browser: string;
  os: string;
  device_type: DeviceType;
  ip_address: string | null;
  /** Signed in with "keep me signed in". */
  remember: boolean;
  created_at: string;
  last_used_at: string;
  expires_at: string;
}

export interface AuthEvent {
  id: string;
  success: boolean;
  username: string;
  ip_address: string | null;
  browser: string;
  os: string;
  device_type: DeviceType;
  is_current: boolean;
  is_new_device: boolean;
  created_at: string;
  last_seen_at: string;
  /** The session this sign-in opened (portal sign-ins only), and whether it is still signed in. */
  session_id?: string | null;
  session_active?: boolean;
}

export interface EffectivePermissions {
  user_id: string;
  permissions: string[];
}

export interface Role {
  id: string;
  org_id: string | null;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
}

export interface Permission {
  code: string;
  description: string;
}

export interface ApiClientReportRef {
  report_id: string;
  name: string;
  code: string | null;
}

/** A machine identity (client id + secret) that may run the reports it was granted. The secret is never part of this. */
export interface ApiClient {
  id: string;
  org_id: string;
  client_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  secret_prefix: string;
  created_at: string;
  secret_rotated_at: string | null;
  last_used_at: string | null;
  reports: ApiClientReportRef[];
}

export interface ApiClientWithSecret {
  client: ApiClient;
  secret: string;
}

// --- protected terms --------------------------------------------------------
// Khmer word-breaking never splits a "protected term" (brand names, proper
// nouns); `exclude_terms` are the reverse -- terms handed back to the
// default breaker. See api/app/models/protected_terms.py.

/** A named, reusable, organization-scoped list a report selects by id. */
export interface ProtectedTermSet {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  terms: string[];
  exclude_terms: string[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/** What create/update send (the org id travels separately on create). */
export interface ProtectedTermSetInput {
  name: string;
  description: string | null;
  terms: string[];
  exclude_terms: string[];
}

/** The deployment-wide list as last synced from the API's mounted config
 * files -- a read-only mirror, edited on the server, never here. */
export interface DeploymentTerms {
  id: string;
  version: number;
  terms: string[];
  exclude_terms: string[];
  source_paths: Record<string, string | null>;
  synced_at: string;
}

/** One report's own layer: the sets it selects (live references, not
 * copies) plus terms of its own. */
export interface ProtectedTermsConfig {
  set_ids: string[];
  terms: string[];
  exclude_terms: string[];
}

/** Populated depending on which of the four grant tables this came from —
 * exactly one of (role_id) / (permission_code) / (report_id + permission_level)
 * / (folder_id + permission_level) is set. See api/app/routers/grants.py. */
export interface Grant {
  id: string;
  granted_at: string;
  granted_by: string | null;
  expires_at: string | null;
  is_active: boolean;
  user_id?: string | null;
  role_id?: string | null;
  permission_code?: string | null;
  subject_type?: "user" | "role" | null;
  subject_id?: string | null;
  report_id?: string | null;
  folder_id?: string | null;
  permission_level?: "view" | "render" | "manage" | null;
  /** Report grants only: e.g. { p_branch: ["BR01"] } narrows this grant's holders to those values. */
  parameter_limits?: Record<string, string[]> | null;
}

export type AccessGrantType = "report" | "folder";

/** One row of GET /grants/access-review -- the aggregate view behind the
 * admin Access Review page. Names are already resolved server-side. */
export interface AccessReviewGrant {
  id: string;
  grant_type: AccessGrantType;
  subject_type: "user" | "role";
  subject_id: string;
  subject_name: string;
  resource_id: string;
  resource_name: string;
  org_id: string;
  permission_level: "view" | "render" | "manage";
  granted_at: string;
  granted_by: string | null;
  granted_by_name: string | null;
  expires_at: string | null;
  parameter_limits: Record<string, string[]> | null;
}

// --- Resources: folders + images (see api/app/routers/folders.py, images.py) --

export interface Folder {
  id: string;
  org_id: string;
  parent_folder_id: string | null;
  name: string;
  description: string | null;
  /** From the folder list: whether the viewer may file reports into it. */
  can_manage?: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImageResource {
  id: string;
  org_id: string;
  folder_id: string | null;
  name: string;
  content_type: string;
  file_ext: string;
  width_px: number;
  height_px: number;
  size_bytes: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

// The CSS counterpart to ImageResource — see api/app/stylesheet_store.py.
export interface StylesheetResource {
  id: string;
  org_id: string;
  folder_id: string | null;
  name: string;
  content_type: string;
  size_bytes: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

// --- AD/LDAP login (see api/app/routers/ldap.py, api/app/auth_ldap.py) --

export type LdapBindMethod = "direct_bind" | "search_bind" | "upn_bind";

export interface LdapConfig {
  id: string;
  org_id: string | null;
  server_uri: string;
  bind_method: LdapBindMethod;
  base_dn: string;
  direct_bind_dn_template: string | null;
  service_bind_dn: string | null;
  service_bind_password_env: string | null;
  user_search_filter: string | null;
  upn_domain: string | null;
  group_search_base: string | null;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface LdapGroupMapping {
  id: string;
  ldap_config_id: string;
  group_dn: string;
  role_id: string;
}

export interface LdapTestResult {
  success: boolean;
  dn: string | null;
  groups: string[];
  detail: string | null;
}

// --- Job scheduling (see api/app/routers/jobs.py, api/app/job_executors.py) --

export type JobType = "render_report" | "rest_call" | "soap_call" | "file_output";
export type TriggerType = "cron" | "interval" | "one_off";
export type JobRunStatus = "queued" | "running" | "success" | "failed" | "retrying";

export interface Job {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  job_type: JobType;
  config: Record<string, unknown>;
  trigger_type: TriggerType;
  cron_expression: string | null;
  interval_seconds: number | null;
  run_at: string | null;
  start_date: string | null;
  end_date: string | null;
  is_enabled: boolean;
  max_retries: number;
  retry_backoff_seconds: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobRun {
  id: string;
  job_id: string;
  triggered_by: "schedule" | "manual" | "api";
  celery_task_id: string | null;
  status: JobRunStatus;
  attempt_number: number;
  started_at: string | null;
  finished_at: string | null;
  result_summary: string | null;
  triggered_by_user_id: string | null;
  created_at: string;
}

// --- System monitoring ---------------------------------------------------

export interface DiskUsage {
  mountpoint: string;
  total_bytes: number;
  used_bytes: number;
  percent: number;
}

export interface SystemMetrics {
  cpu_percent: number;
  cpu_percent_per_core: number[];
  cpu_core_count: number;
  cpu_thread_count: number;
  memory_total_bytes: number;
  memory_used_bytes: number;
  memory_percent: number;
  disks: DiskUsage[];
  process_thread_count: number;
  process_count: number;
  uptime_seconds: number;
}

// --- Admin dashboard -------------------------------------------------------
// See api/app/models/analytics.py + specs/admin_dashboard_design.md.

export interface ReportRenderStats {
  report_id: string;
  name: string;
  render_count: number;
  error_count: number;
  avg_duration_ms: number | null;
  p95_duration_ms: number | null;
  last_rendered_at: string | null;
}

export interface JobsSummary {
  total_jobs: number;
  enabled_jobs: number;
  runs_today: number;
  succeeded_today: number;
  failed_today: number;
  running_now: number;
}

export interface SecurityActivityItem {
  kind: "login_failed" | "access_denied";
  username: string | null;
  ip_address: string | null;
  detail: string;
  created_at: string;
  unusual: boolean;
}

// --- Change audit trail + template file history (api/app/audit.py, routers/audit.py) ---

/** One field-level change on an audit event. Exactly one shape applies:
 * before/after (a value changed), added/removed (a list of plain values --
 * terms, permission codes -- changed), `redacted` (a secret changed; the
 * server never sends its value), or `opaque` (a bulky value changed and
 * isn't kept). `modified` appears on a list of named items (a report's filter
 * parameters). */
export interface AuditChange {
  field: string;
  before?: unknown;
  after?: unknown;
  added?: unknown[];
  removed?: unknown[];
  modified?: unknown[];
  added_count?: number;
  removed_count?: number;
  redacted?: boolean;
  opaque?: boolean;
}

export interface AuditEvent {
  id: string;
  created_at: string;
  actor_username: string;
  actor_user_id: string | null;
  ip_address: string | null;
  org_id: string | null;
  /** "<entity_type>.<verb>", e.g. "report.file_replace". */
  action: string;
  entity_type: string;
  entity_id: string;
  entity_label: string | null;
  summary: string;
  changes: AuditChange[] | null;
  details: Record<string, unknown> | null;
}

export interface AuditPage {
  items: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditQuery {
  entityType?: string;
  entityId?: string;
  action?: string;
  actor?: string;
  q?: string;
  since?: string;
  until?: string;
  orgId?: string;
  limit?: number;
  offset?: number;
}

/** One version of a template's file. */
export interface ReportVersion {
  version: number;
  version_label: string | null;
  template_ext: TemplateExt;
  size_bytes: number;
  size_delta: number | null;
  sha256: string;
  original_filename: string | null;
  note: string | null;
  created_by: string | null;
  created_at: string;
  backfilled: boolean;
  fields: string[] | null;
  fields_added: string[] | null;
  fields_removed: string[] | null;
  identical_to_previous: boolean;
  available: boolean;
}

export type ChangelogEntry =
  | { kind: "version"; at: string; version: ReportVersion; upload_event: AuditEvent | null }
  | { kind: "event"; at: string; event: AuditEvent };

export interface ReportChangelog {
  report_id: string;
  current_version: number;
  /** Oldest version whose file is still held; anything below was overwritten before history was kept. */
  first_retained_version: number | null;
  original_available: boolean;
  entries: ChangelogEntry[];
}

/** How a version is shown: the uploader's label ("v1.0.1") when it has one, else its sequence number ("v3"). */
export const versionName = (version: number, label?: string | null): string => `v${label || version}`;

/** The label of `version` as recorded in the change log, if any. */
export const labelInChangelog = (changelog: ReportChangelog | null, version: number): string | null => {
  const e = changelog?.entries.find((x) => x.kind === "version" && x.version.version === version);
  return e && e.kind === "version" ? e.version.version_label : null;
};

/** GET /me/dashboard: the signed-in person's own report activity (api/app/routers/me.py). */
export interface MyRun {
  report_id: string;
  name: string | null;
  at: string;
  via: string | null;
  format: string | null;
  parameters_selected: number | null;
  ok: boolean;
  reason: string | null;
}

export interface MyDashboard {
  since: string;
  runs_7d: number;
  runs_30d: number;
  failed_30d: number;
  last_run_at: string | null;
  recent: MyRun[];
  top_reports: { report_id: string; name: string | null; runs: number }[];
  /** The last 30 UTC days, oldest first, zero-filled. */
  daily: { date: string; runs: number; failed: number }[];
}

// --- Fonts (Resources > Fonts) -- see api/app/routers/fonts.py ---------------

/** A font added at runtime: installed for the whole server, drawn by every rendering path. */
export interface FontResource {
  id: string;
  family: string;
  subfamily: string;
  full_name: string;
  postscript_name: string;
  version: string;
  weight: number;
  italic: boolean;
  glyph_count: number;
  khmer_coverage: number;
  latin_coverage: number;
  has_layout_tables: boolean;
  copyright: string;
  license: string;
  license_url: string;
  embedding: string;
  note: string;
  filename: string;
  file_ext: "ttf" | "otf";
  sha256: string;
  size_bytes: number;
  created_at: string;
  used_by: string[];
  warnings: string[];
  shadows_installed: boolean;
}

export interface InstalledFont {
  family: string;
  source: "uploaded" | "system";
}

export interface FontBlock {
  name: string;
  start: number;
  end: number;
  present: number[];
  missing: number[];
}

/** A font a template names, and whether the server has it. */
export interface TemplateFont {
  name: string;
  status: "uploaded" | "installed" | "substituted" | "missing";
  resolved_to: string | null;
}

// --- The New report wizard -- see api/app/routers/report_wizard.py -----------

export type DataFieldKind = "text" | "number" | "date" | "boolean" | "list" | "object" | "empty";

/** One path a template can use in a report's data: `invoices[].total_usd` (`[]` = the items of a list). */
export interface DataField {
  path: string;
  kind: DataFieldKind;
  example: string | null;
  /** list: how many items the run returned. */
  count: number | null;
  depth: number;
}

/** POST /reports/data-preview -- a data source run once, unsaved. */
export interface DataPreview {
  data: Record<string, unknown>;
  fields: DataField[];
  /** The filters the source uses: the ones sent plus any it found (`:month`, `{{ month }}`). */
  parameters: ReportParameter[];
  elapsed_ms: number;
  truncated: boolean;
  /** Filters still without a test value -- nothing was fetched; ask for them and run again. */
  missing: string[];
}

/** GET /reports/{id}/template-check -- the template compared with the report's sample data. */
export interface TemplateCheck {
  checked: boolean;
  reason: string | null;
  matched: string[];
  unknown: { placeholder: string; suggestion: string | null }[];
  unused: string[];
  fields: DataField[];
}
