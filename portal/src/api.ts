// Typed fetch client for the api service's public JSON endpoints. Ports
// the auth-header/401-handling behavior that used to live in the
// vanilla-JS portal's app.js 1:1, plus the newer schema/batch/sample
// endpoints — see api/app/routers/reports.py.
import type {
  Dashboard,
  DashboardSummary,
  DashboardTile,
  AnalysisChart,
  AnalysisView,
  AnalyzeDataset,
  AnalyzeForm,
  PivotLayout,
  PivotResult,
  ApprovedRoutine,
  DiscoveredRoutines,
  ApiClient,
  ApiClientWithSecret,
  AccessReviewGrant,
  AccessibleReport,
  ApiErrorBody,
  AuditPage,
  AuditQuery,
  AuthEvent,
  AuthInfo,
  BatchLimits,
  MyDashboard,
  MyRun,
  Connection,
  ConnectionConfig,
  ConnectionSummary,
  ConnectionTestResult,
  DataConfig,
  DataPreview,
  DataSource,
  DeploymentTerms,
  EffectivePermissions,
  UserOverview,
  Folder,
  ImportChoice,
  ImportPlan,
  ImportSummary,
  ProjectContents,
  ResourceUsage,
  FontBlock,
  FontResource,
  InstalledFont,
  TemplateFont,
  TemplateCheck,
  ReportParameter,
  ReportShortcut,
  Grant,
  ImageResource,
  Job,
  JobDelivery,
  Dataset,
  DatasetAccess,
  DatasetAccessMode,
  DatasetGrant,
  DatasetField,
  DatasetMeasure,
  DatasetPreview,
  DatasetSummary,
  DatasetWrite,
  JobRun,
  SchedulePreview,
  JobsSummary,
  JdbcConnectionConfig,
  SmtpConnectionConfig,
  JdbcDriver,
  JdbcEngine,
  JobType,
  LdapBindMethod,
  LdapConfig,
  LdapGroupMapping,
  LdapTestResult,
  OptionsPreview,
  OptionsSource,
  Organization,
  ParsedTemplate,
  PasswordResetResult,
  Permission,
  ProtectedTermSet,
  ProtectedTermSetInput,
  ProtectedTermsConfig,
  RenderErrorInfo,
  RenderFormat,
  RenderResult,
  ReportChangelog,
  ReportVersion,
  ReportMeta,
  ReportRenderStats,
  ReportSchema,
  ResourceBinding,
  Role,
  RunForm,
  Secret,
  SecretSummary,
  SecurityActivityItem,
  StylesheetResource,
  SystemMetrics,
  TemplateExt,
  TotpEnrollment,
  TriggerType,
  User,
  UserSession,
} from "./types";
import { FORMATS_BY_EXT } from "./types";
import { recordFailure, type FailureInfo } from "./errorLog";

declare global {
  interface Window {
    PORTAL_API_BASE_URL?: string;
  }
}

const API = (window.PORTAL_API_BASE_URL || "") + "/api/v1";

/** What a status means in plain words, for an answer that carries no message of its own (a proxy's HTML error
 * page, an empty body). Keeps a failed request readable without opening the browser's network tab. */
export function statusMessage(status: number): string {
  if (status === 0) return "Can't reach the server. Check your connection, or the server may be restarting — try again in a moment.";
  if (status === 400) return "The request wasn't accepted — check the values and try again.";
  if (status === 401) return "Your session has ended. Sign in again.";
  if (status === 403) return "You don't have permission to do this.";
  if (status === 404) return "It no longer exists — it may have been deleted or moved. Reload the page.";
  if (status === 408) return "The server took too long to answer. Try again.";
  if (status === 409) return "It conflicts with something that already exists or was changed meanwhile. Reload and try again.";
  if (status === 413) return "The file or request is too large for the server to accept.";
  if (status === 415) return "That file type isn't supported here.";
  if (status === 422) return "Some of the values aren't valid.";
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  if (status === 502 || status === 503 || status === 504)
    return "The server isn't responding right now (it may be restarting or overloaded). Try again in a minute; if it persists, contact your administrator.";
  if (status >= 500) return "The server hit an unexpected error. Try again; if it keeps happening, contact your administrator.";
  return "The request failed.";
}

/** The message for a failed request: the API's own `detail` when it sent one -- a string, or FastAPI's list of
 * validation problems -- else `fallback` plus what the status means. */
export function errorDetail(status: number, body: ApiErrorBody | null | undefined, fallback = "Request failed"): string {
  const detail = body?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((d) => {
        const field = (d.loc ?? []).filter((part) => part !== "body" && part !== "query" && part !== "path").join(".");
        return field ? `${field}: ${d.msg ?? "invalid"}` : (d.msg ?? "invalid value");
      })
      .join("; ");
  }
  return `${fallback} (HTTP ${status}): ${statusMessage(status)}`;
}

export class ApiError extends Error {
  status: number;
  /** Present when a report failed to render -- see RenderErrorInfo. */
  renderError?: RenderErrorInfo;
  /** What a technician needs (request, status, request id, time) -- see errorLog.ts. Absent for an error the portal
   * made up itself (a form check). */
  info?: FailureInfo;
  constructor(status: number, message: string, renderError?: RenderErrorInfo, info?: FailureInfo) {
    super(message);
    this.status = status;
    this.renderError = renderError;
    this.info = info;
  }
}

// The method and path each apiFetch() answer was for, so the error built from it later can say what was called.
const requestOf = new WeakMap<Response, { method: string; path: string }>();

function apiPath(url: string): string {
  try {
    const u = new URL(url, location.href);
    return u.pathname + u.search;
  } catch {
    return url;
  }
}

/** The ApiError for a failed answer, with its technical details recorded (errorLog.ts). */
function failure(resp: Response, message: string, renderError?: RenderErrorInfo): ApiError {
  const sent = requestOf.get(resp);
  const info = recordFailure({
    kind: "http",
    method: sent?.method ?? "?",
    path: sent?.path ?? apiPath(resp.url),
    status: resp.status,
    requestId: resp.headers.get("X-Request-ID"),
    message,
  });
  return new ApiError(resp.status, message, renderError, info);
}

let unauthorizedHandler: (() => void) | null = null;
let passwordChangeHandler: (() => void) | null = null;

// `detail` of the 403 the API answers with for an account that still has to
// change its password -- matches api/app/auth.py's PASSWORD_CHANGE_REQUIRED_DETAIL.
export const PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED";

/** Called once, by the top-level app, so this module can react to the end of a
 * session (the refresh cookie is gone, expired or was revoked: drop back to the login
 * view) without importing React or holding UI state itself. */
export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler;
}

/** Same idea for the "you must change your password first" 403 -- how the
 * app learns of it mid-session (an admin flagged the account while its owner
 * was signed in), as opposed to at sign-in, where the login answer says so. */
export function onPasswordChangeRequired(handler: () => void): void {
  passwordChangeHandler = handler;
}

// --- the session: a short-lived access token in memory, a refresh cookie the browser holds -------------
//
// Signing in (api.login) returns an access token (a JWT) that lives only in this variable: not in
// localStorage or sessionStorage, so a script injected into the page can't read it back later, and a
// reload simply asks the server for a new one with the refresh cookie (api.restoreSession). That cookie
// is HttpOnly -- JavaScript can't see it at all -- and is sent only to /auth/*, never to the other endpoints.
// The access token expires in minutes, so it's renewed shortly before (and, as a fallback, whenever a call
// answers 401). Each renewal rotates the cookie; see api/app/auth_tokens.py.

let accessToken: string | null = null;
let refreshTimer: number | undefined;
let refreshing: Promise<AuthInfo | null> | null = null;

// The refresh and logout routes insist on this header: only our own script sets it, so another site's
// page can't make the browser call them with the cookie (it would need a CORS preflight to be allowed).
const CLIENT_HEADER = { "X-Aksor-Client": "portal" };

// How long the sign-in form waits for an answer before giving up and re-enabling its button.
const LOGIN_TIMEOUT_MS = 20_000;

// Signing out in one tab ends the session for all of them (the cookie is shared); tell the others at once.
const authChannel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("aksor-auth") : null;
authChannel?.addEventListener("message", (event) => {
  if (event.data === "signed-out") {
    dropSession();
    unauthorizedHandler?.();
  }
});

function dropSession(): void {
  accessToken = null;
  window.clearTimeout(refreshTimer);
}

function renewInBackground(): void {
  refreshSession().then(
    (info) => {
      if (!info) unauthorizedHandler?.();
    },
    // The API couldn't be reached -- not the same as being signed out. Try again shortly; the access token is still good for a while.
    () => {
      refreshTimer = window.setTimeout(renewInBackground, 30_000);
    }
  );
}

function adopt(body: TokenResponse): AuthInfo {
  accessToken = body.access_token;
  window.clearTimeout(refreshTimer);
  // Renew with a fifth of the lifetime left (but never in a tight loop), so a call rarely meets an expired token.
  refreshTimer = window.setTimeout(renewInBackground, Math.max(body.expires_in * 0.8, 10) * 1000);
  return toAuthInfo(body.user);
}

/** Trade the refresh cookie for a new access token. One at a time: concurrent callers share the answer, and
 * across tabs a lock makes them take turns -- so the second tab refreshes with the cookie the first one just
 * rotated instead of presenting the old one. Resolves null when there's no session (any more); *rejects* when the
 * API can't be reached, which is not the same thing. */
export function refreshSession(): Promise<AuthInfo | null> {
  if (refreshing) return refreshing;
  const run = async (): Promise<AuthInfo | null> => {
    const resp = await fetch(API + "/auth/refresh", { method: "POST", credentials: "include", headers: CLIENT_HEADER });
    if (!resp.ok) {
      dropSession();
      return null;
    }
    return adopt(await resp.json());
  };
  const locks = (navigator as unknown as { locks?: { request: (name: string, callback: () => Promise<AuthInfo | null>) => Promise<AuthInfo | null> } }).locks;
  const pending = (locks ? locks.request("aksor-refresh", run) : run()).finally(() => {
    refreshing = null;
  });
  refreshing = pending;
  return pending;
}

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const send = () => {
    const headers = new Headers(options.headers || {});
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    // No answer at all (offline, DNS, the API container down, CORS) surfaces as a bare "TypeError: Failed to
    // fetch"; make it an ApiError with a sentence a person can act on. Aborts stay as they are.
    const method = (options.method || "GET").toUpperCase();
    return fetch(API + path, { ...options, headers }).then(
      (resp) => {
        requestOf.set(resp, { method, path: apiPath(resp.url || API + path) });
        return resp;
      },
      (err: unknown) => {
        if (err instanceof TypeError) {
          const message = statusMessage(0);
          const info = recordFailure({ kind: "network", method, path: apiPath(API + path), status: 0, requestId: null, message });
          throw new ApiError(0, message, undefined, info);
        }
        throw err;
      }
    );
  };
  let resp = await send();
  if (resp.status === 401) {
    // The access token expired (or its session was revoked): renew once and retry. Still 401 -> signed out.
    let renewed: AuthInfo | null;
    try {
      renewed = await refreshSession();
    } catch {
      return resp; // the API went away between the two calls -- hand back the 401, don't sign anyone out for it
    }
    if (renewed) resp = await send();
    if (!renewed || resp.status === 401) {
      dropSession();
      unauthorizedHandler?.();
    }
  } else if (resp.status === 403 && passwordChangeHandler) {
    const body: ApiErrorBody = await resp.clone().json().catch(() => ({}));
    if (body.detail === PASSWORD_CHANGE_REQUIRED) passwordChangeHandler();
  }
  return resp;
}

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body: ApiErrorBody = await resp.json().catch(() => ({}));
    throw failure(resp, errorDetail(resp.status, body, "Request failed"));
  }
  return resp.json() as Promise<T>;
}

function filenameFromDisposition(resp: Response, fallback: string): string {
  const header = resp.headers.get("Content-Disposition") || "";
  const match = /filename="([^"]+)"/.exec(header);
  return match ? match[1] : fallback;
}

/** Package a render/run response: the file, its name, and how many files the
 * report has (X-Report-Parts -- see api/app/report_split.py). When a split
 * report comes back whole the body is a ZIP, so a missing file name falls
 * back to `.zip`, not the requested format. */
async function renderResult(resp: Response, fallbackName: string, format: RenderFormat): Promise<RenderResult> {
  const isZip = (resp.headers.get("Content-Type") || "").includes("zip");
  const part = Number(resp.headers.get("X-Report-Part")) || null;
  return {
    blob: await resp.blob(),
    filename: filenameFromDisposition(resp, `${fallbackName}.${isZip ? "zip" : format}`),
    parts: Number(resp.headers.get("X-Report-Parts")) || 1,
    part,
    report: describedReport(resp),
  };
}

const embedRunsInFlight = new Map<string, Promise<RenderResult>>();

/** What authorizes an embedded run: an API client's id + secret (an admin granted it this report). */
export interface EmbedAuth {
  clientId?: string;
  clientSecret?: string;
}

async function requestEmbedRun(
  ref: string,
  parameters: Record<string, string>,
  auth: EmbedAuth,
  format: RenderFormat,
  fallbackName: string,
  part?: number
): Promise<RenderResult> {
  const resp = await fetch(`${API}/reports/${ref}/embed-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      parameters,
      ...(auth.clientId && auth.clientSecret ? { client_id: auth.clientId, client_secret: auth.clientSecret } : {}),
      format,
      ...(part ? { part } : {}),
    }),
  });
  if (!resp.ok) {
    const body: ApiErrorBody = await resp.json().catch(() => ({}));
    throw failure(resp, errorDetail(resp.status, body, "Run failed"));
  }
  return renderResult(resp, fallbackName, format);
}

/** The `X-Report-Name` / `X-Report-Ext` headers the parameter-driven run routes add, if both
 * are present and make sense (the name is percent-encoded -- it is often Khmer). */
function describedReport(resp: Response): RenderResult["report"] {
  const name = resp.headers.get("X-Report-Name");
  const ext = resp.headers.get("X-Report-Ext");
  if (!name || !ext || !(ext in FORMATS_BY_EXT)) return undefined;
  try {
    return { name: decodeURIComponent(name), ext: ext as TemplateExt };
  } catch {
    return undefined;
  }
}

// --- Small typed-JSON helpers -------------------------------------------
// Every admin endpoint below is one of: "GET it", "POST/PATCH/PUT it with
// a JSON body", or "DELETE it" — these three collapse what used to be a
// repeated `apiFetch(...).then((r) => asJson<T>(r))` (plus manual
// Content-Type headers and manual error handling on every DELETE) at
// every one of the ~35 call sites below.

function getJSON<T>(path: string): Promise<T> {
  return apiFetch(path).then((r) => asJson<T>(r));
}

function sendJSON<T>(path: string, method: "POST" | "PATCH" | "PUT", body: unknown): Promise<T> {
  return apiFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => asJson<T>(r));
}

/** DELETE with no response body. `ignoreStatuses` lets a caller treat an
 * already-gone resource (404) as success rather than an error — only
 * `deleteReport` needs that; every other delete/revoke call below wants
 * the default (any non-2xx throws). */
async function del(path: string, fallbackMessage: string, ignoreStatuses: number[] = []): Promise<void> {
  const resp = await apiFetch(path, { method: "DELETE" });
  if (!resp.ok && !ignoreStatuses.includes(resp.status)) {
    const body: ApiErrorBody = await resp.json().catch(() => ({}));
    throw failure(resp, errorDetail(resp.status, body, fallbackMessage));
  }
}

function qs(params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter((e): e is [string, string] => e[1] !== undefined);
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
}

interface AuthVerifyResponse {
  authenticated: boolean;
  username: string;
  org_id: string | null;
  is_superuser: boolean;
  permissions: string[];
  must_change_password?: boolean;
  setup_required?: boolean;
}

function toAuthInfo(body: AuthVerifyResponse): AuthInfo {
  return {
    authenticated: body.authenticated,
    username: body.username,
    orgId: body.org_id,
    isSuperuser: body.is_superuser,
    permissions: body.permissions,
    mustChangePassword: body.must_change_password ?? false,
    setupRequired: body.setup_required ?? false,
  };
}

// Sentinel `ApiError.message` returned by login() when the account has
// 2FA enabled and no (or the wrong) code was given yet -- matches
// api/app/routers/auth.py's TOTP_REQUIRED_DETAIL. Login.tsx checks for
// this specific string to know "show the code step" rather than "the
// password was wrong."
export const TOTP_REQUIRED = "2FA_REQUIRED";

interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthVerifyResponse;
}

/** Brave sends Chrome's User-Agent unchanged, so the server would list it as Chrome. Over https (or localhost)
 * it says so in the Sec-CH-UA client hint; elsewhere -- plain http on a LAN address -- the page can still tell, and
 * passes that along at sign-in so Settings > Active Sessions and new-sign-in alerts name the right browser. */
function browserHintHeaders(): Record<string, string> {
  return "brave" in navigator ? { "X-Aksor-Browser": "Brave" } : {};
}

export const api = {
  /** Sign in: password (and the 2FA code, on the second step for an account that has it). The access token
   * stays in memory; the refresh cookie is set by the server. `remember` keeps this browser signed in for
   * weeks instead of a working day. */
  async login(username: string, password: string, options: { totpCode?: string; remember?: boolean } = {}): Promise<AuthInfo | ApiError> {
    // Never leave the sign-in button spinning: a server that doesn't answer is given up on after a while,
    // and every way this can fail comes back as an ApiError the form can show.
    const controller = new AbortController();
    const giveUp = window.setTimeout(() => controller.abort(), LOGIN_TIMEOUT_MS);
    let resp: Response;
    try {
      resp = await fetch(API + "/auth/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...browserHintHeaders() },
        body: JSON.stringify({ username, password, totp_code: options.totpCode || null, remember: options.remember ?? false }),
        signal: controller.signal,
      });
    } catch (err) {
      return new ApiError(
        0,
        err instanceof DOMException && err.name === "AbortError"
          ? "The server didn't answer in time. Try again in a moment."
          : "Couldn't reach the server. Check that the API is running and that this page's address is allowed by it (CORS), then try again."
      );
    } finally {
      window.clearTimeout(giveUp);
    }
    if (!resp.ok) {
      const body: ApiErrorBody = await resp.json().catch(() => ({}));
      if (typeof body.detail === "string") return failure(resp, body.detail);
      return failure(
        resp,
        resp.status >= 500
          ? `The server had a problem (HTTP ${resp.status}). Try again, and if it keeps happening tell whoever runs it — its log has the details.`
          : `Sign-in failed (HTTP ${resp.status}).`
      );
    }
    return adopt(await resp.json());
  },

  /** On page load: is there a session? The refresh cookie answers with a fresh access token, or nothing. */
  restoreSession(): Promise<AuthInfo | null> {
    // An unreachable API can't tell us there's a session, so it reads as none: the login screen shows its own error.
    return refreshSession().catch(() => null);
  },

  /** Sign out: the server revokes this session and clears the cookie; other tabs are told to sign out too. */
  async logout(): Promise<void> {
    const headers: Record<string, string> = { ...CLIENT_HEADER };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    await fetch(API + "/auth/logout", { method: "POST", credentials: "include", headers }).catch(() => {});
    dropSession();
    authChannel?.postMessage("signed-out");
  },

  /** First-run setup: turn the install-time PORTAL_PASSWORD sign-in into your own administrator account (same user
   * name, this password). The answer is a new session for that account, adopted here like a sign-in. */
  async setupAdmin(newPassword: string): Promise<AuthInfo> {
    const resp = await apiFetch("/auth/setup-admin", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...browserHintHeaders() },
      body: JSON.stringify({ new_password: newPassword }),
    });
    if (!resp.ok) {
      const body: ApiErrorBody = await resp.json().catch(() => ({}));
      throw failure(resp, errorDetail(resp.status, body, "Setup failed"));
    }
    return adopt(await resp.json());
  },

  // Settings > Active Sessions: the places this account is signed in, each one revocable.
  sessions: {
    list(): Promise<UserSession[]> {
      return getJSON("/auth/sessions");
    },
    revoke(id: string): Promise<void> {
      return del(`/auth/sessions/${id}`, "Couldn't sign that session out");
    },
    async revokeOthers(): Promise<number> {
      const body = await sendJSON<{ revoked: number }>("/auth/sessions/revoke-others", "POST", {});
      return body.revoked;
    },
  },

  listReports(): Promise<ReportMeta[]> {
    return getJSON("/reports");
  },

  /** The reports the signed-in user may open, with their access level on
   * each -- the end-user Reports page's data (unlike listReports above,
   * which is the public every-template list behind the Templates screen). */
  listAccessibleReports(): Promise<AccessibleReport[]> {
    return getJSON("/reports/accessible");
  },

  /** Shortcuts in folders the caller may open, for reports they can open (the Resources screen). */
  listShortcuts(): Promise<ReportShortcut[]> {
    return getJSON("/reports/shortcuts");
  },

  /** Manager-only: the folders a report is also listed in. */
  listReportShortcuts(reportId: string): Promise<ReportShortcut[]> {
    return getJSON(`/reports/${reportId}/shortcuts`);
  },

  createShortcut(reportId: string, folderId: string): Promise<ReportShortcut> {
    return sendJSON(`/reports/${reportId}/shortcuts`, "POST", { folder_id: folderId });
  },

  /** Removes the link only -- the report itself is untouched. */
  deleteShortcut(shortcutId: string): Promise<void> {
    return del(`/reports/shortcuts/${shortcutId}`, "Couldn't remove the shortcut");
  },

  /** Manager-only: a report's filter parameters (with their full option
   * lists) and REST data source. */
  getDataConfig(id: string): Promise<DataConfig> {
    return getJSON(`/reports/${id}/data-config`);
  },

  putDataConfig(id: string, config: DataConfig): Promise<DataConfig> {
    return sendJSON(`/reports/${id}/data-config`, "PUT", config);
  },

  /** Manager-only: try a REST-backed choice list -- saved or not -- and get the
   * choices its paths produce (or a readable reason it can't), so the JSONPaths
   * can be checked against the real response before saving. */
  previewOptions(id: string, source: OptionsSource): Promise<OptionsPreview> {
    return sendJSON(`/reports/${id}/data-config/preview-options`, "POST", { options_source: source });
  },

  /** Manager-only: a report's own protected-terms layer (selected set ids
   * plus its own terms). */
  getProtectedTermsConfig(id: string): Promise<ProtectedTermsConfig> {
    return getJSON(`/reports/${id}/protected-terms-config`);
  },

  putProtectedTermsConfig(id: string, config: ProtectedTermsConfig): Promise<ProtectedTermsConfig> {
    return sendJSON(`/reports/${id}/protected-terms-config`, "PUT", config);
  },

  /** The run page's form: parameters with options already narrowed to the
   * signed-in user's grants. */
  getRunForm(id: string): Promise<RunForm> {
    return getJSON(`/reports/${id}/run-form`);
  },

  /** Run a report as the signed-in user. The server checks every parameter
   * value against the user's grants *before* it fetches the report's data;
   * a value they may not use comes back as a 403 with a readable message. */
  async runReport(
    id: string,
    parameters: Record<string, string>,
    format: RenderFormat,
    fallbackName: string,
    part?: number
  ): Promise<RenderResult> {
    const resp = await apiFetch(`/reports/${id}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parameters, format, ...(part ? { part } : {}) }),
    });
    if (!resp.ok) {
      const body: ApiErrorBody = await resp.json().catch(() => ({}));
      throw failure(resp, errorDetail(resp.status, body, "Run failed"), body.render_error);
    }
    return renderResult(resp, fallbackName, format);
  },

  /** Run a report for an embedded viewer: just the parameter values, plus what
   * authorizes them -- an API client's id + secret (api/app/clients.py). The server
   * fetches the data itself. `ref` is the report's code or id -- Aksor resolves
   * either (api/app/report_ref.py). Deliberately a plain fetch, not apiFetch: an
   * embed is anonymous, so it must neither send this origin's console login
   * nor let a rejection's 401 sign that login out. */
  embedRunReport(
    ref: string,
    parameters: Record<string, string>,
    auth: EmbedAuth,
    format: RenderFormat,
    fallbackName: string,
    part?: number
  ): Promise<RenderResult> {
    // Every run is a full server-side fetch + render (seconds), and the same one can be asked for
    // twice within milliseconds -- React's StrictMode (`npm run dev`) mounts effects twice, and a
    // host may answer our `ready` more than once -- so an identical run already in flight is
    // shared, not repeated. It is forgotten as soon as it settles: asking again later (Refresh,
    // a new View) is a real new request.
    const key = JSON.stringify([ref, parameters, auth, format, part ?? null]);
    const running = embedRunsInFlight.get(key);
    if (running) return running;

    const request = requestEmbedRun(ref, parameters, auth, format, fallbackName, part);
    const forget = () => void embedRunsInFlight.delete(key);
    request.then(forget, forget);
    embedRunsInFlight.set(key, request);
    return request;
  },

  /** The New report wizard: start from the data (api/app/routers/report_wizard.py). */
  wizard: {
    /** Run a data source once, unsaved. `missing` set = it needs test values for those filters first. */
    preview(body: { data_source: DataSource; parameters: ReportParameter[]; values: Record<string, string> }): Promise<DataPreview> {
      return sendJSON("/reports/data-preview", "POST", body);
    },
    /** Create the report as a draft: its source and filters saved, the data as its sample, a starter template. */
    createDraft(body: {
      name: string;
      description?: string | null;
      code?: string | null;
      folder_id?: string | null;
      format: TemplateExt;
      parameters: ReportParameter[];
      data_source: DataSource | null;
      sample: Record<string, unknown>;
      values: Record<string, string>;
    }): Promise<ReportMeta> {
      return sendJSON("/reports/drafts", "POST", body);
    },
    /** Replace the template with a fresh starter in `format` (a new version). */
    starter(id: string, format: TemplateExt): Promise<ReportMeta> {
      return sendJSON(`/reports/${encodeURIComponent(id)}/starter`, "POST", { format });
    },
    check(id: string): Promise<TemplateCheck> {
      return getJSON(`/reports/${encodeURIComponent(id)}/template-check`);
    },
    publish(id: string): Promise<ReportMeta> {
      return sendJSON(`/reports/${encodeURIComponent(id)}/publish`, "POST", {});
    },
  },

  getReport(id: string): Promise<ReportMeta> {
    return getJSON(`/reports/${id}`);
  },

  getSchema(id: string): Promise<ReportSchema> {
    return getJSON(`/reports/${id}/schema`);
  },

  /** The fonts a template names, and whether the server has each one. */
  getReportFonts(id: string): Promise<TemplateFont[]> {
    return getJSON(`/reports/${id}/fonts`);
  },

  createReport(
    name: string,
    description: string,
    file: File,
    resourceBindings?: Record<string, ResourceBinding>,
    code?: string,
    folderId?: string | null
  ): Promise<ReportMeta> {
    const form = new FormData();
    form.set("name", name);
    form.set("description", description);
    form.set("file", file);
    if (resourceBindings) form.set("resource_bindings", JSON.stringify(resourceBindings));
    if (code?.trim()) form.set("code", code.trim());
    if (folderId) form.set("folder_id", folderId);
    return apiFetch("/reports", { method: "POST", body: form }).then((r) => asJson<ReportMeta>(r));
  },

  /** Pre-flight parse of an uploaded .html template — detected fields,
   * resource() names to map, and any Jinja2 syntax errors — run right
   * after RegisterDialog's dropzone accepts an .html file, before the
   * caller has committed to registering it (see
   * api/app/routers/reports.py's parse_template). */
  parseTemplate(file: File): Promise<ParsedTemplate> {
    const form = new FormData();
    form.set("file", file);
    return apiFetch("/reports/parse-template", { method: "POST", body: form }).then((r) => asJson<ParsedTemplate>(r));
  },

  updateReport(
    id: string,
    body: {
      name?: string;
      description?: string;
      sample_context?: Record<string, unknown>;
      // Omit the key to leave folder placement unchanged; pass `null`
      // explicitly to move a report back to the Resources root — see
      // ReportUpdate's docstring in api/app/models/reports.py.
      folder_id?: string | null;
      is_public?: boolean;
      // Omit to leave the code alone; null removes it.
      code?: string | null;
    }
  ): Promise<ReportMeta> {
    return sendJSON(`/reports/${id}`, "PATCH", body);
  },

  /** `note` is the uploader's own "what changed?", kept against this version
   * in the template's change log -- the one thing a binary file can't say. */
  replaceFile(id: string, file: File, note?: string, versionLabel?: string): Promise<ReportMeta> {
    const form = new FormData();
    form.set("file", file);
    if (note?.trim()) form.set("note", note.trim());
    if (versionLabel?.trim()) form.set("version_label", versionLabel.trim());
    return apiFetch(`/reports/${id}/file`, { method: "PUT", body: form }).then((r) => asJson<ReportMeta>(r));
  },

  /** Edit a version's label and/or note after the fact (the file never changes).
   * Send only the keys to change; an empty string clears one. */
  updateVersion(id: string, version: number, changes: { version_label?: string; note?: string }): Promise<ReportVersion> {
    return apiFetch(`/reports/${id}/versions/${version}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    }).then((r) => asJson<ReportVersion>(r));
  },

  /** The template file itself, Jinja2 placeholders intact -- not a
   * rendering of it. Omit `version` for the current file; `1` is the file as
   * first uploaded. Manage-level only, and every call is recorded server-side. */
  async downloadTemplate(id: string, version?: number): Promise<{ blob: Blob; filename: string }> {
    const resp = await apiFetch(`/reports/${id}/file${qs({ version: version !== undefined ? String(version) : undefined })}`);
    if (!resp.ok) {
      const body: ApiErrorBody = await resp.json().catch(() => ({}));
      throw failure(resp, errorDetail(resp.status, body, "Download failed"));
    }
    return { blob: await resp.blob(), filename: filenameFromDisposition(resp, `${id}-v${version ?? "current"}`) };
  },

  /** Every version of the template's file merged with every other recorded
   * change to it, newest first. */
  getChangelog(id: string): Promise<ReportChangelog> {
    return getJSON(`/reports/${id}/changelog`);
  },

  deleteReport(id: string): Promise<void> {
    return del(`/reports/${id}`, "Delete failed", [404]);
  },

  async render(
    id: string,
    data: Record<string, unknown>,
    format: RenderFormat,
    fallbackName: string,
    part?: number
  ): Promise<RenderResult> {
    const resp = await apiFetch(`/reports/${id}/render?format=${format}${part ? `&part=${part}` : ""}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!resp.ok) {
      const body: ApiErrorBody = await resp.json().catch(() => ({}));
      throw failure(resp, errorDetail(resp.status, body, "Render failed"), body.render_error);
    }
    return renderResult(resp, fallbackName, format);
  },

  /** The server's per-format batch size limits -- kept there, not copied here. */
  batchLimits(): Promise<BatchLimits> {
    return getJSON("/reports/batch-limits");
  },

  async renderBatch(
    id: string,
    contexts: Record<string, unknown>[],
    format: RenderFormat
  ): Promise<{ blob: Blob; filename: string }> {
    const resp = await apiFetch(`/reports/${id}/render/batch?format=${format}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(contexts),
    });
    if (!resp.ok) {
      const body: ApiErrorBody = await resp.json().catch(() => ({}));
      throw failure(resp, errorDetail(resp.status, body, "Batch render failed"));
    }
    const blob = await resp.blob();
    return { blob, filename: filenameFromDisposition(resp, `${id}-batch.zip`) };
  },

  // --- Analyze (api/app/routers/analyze.py) --------------------------
  analyze: {
    datasets(): Promise<AnalyzeDataset[]> {
      return getJSON("/analyze/datasets");
    },
    form(name: string): Promise<AnalyzeForm> {
      return getJSON(`/analyze/datasets/${encodeURIComponent(name)}`);
    },
    pivot(dataset: string, values: Record<string, string>, layout: PivotLayout): Promise<PivotResult> {
      return sendJSON("/analyze/pivot", "POST", { dataset, values, layout });
    },
    /** The view as a file -- PDF, Word or Excel -- with its chart when `chart` isn't "table". */
    async export(body: {
      dataset: string;
      values: Record<string, string>;
      layout: PivotLayout;
      format: "pdf" | "docx" | "xlsx";
      chart: AnalysisChart;
      title?: string;
    }): Promise<{ blob: Blob; filename: string }> {
      const resp = await apiFetch("/analyze/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!resp.ok) {
        const err: ApiErrorBody = await resp.json().catch(() => ({}));
        throw failure(resp, errorDetail(resp.status, err, "Export failed"));
      }
      return { blob: await resp.blob(), filename: filenameFromDisposition(resp, `${body.dataset}-analysis.${body.format}`) };
    },
    views: {
      list(): Promise<AnalysisView[]> {
        return getJSON("/analyze/views");
      },
      get(id: string): Promise<AnalysisView> {
        return getJSON(`/analyze/views/${id}`);
      },
      create(body: { title: string; dataset: string; config: AnalysisView["config"] }): Promise<AnalysisView> {
        return sendJSON("/analyze/views", "POST", body);
      },
      update(id: string, body: { title: string; dataset: string; config: AnalysisView["config"] }): Promise<AnalysisView> {
        return sendJSON(`/analyze/views/${id}`, "PUT", body);
      },
      delete(id: string): Promise<void> {
        return del(`/analyze/views/${id}`, "Delete failed");
      },
    },
  },

  // --- Dashboards (api/app/routers/dashboards.py) ------------------------
  dashboards: {
    list(): Promise<DashboardSummary[]> {
      return getJSON("/dashboards");
    },
    get(id: string): Promise<Dashboard> {
      return getJSON(`/dashboards/${id}`);
    },
    create(title: string): Promise<Dashboard> {
      return sendJSON("/dashboards", "POST", { title });
    },
    update(id: string, body: { title: string; description?: string | null; tiles: DashboardTile[]; filters: Record<string, string> }): Promise<Dashboard> {
      return sendJSON(`/dashboards/${id}`, "PUT", body);
    },
    share(id: string, roleIds: string[]): Promise<Dashboard> {
      return sendJSON(`/dashboards/${id}/sharing`, "PUT", { role_ids: roleIds });
    },
    delete(id: string): Promise<void> {
      return del(`/dashboards/${id}`, "Delete failed");
    },
    runTile(id: string, tileId: string, filters: Record<string, string>): Promise<PivotResult & { tile: DashboardTile }> {
      return sendJSON(`/dashboards/${id}/tiles/${encodeURIComponent(tileId)}/run`, "POST", { filters });
    },
  },

  // --- Admin: organizations, users, roles, permissions, grants ---------
  // See api/app/routers/{organizations,users,roles,grants}.py.

  organizations: {
    list(): Promise<Organization[]> {
      return getJSON("/organizations");
    },
    get(id: string): Promise<Organization> {
      return getJSON(`/organizations/${id}`);
    },
    create(body: { id: string; name: string; parent_org_id?: string | null }): Promise<Organization> {
      return sendJSON("/organizations", "POST", body);
    },
  },

  users: {
    list(orgId?: string): Promise<User[]> {
      return getJSON(`/users${qs({ org_id: orgId })}`);
    },
    get(id: string): Promise<User> {
      return getJSON(`/users/${id}`);
    },
    // Self-service — no user:manage required, and deliberately narrower
    // than update() below: no is_active/is_locked, and a password change
    // must carry the correct current_password. 404s for a break-glass
    // login (PORTAL_USERNAME/PORTAL_PASSWORD) — there's no database row
    // behind it to show or edit.
    me(): Promise<User> {
      return getJSON(`/users/me`);
    },
    updateMe(body: {
      email?: string | null;
      display_name?: string | null;
      new_password?: string;
      current_password?: string;
      notify_new_signin?: boolean;
    }): Promise<User> {
      return sendJSON(`/users/me`, "PATCH", body);
    },
    // Recent (ip, browser, device) sign-in fingerprints from the last
    // 30 days -- history, not live sessions. The live, revocable ones are
    // api.sessions above.
    recentSignIns(): Promise<AuthEvent[]> {
      return getJSON(`/users/me/sessions`);
    },
    // Access tab's sign-in activity — every recorded success and failed
    // attempt for this account, most recent first.
    authLog(): Promise<AuthEvent[]> {
      return getJSON(`/users/me/auth-log`);
    },
    // Backs the TopBar notification bell — unacknowledged new-device
    // sign-in alerts, empty once notify_new_signin is off.
    notifications(): Promise<AuthEvent[]> {
      return getJSON(`/users/me/notifications`);
    },
    ackNotifications(): Promise<void> {
      return apiFetch(`/users/me/notifications/ack`, { method: "POST" }).then(() => undefined);
    },
    /** "It was me": dismiss one new-device alert. */
    confirmSignIn(eventId: string): Promise<void> {
      return apiFetch(`/users/me/notifications/${encodeURIComponent(eventId)}/ack`, { method: "POST" }).then(() => undefined);
    },
    /** "Not me": sign out the session a new-device alert is about, and dismiss it. */
    disownSignIn(eventId: string): Promise<{ signed_out: boolean }> {
      return apiFetch(`/users/me/notifications/${encodeURIComponent(eventId)}/sign-out`, { method: "POST" }).then((r) => r.json());
    },
    // Generic per-account settings (see api/app/db/user_settings.py) —
    // one `{code: JSON value}` map, so a new preference is a new code
    // string, not a new endpoint or column. list() 404s for a break-glass
    // login (no database row to attach settings to); userSettings.tsx is
    // what handles that.
    settings: {
      list(): Promise<Record<string, unknown>> {
        return getJSON(`/users/me/settings`);
      },
      set(code: string, value: unknown): Promise<unknown> {
        return sendJSON(`/users/me/settings/${encodeURIComponent(code)}`, "PUT", { value });
      },
    },
    // Profile tab's avatar — re-encoded/downscaled server-side (see
    // api/app/avatar_store.py); avatarBlob() 404s when none is set, same
    // "caller treats a failure as show-the-fallback" contract as
    // images.fileBlob().
    uploadAvatar(file: File): Promise<User> {
      const form = new FormData();
      form.set("file", file);
      return apiFetch(`/users/me/avatar`, { method: "PUT", body: form }).then((r) => asJson<User>(r));
    },
    deleteAvatar(): Promise<User> {
      return apiFetch(`/users/me/avatar`, { method: "DELETE" }).then((r) => asJson<User>(r));
    },
    async avatarBlob(): Promise<Blob> {
      const resp = await apiFetch(`/users/me/avatar`);
      if (!resp.ok) {
        const body: ApiErrorBody = await resp.json().catch(() => ({}));
        throw failure(resp, errorDetail(resp.status, body, "Couldn't load avatar"));
      }
      return resp.blob();
    },
    // Access tab's two-factor authentication -- see api/app/totp.py and
    // types.ts's own note on what this does/doesn't protect.
    totp: {
      enroll(): Promise<TotpEnrollment> {
        return apiFetch(`/users/me/totp/enroll`, { method: "POST" }).then((r) => asJson<TotpEnrollment>(r));
      },
      confirm(code: string): Promise<User> {
        return sendJSON(`/users/me/totp/confirm`, "POST", { code });
      },
      disable(code: string): Promise<User> {
        return sendJSON(`/users/me/totp/disable`, "POST", { code });
      },
    },
    create(
      orgId: string,
      body: {
        username: string;
        email?: string | null;
        display_name?: string | null;
        auth_source: "local" | "ldap";
        password?: string | null;
        // Server default is true -- the new user must choose their own
        // password at first sign-in. Send false only for an account nobody
        // signs in to interactively.
        must_change_password?: boolean;
      }
    ): Promise<User> {
      return sendJSON(`/users${qs({ org_id: orgId })}`, "POST", body);
    },
    update(
      id: string,
      body: {
        email?: string | null;
        display_name?: string | null;
        is_active?: boolean;
        is_locked?: boolean;
        password?: string | null;
        // Require (or stop requiring) a password change at next sign-in.
        must_change_password?: boolean;
        // Lost-authenticator lockout recovery -- clears the target
        // user's 2FA enrollment so they can re-enroll from Settings >
        // Access. No code/current-password check server-side; that's
        // the point (they're locked out precisely because they can't
        // produce one), so this is deliberately user:manage-gated.
        reset_totp?: boolean;
      }
    ): Promise<User> {
      return sendJSON(`/users/${id}`, "PATCH", body);
    },
    // Omit `password` to have the server generate one (returned once in
    // `generated_password`); `require_change` defaults to true server-side.
    resetPassword(id: string, body: { password?: string; require_change?: boolean }): Promise<PasswordResetResult> {
      return sendJSON(`/users/${id}/reset-password`, "POST", body);
    },
    permissions(id: string): Promise<EffectivePermissions> {
      return getJSON(`/users/${id}/permissions`);
    },
    /** Templates they uploaded, what they can reach, and where each permission comes from. */
    overview(id: string): Promise<UserOverview> {
      return getJSON(`/users/${id}/overview`);
    },
  },

  roles: {
    list(orgId?: string): Promise<Role[]> {
      return getJSON(`/roles${qs({ org_id: orgId })}`);
    },
    get(id: string): Promise<Role> {
      return getJSON(`/roles/${id}`);
    },
    create(body: { org_id: string; name: string; description?: string | null }): Promise<Role> {
      return sendJSON("/roles", "POST", body);
    },
    delete(id: string): Promise<void> {
      return del(`/roles/${id}`, "Delete failed");
    },
    setPermissions(id: string, permissions: string[]): Promise<Role> {
      return sendJSON(`/roles/${id}/permissions`, "PUT", { permissions });
    },
  },

  clients: {
    /** Superusers may omit `orgId` to list every organization's clients. */
    list(orgId?: string): Promise<ApiClient[]> {
      return getJSON(`/clients${qs({ org_id: orgId })}`);
    },
    /** The response carries the secret -- the only time it is ever returned. */
    create(body: {
      org_id?: string;
      client_id: string;
      name: string;
      description?: string | null;
      report_ids: string[];
    }): Promise<ApiClientWithSecret> {
      return sendJSON("/clients", "POST", body);
    },
    update(id: string, body: { name?: string; description?: string | null; is_active?: boolean }): Promise<ApiClient> {
      return sendJSON(`/clients/${id}`, "PATCH", body);
    },
    setReports(id: string, reportIds: string[]): Promise<ApiClient> {
      return sendJSON(`/clients/${id}/reports`, "PUT", { report_ids: reportIds });
    },
    /** The old secret stops working at once; the new one is in the response, once. */
    rotateSecret(id: string): Promise<ApiClientWithSecret> {
      return sendJSON(`/clients/${id}/rotate-secret`, "POST", {});
    },
    delete(id: string): Promise<void> {
      return del(`/clients/${id}`, "Delete failed");
    },
  },

  connections: {
    /** Report authors get this too (no header values in it); superusers may omit `orgId` for every organization's. */
    list(orgId?: string): Promise<ConnectionSummary[]> {
      return getJSON(`/connections${qs({ org_id: orgId })}`);
    },
    get(id: string): Promise<Connection> {
      return getJSON(`/connections/${id}`);
    },
    create(body: {
      org_id?: string;
      name: string;
      kind?: "rest" | "jdbc" | "smtp";
      description?: string | null;
      config: ConnectionConfig | JdbcConnectionConfig | SmtpConnectionConfig;
    }): Promise<Connection> {
      return sendJSON("/connections", "POST", { kind: "rest", ...body });
    },
    /** Replaces the description and settings; the name is fixed (reports refer to it). */
    update(id: string, body: { description?: string | null; config: ConnectionConfig | JdbcConnectionConfig | SmtpConnectionConfig }): Promise<Connection> {
      return sendJSON(`/connections/${id}`, "PUT", body);
    },
    /** Logs in with a database connection's settings -- saved or not -- and says whether it worked. Saves nothing. */
    test(config: JdbcConnectionConfig, orgId?: string): Promise<ConnectionTestResult> {
      return sendJSON("/connections/test", "POST", { org_id: orgId, config });
    },
    /** Sends one test email with a mail server's settings -- saved or not. Saves nothing. */
    testMail(config: SmtpConnectionConfig, to: string, orgId?: string): Promise<ConnectionTestResult> {
      return sendJSON("/connections/test-mail", "POST", { org_id: orgId, config, to });
    },
    /** SQL Server: replace the stored procedures and functions reports may call. */
    setRoutines(id: string, routines: ApprovedRoutine[]): Promise<Connection> {
      return sendJSON(`/connections/${id}/routines`, "PUT", { routines });
    },
    /** SQL Server: what the connection's login may run, read from the catalog. Approves nothing. */
    discoverRoutines(id: string): Promise<DiscoveredRoutines> {
      return sendJSON(`/connections/${id}/routines/discover`, "POST", {});
    },
    delete(id: string): Promise<void> {
      return del(`/connections/${id}`, "Delete failed");
    },
  },

  // Database engines and the vendor JDBC drivers (.jar) uploaded for them -- see
  // api/app/jdbc.py. Uploading needs driver:manage; listing, connection:manage too.
  jdbc: {
    engines(): Promise<JdbcEngine[]> {
      return getJSON("/jdbc/engines");
    },
    drivers: {
      list(orgId?: string): Promise<JdbcDriver[]> {
        return getJSON(`/jdbc/drivers${qs({ org_id: orgId })}`);
      },
      upload(body: { name: string; engine: string; driverClass: string; orgId?: string; file: File }): Promise<JdbcDriver> {
        const form = new FormData();
        form.set("name", body.name);
        form.set("engine", body.engine);
        form.set("driver_class", body.driverClass);
        if (body.orgId) form.set("org_id", body.orgId);
        form.set("file", body.file);
        return apiFetch("/jdbc/drivers", { method: "POST", body: form }).then((r) => asJson<JdbcDriver>(r));
      },
      async download(id: string): Promise<{ blob: Blob; filename: string }> {
        const resp = await apiFetch(`/jdbc/drivers/${id}/download`);
        if (!resp.ok) {
          const body: ApiErrorBody = await resp.json().catch(() => ({}));
          throw failure(resp, errorDetail(resp.status, body, "Download failed"));
        }
        return { blob: await resp.blob(), filename: filenameFromDisposition(resp, "driver.jar") };
      },
      delete(id: string): Promise<void> {
        return del(`/jdbc/drivers/${id}`, "Delete failed");
      },
    },
  },

  // Named credentials (Admin > Secrets) a data source's or a connection's own
  // auth can refer to (token_secret/password_secret) instead of an
  // environment variable -- created, rotated and revoked here, in one place,
  // rather than as a value embedded in whatever refers to it. See
  // api/app/secrets.py; the value is never part of any response.
  secrets: {
    /** Report/connection authors get this too (no values, ever); superusers may omit `orgId` for every organization's. */
    list(orgId?: string): Promise<SecretSummary[]> {
      return getJSON(`/secrets${qs({ org_id: orgId })}`);
    },
    get(id: string): Promise<Secret> {
      return getJSON(`/secrets/${id}`);
    },
    create(body: { org_id?: string; name: string; description?: string | null; value: string }): Promise<Secret> {
      return sendJSON("/secrets", "POST", body);
    },
    /** Replaces the value; whatever already names this secret needs no change and uses the new value on its next run. */
    rotate(id: string, value: string): Promise<Secret> {
      return sendJSON(`/secrets/${id}/rotate`, "POST", { value });
    },
    /** `is_active: false` revokes it (existing references start failing, readably); `true` reactivates. */
    update(id: string, body: { description?: string | null; is_active?: boolean }): Promise<Secret> {
      return sendJSON(`/secrets/${id}`, "PATCH", body);
    },
    /** Refused (409) while any report or connection still refers to it. */
    delete(id: string): Promise<void> {
      return del(`/secrets/${id}`, "Delete failed");
    },
  },

  permissions: {
    list(): Promise<Permission[]> {
      return getJSON("/permissions");
    },
  },

  protectedTerms: {
    /** Superusers may omit `orgId` to list every organization's sets. */
    listSets(orgId?: string): Promise<ProtectedTermSet[]> {
      return getJSON(`/protected-term-sets${qs({ org_id: orgId })}`);
    },
    createSet(orgId: string, body: ProtectedTermSetInput): Promise<ProtectedTermSet> {
      return sendJSON("/protected-term-sets", "POST", { org_id: orgId, ...body });
    },
    updateSet(id: string, body: ProtectedTermSetInput): Promise<ProtectedTermSet> {
      return sendJSON(`/protected-term-sets/${id}`, "PUT", body);
    },
    deleteSet(id: string): Promise<void> {
      return del(`/protected-term-sets/${id}`, "Delete failed");
    },
    deploymentFloor(): Promise<DeploymentTerms> {
      return getJSON("/protected-term-sets/deployment-floor");
    },
  },

  grants: {
    roles: {
      list(userId: string): Promise<Grant[]> {
        return getJSON(`/grants/roles${qs({ user_id: userId })}`);
      },
      grant(userId: string, roleId: string, expiresAt?: string | null): Promise<Grant> {
        return sendJSON("/grants/roles", "POST", { user_id: userId, role_id: roleId, expires_at: expiresAt || null });
      },
      revoke(grantId: string): Promise<void> {
        return del(`/grants/roles/${grantId}`, "Revoke failed");
      },
    },
    permissions: {
      list(userId: string): Promise<Grant[]> {
        return getJSON(`/grants/permissions${qs({ user_id: userId })}`);
      },
      grant(userId: string, permissionCode: string, expiresAt?: string | null): Promise<Grant> {
        return sendJSON("/grants/permissions", "POST", {
          user_id: userId,
          permission_code: permissionCode,
          expires_at: expiresAt || null,
        });
      },
      revoke(grantId: string): Promise<void> {
        return del(`/grants/permissions/${grantId}`, "Revoke failed");
      },
    },
    reports: {
      list(reportId: string): Promise<Grant[]> {
        return getJSON(`/grants/reports${qs({ report_id: reportId })}`);
      },
      grant(
        subjectType: "user" | "role",
        subjectId: string,
        reportId: string,
        permissionLevel: "view" | "render" | "manage",
        expiresAt?: string | null,
        parameterLimits?: Record<string, string[]> | null
      ): Promise<Grant> {
        return sendJSON("/grants/reports", "POST", {
          subject_type: subjectType,
          subject_id: subjectId,
          report_id: reportId,
          permission_level: permissionLevel,
          expires_at: expiresAt || null,
          parameter_limits: parameterLimits && Object.keys(parameterLimits).length > 0 ? parameterLimits : null,
        });
      },
      revoke(grantId: string): Promise<void> {
        return del(`/grants/reports/${grantId}`, "Revoke failed");
      },
    },
    folders: {
      list(folderId: string): Promise<Grant[]> {
        return getJSON(`/grants/folders${qs({ folder_id: folderId })}`);
      },
      grant(
        subjectType: "user" | "role",
        subjectId: string,
        folderId: string,
        permissionLevel: "view" | "manage",
        expiresAt?: string | null
      ): Promise<Grant> {
        return sendJSON("/grants/folders", "POST", {
          subject_type: subjectType,
          subject_id: subjectId,
          folder_id: folderId,
          permission_level: permissionLevel,
          expires_at: expiresAt || null,
        });
      },
      revoke(grantId: string): Promise<void> {
        return del(`/grants/folders/${grantId}`, "Revoke failed");
      },
    },
    // Every active report + folder grant the caller may review, in one
    // call -- backs the admin Access Review page. See
    // api/app/routers/grants.py's list_access_review_grants.
    accessReview(orgId?: string): Promise<AccessReviewGrant[]> {
      return getJSON(`/grants/access-review${qs({ org_id: orgId })}`);
    },
  },

  // --- Admin: AD/LDAP directory configuration --------------------------
  // See api/app/routers/ldap.py, api/app/auth_ldap.py.

  ldap: {
    list(orgId?: string): Promise<LdapConfig[]> {
      return getJSON(`/ldap-configs${qs({ org_id: orgId })}`);
    },
    create(
      orgId: string | null,
      body: {
        server_uri: string;
        bind_method: LdapBindMethod;
        base_dn: string;
        direct_bind_dn_template?: string | null;
        service_bind_dn?: string | null;
        service_bind_password_env?: string | null;
        user_search_filter?: string | null;
        upn_domain?: string | null;
        group_search_base?: string | null;
        is_enabled?: boolean;
      }
    ): Promise<LdapConfig> {
      return sendJSON(`/ldap-configs${qs({ org_id: orgId ?? undefined })}`, "POST", body);
    },
    update(id: string, body: Partial<LdapConfig>): Promise<LdapConfig> {
      return sendJSON(`/ldap-configs/${id}`, "PATCH", body);
    },
    delete(id: string): Promise<void> {
      return del(`/ldap-configs/${id}`, "Delete failed");
    },
    test(id: string, username: string, password: string): Promise<LdapTestResult> {
      return sendJSON(`/ldap-configs/${id}/test`, "POST", { username, password });
    },
    groupMappings: {
      list(configId: string): Promise<LdapGroupMapping[]> {
        return getJSON(`/ldap-configs/${configId}/group-mappings`);
      },
      create(configId: string, groupDn: string, roleId: string): Promise<LdapGroupMapping> {
        return sendJSON(`/ldap-configs/${configId}/group-mappings`, "POST", { group_dn: groupDn, role_id: roleId });
      },
      delete(configId: string, mappingId: string): Promise<void> {
        return del(`/ldap-configs/${configId}/group-mappings/${mappingId}`, "Delete failed");
      },
    },
  },

  // --- Admin: job scheduling ---------------------------------------------
  // See api/app/routers/jobs.py, api/app/job_executors.py.

  me: {
    dashboard(): Promise<MyDashboard> {
      return getJSON("/me/dashboard");
    },
    /** My runs: the signed-in person's own runs, newest first (up to 200). */
    runs(limit = 100): Promise<MyRun[]> {
      return getJSON(`/me/runs?limit=${limit}`);
    },
  },

  // Datasets -- api/app/datasets.py. Listing is open to report managers (to build a report on one).
  datasets: {
    list(orgId?: string): Promise<DatasetSummary[]> {
      return getJSON(`/datasets${qs({ org_id: orgId })}`);
    },
    get(id: string): Promise<Dataset> {
      return getJSON(`/datasets/${id}`);
    },
    create(body: DatasetWrite & { org_id?: string; name: string }): Promise<Dataset> {
      return sendJSON("/datasets", "POST", body);
    },
    update(id: string, body: DatasetWrite): Promise<Dataset> {
      return sendJSON(`/datasets/${id}`, "PUT", body);
    },
    delete(id: string): Promise<void> {
      return del(`/datasets/${id}`, "Delete failed");
    },
    /** Run a dataset's source once -- saved or not -- with test values; nothing is saved. */
    preview(body: {
      org_id?: string;
      parameters: ReportParameter[];
      data_source: DataSource;
      fields: DatasetField[];
      measures: DatasetMeasure[];
      values: Record<string, string>;
    }): Promise<DatasetPreview> {
      return sendJSON("/datasets/preview", "POST", body);
    },
    previewOptions(source: OptionsSource, orgId?: string): Promise<OptionsPreview> {
      return sendJSON("/datasets/preview-options", "POST", { org_id: orgId, options_source: source });
    },
    /** Make a dataset of a report's own source and filters, and build the report on it. */
    fromReport(reportId: string, name: string, title: string): Promise<Dataset> {
      return sendJSON("/datasets/from-report", "POST", { report_id: reportId, name, title });
    },
    access: {
      get(id: string): Promise<DatasetAccess> {
        return getJSON(`/datasets/${id}/access`);
      },
      setMode(id: string, mode: DatasetAccessMode): Promise<DatasetAccess> {
        return sendJSON(`/datasets/${id}/access/mode`, "PUT", { mode });
      },
      grant(
        id: string,
        body: { subject_type: "user" | "role"; subject_id: string; level: "run" | "build"; parameter_limits: Record<string, string[]> | null; expires_at: string | null },
      ): Promise<DatasetGrant> {
        return sendJSON(`/datasets/${id}/access`, "POST", body);
      },
      revoke(id: string, grantId: string): Promise<void> {
        return del(`/datasets/${id}/access/${grantId}`, "Revoke failed");
      },
    },
  },

  jobs: {
    list(orgId?: string): Promise<Job[]> {
      return getJSON(`/jobs${qs({ org_id: orgId })}`);
    },
    get(id: string): Promise<Job> {
      return getJSON(`/jobs/${id}`);
    },
    create(
      orgId: string,
      body: {
        name: string;
        description?: string | null;
        job_type: JobType;
        config: Record<string, unknown>;
        trigger_type: TriggerType;
        cron_expression?: string | null;
        interval_seconds?: number | null;
        run_at?: string | null;
        start_date?: string | null;
        end_date?: string | null;
        is_enabled?: boolean;
        max_retries?: number;
        retry_backoff_seconds?: number;
      }
    ): Promise<Job> {
      return sendJSON(`/jobs${qs({ org_id: orgId })}`, "POST", body);
    },
    update(id: string, body: Partial<Job>): Promise<Job> {
      return sendJSON(`/jobs/${id}`, "PATCH", body);
    },
    delete(id: string): Promise<void> {
      return del(`/jobs/${id}`, "Delete failed");
    },
    previewSchedule(body: { cron_expression: string; start_date?: string | null; end_date?: string | null; count?: number }): Promise<SchedulePreview> {
      return sendJSON("/jobs/schedule-preview", "POST", body);
    },
    run(id: string): Promise<JobRun> {
      return apiFetch(`/jobs/${id}/run`, { method: "POST" }).then((r) => asJson<JobRun>(r));
    },
    deliveries(jobId: string, runId: string): Promise<JobDelivery[]> {
      return getJSON(`/jobs/${jobId}/runs/${runId}/deliveries`);
    },
    /** Re-send a run's failed emails, with the same files. */
    resend(jobId: string, runId: string): Promise<{ queued: number }> {
      return sendJSON(`/jobs/${jobId}/runs/${runId}/resend`, "POST", {});
    },
    runs(id: string, status?: string): Promise<JobRun[]> {
      return getJSON(`/jobs/${id}/runs${qs({ status })}`);
    },
    summary(orgId?: string): Promise<JobsSummary> {
      return getJSON(`/jobs/summary${qs({ org_id: orgId })}`);
    },
  },

  system: {
    metrics(): Promise<SystemMetrics> {
      return getJSON("/system/metrics");
    },
  },

  // --- Admin dashboard ------------------------------------------------------
  // See api/app/routers/reports.py's /analytics/summary, api/app/routers/
  // security.py, and specs/admin_dashboard_design.md.

  analytics: {
    renderStats(opts: { days?: number; limit?: number; orgId?: string } = {}): Promise<ReportRenderStats[]> {
      return getJSON(
        `/reports/analytics/summary${qs({
          days: opts.days !== undefined ? String(opts.days) : undefined,
          limit: opts.limit !== undefined ? String(opts.limit) : undefined,
          org_id: opts.orgId,
        })}`
      );
    },
  },

  audit: {
    /** The change audit trail (needs `audit:view`); newest first, paged. */
    list(q: AuditQuery = {}): Promise<AuditPage> {
      return getJSON(
        `/audit${qs({
          entity_type: q.entityType,
          entity_id: q.entityId,
          action: q.action,
          actor: q.actor,
          q: q.q,
          since: q.since,
          until: q.until,
          org_id: q.orgId,
          limit: q.limit !== undefined ? String(q.limit) : undefined,
          offset: q.offset !== undefined ? String(q.offset) : undefined,
        })}`
      );
    },
  },

  security: {
    activity(opts: { sinceHours?: number; limit?: number; orgId?: string } = {}): Promise<SecurityActivityItem[]> {
      return getJSON(
        `/security/activity${qs({
          since_hours: opts.sinceHours !== undefined ? String(opts.sinceHours) : undefined,
          limit: opts.limit !== undefined ? String(opts.limit) : undefined,
          org_id: opts.orgId,
        })}`
      );
    },
  },

  // --- Resources: folders + images ----------------------------------------
  // See api/app/routers/folders.py, images.py.

  folders: {
    list(orgId?: string): Promise<Folder[]> {
      return getJSON(`/folders${qs({ org_id: orgId })}`);
    },
    create(body: { org_id: string; name: string; description?: string | null; parent_folder_id?: string | null }): Promise<Folder> {
      return sendJSON("/folders", "POST", body);
    },
    update(
      id: string,
      body: {
        name?: string;
        description?: string;
        // Same UNSET-vs-null convention as reports.updateReport's
        // folder_id — omit to leave the parent unchanged, pass `null`
        // to move this folder to the Resources root.
        parent_folder_id?: string | null;
        /** Mark a top-level folder as a project, or unmark it. */
        is_project?: boolean;
      }
    ): Promise<Folder> {
      return sendJSON(`/folders/${id}`, "PATCH", body);
    },
    delete(id: string): Promise<void> {
      return del(`/folders/${id}`, "Delete failed");
    },
  },

  // --- Projects: a folder exported as one package, imported elsewhere (api/app/routers/projects.py) ---
  projects: {
    contents(id: string): Promise<ProjectContents> {
      return getJSON(`/projects/${id}`);
    },
    async export(
      id: string,
      body: { leave_out: string[]; versions: boolean; data_sources: boolean; fonts: boolean; term_sets: boolean },
    ): Promise<{ blob: Blob; filename: string }> {
      const resp = await apiFetch(`/projects/${id}/export`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!resp.ok) {
        const err: ApiErrorBody = await resp.json().catch(() => ({}));
        throw failure(resp, errorDetail(resp.status, err, "Export failed"));
      }
      return { blob: await resp.blob(), filename: filenameFromDisposition(resp, "project.aksor-project.zip") };
    },
    async preview(file: File, into: string | null, orgId: string): Promise<ImportPlan> {
      const form = new FormData();
      form.set("file", file);
      form.set("org_id", orgId);
      if (into) form.set("into", into);
      return asJson(await apiFetch("/projects/import/preview", { method: "POST", body: form }));
    },
    apply(token: string, decisions: Record<string, ImportChoice>): Promise<ImportSummary> {
      return sendJSON(`/projects/import/${token}`, "POST", { decisions });
    },
    cancel(token: string): Promise<void> {
      return del(`/projects/import/${token}`, "Cancel failed");
    },
  },

  // --- Fonts: server-wide, added without redeploying (api/app/routers/fonts.py) ---
  fonts: {
    list(): Promise<FontResource[]> {
      return getJSON("/fonts");
    },
    installed(): Promise<InstalledFont[]> {
      return getJSON("/fonts/installed");
    },
    upload(file: File, note: string): Promise<FontResource> {
      const form = new FormData();
      form.set("file", file);
      if (note.trim()) form.set("note", note.trim());
      return apiFetch("/fonts", { method: "POST", body: form }).then((r) => asJson<FontResource>(r));
    },
    coverage(id: string): Promise<FontBlock[]> {
      return getJSON(`/fonts/${id}/coverage`);
    },
    delete(id: string, force = false): Promise<void> {
      return del(`/fonts/${id}${force ? "?force=true" : ""}`, "Delete failed");
    },
    // Like images: the token is a header this app attaches, so the preview fetches the bytes itself.
    async fileBlob(id: string): Promise<Blob> {
      const resp = await apiFetch(`/fonts/${id}/file`);
      if (!resp.ok) {
        const body: ApiErrorBody = await resp.json().catch(() => ({}));
        throw failure(resp, errorDetail(resp.status, body, "Couldn't load the font"));
      }
      return resp.blob();
    },
  },

  images: {
    list(params: { orgId?: string; folderId?: string | null } = {}): Promise<ImageResource[]> {
      return getJSON(`/images${qs({ org_id: params.orgId, folder_id: params.folderId ?? undefined })}`);
    },
    upload(name: string, orgId: string, folderId: string | null, file: File): Promise<ImageResource> {
      const form = new FormData();
      form.set("name", name);
      form.set("org_id", orgId);
      if (folderId) form.set("folder_id", folderId);
      form.set("file", file);
      return apiFetch("/images", { method: "POST", body: form }).then((r) => asJson<ImageResource>(r));
    },
    delete(id: string): Promise<void> {
      return del(`/images/${id}`, "Delete failed");
    },
    /** Rename and/or move (folder_id null = the top level); the id, and every template using it, stay the same. */
    update(id: string, body: { name?: string; folder_id?: string | null }): Promise<ImageResource> {
      return sendJSON(`/images/${id}`, "PATCH", body);
    },
    /** A new picture under the same id -- every template using it changes. */
    replace(id: string, file: File): Promise<ImageResource> {
      const form = new FormData();
      form.set("file", file);
      return apiFetch(`/images/${id}/file`, { method: "PUT", body: form }).then((r) => asJson<ImageResource>(r));
    },
    usage(id: string): Promise<ResourceUsage[]> {
      return getJSON(`/images/${id}/usage`);
    },
    // The access token is a header this app attaches itself (see apiFetch
    // above), not a browser-automatic credential a plain <img src="...">
    // could carry — so thumbnails fetch bytes
    // through apiFetch and the component builds its own object URL
    // (see ResourceThumbnail.tsx) rather than pointing an <img> at a URL.
    async fileBlob(id: string): Promise<Blob> {
      const resp = await apiFetch(`/images/${id}/file`);
      if (!resp.ok) {
        const body: ApiErrorBody = await resp.json().catch(() => ({}));
        throw failure(resp, errorDetail(resp.status, body, "Couldn't load image"));
      }
      return resp.blob();
    },
    /** A small preview (fits size x size) for a file card -- not the original, which may be megabytes. */
    async thumbnailBlob(id: string, size: 240 | 480 = 480): Promise<Blob> {
      const resp = await apiFetch(`/images/${id}/thumbnail?size=${size}`);
      if (!resp.ok) {
        const body: ApiErrorBody = await resp.json().catch(() => ({}));
        throw failure(resp, errorDetail(resp.status, body, "Couldn't load the preview"));
      }
      return resp.blob();
    },
  },

  // The CSS counterpart to `images` above — see api/app/routers/stylesheets.py.
  stylesheets: {
    list(params: { orgId?: string; folderId?: string | null } = {}): Promise<StylesheetResource[]> {
      return getJSON(`/stylesheets${qs({ org_id: params.orgId, folder_id: params.folderId ?? undefined })}`);
    },
    upload(name: string, orgId: string, folderId: string | null, file: File): Promise<StylesheetResource> {
      const form = new FormData();
      form.set("name", name);
      form.set("org_id", orgId);
      if (folderId) form.set("folder_id", folderId);
      form.set("file", file);
      return apiFetch("/stylesheets", { method: "POST", body: form }).then((r) => asJson<StylesheetResource>(r));
    },
    delete(id: string): Promise<void> {
      return del(`/stylesheets/${id}`, "Delete failed");
    },
    /** What was uploaded: the SCSS / Sass / Less source, or the CSS itself. */
    async source(id: string): Promise<string> {
      const resp = await apiFetch(`/stylesheets/${id}/source`);
      if (!resp.ok) throw failure(resp, errorDetail(resp.status, await resp.json().catch(() => null), "Couldn't load it"));
      return resp.text();
    },
    /** The compiled CSS a template gets. */
    async css(id: string): Promise<string> {
      const resp = await apiFetch(`/stylesheets/${id}/file`);
      if (!resp.ok) throw failure(resp, errorDetail(resp.status, await resp.json().catch(() => null), "Couldn't load it"));
      return resp.text();
    },
    update(id: string, body: { name?: string; folder_id?: string | null }): Promise<StylesheetResource> {
      return sendJSON(`/stylesheets/${id}`, "PATCH", body);
    },
    usage(id: string): Promise<ResourceUsage[]> {
      return getJSON(`/stylesheets/${id}/usage`);
    },
    replace(id: string, file: File): Promise<StylesheetResource> {
      const form = new FormData();
      form.set("file", file);
      return apiFetch(`/stylesheets/${id}/file`, { method: "PUT", body: form }).then((r) => asJson<StylesheetResource>(r));
    },
  },
};

export function apiBaseUrl(): string {
  return window.PORTAL_API_BASE_URL || window.location.origin;
}
