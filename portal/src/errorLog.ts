// What a technician needs to troubleshoot a failure without opening the browser's developer tools: every failed
// API request (and every script error nobody caught) is kept here with what was called, how it answered, the
// request id the API logged it under, when, and on which page. Toasts and dialogs show one entry under
// "Technical details"; Account menu -> Recent errors lists them all with a Copy button.
//
// No imports from api.ts (it records into this module) or React.

export interface FailureInfo {
  id: number;
  /** ISO time it happened. */
  when: string;
  /** "http" -- the API answered with an error; "network" -- no answer at all; "script" -- a bug in the page. */
  kind: "http" | "network" | "script";
  method: string;
  /** The API path called, without the server part (e.g. /api/v1/reports/abc). */
  path: string;
  /** 0 when there was no answer. */
  status: number;
  /** The API's X-Request-ID: the same id is on every server log line about this request. */
  requestId: string | null;
  message: string;
  /** The portal page (its #/route) it happened on. */
  page: string;
}

const MAX_ENTRIES = 50;
let entries: FailureInfo[] = [];
let nextId = 1;
type Listener = (entries: FailureInfo[]) => void;
const listeners = new Set<Listener>();

export function recordFailure(info: Omit<FailureInfo, "id" | "when" | "page">): FailureInfo {
  const entry: FailureInfo = { ...info, id: nextId++, when: new Date().toISOString(), page: location.hash || "#/" };
  entries = [entry, ...entries].slice(0, MAX_ENTRIES);
  for (const l of listeners) l(entries);
  return entry;
}

export function recentFailures(): FailureInfo[] {
  return entries;
}

export function subscribeFailures(listener: Listener): () => void {
  listeners.add(listener);
  listener(entries);
  return () => listeners.delete(listener);
}

export function clearFailures(): void {
  entries = [];
  for (const l of listeners) l(entries);
}

const STATUS_TEXT: Record<number, string> = {
  0: "No answer (network, server down or blocked)",
  400: "Bad Request",
  401: "Unauthorized",
  403: "Forbidden",
  404: "Not Found",
  405: "Method Not Allowed",
  408: "Request Timeout",
  409: "Conflict",
  413: "Payload Too Large",
  415: "Unsupported Media Type",
  422: "Unprocessable Content",
  429: "Too Many Requests",
  500: "Internal Server Error",
  502: "Bad Gateway",
  503: "Service Unavailable",
  504: "Gateway Timeout",
};

export function statusLabel(status: number): string {
  return `${status || "—"} ${STATUS_TEXT[status] ?? ""}`.trim();
}

/** Where to look next, for whoever runs the server. */
export function nextStep(info: FailureInfo): string {
  if (info.kind === "script") return "A problem in the portal page itself; reload. If it repeats, report it with these details.";
  if (info.status === 0)
    return "The browser got no answer: check the API is running (./deployment.sh status), that the portal's API address (PORTAL_API_BASE_URL) is right, and that the API allows this site (CORS_ALLOWED_ORIGINS).";
  if (info.status === 502 || info.status === 504)
    return "The proxy in front of the API got no answer from it: check the API container and its log.";
  if (info.status === 503) return "The API is starting, overloaded or in maintenance: wait and retry; check its log.";
  if (info.status >= 500)
    return info.requestId
      ? `On the server, search the API log for this reference: grep ${info.requestId} data/logs/* (or ./deployment.sh app logs api | grep ${info.requestId}) — the full error is there.`
      : "Check the API log at the time shown.";
  if (info.status === 401) return "The session ended; sign in again.";
  if (info.status === 403) return "The account lacks a permission for this; an administrator can grant it (Admin → Roles).";
  if (info.status === 404) return "The item or page no longer exists (deleted, moved, or a stale link); reload.";
  if (info.status === 409) return "It conflicts with existing data or a change made meanwhile; reload and retry.";
  if (info.status === 413) return "The upload is over the size limit of the server or its proxy (nginx client_max_body_size).";
  return "The server refused the request for the reason in the message.";
}

/** Plain text for pasting into a ticket or chat. */
export function describeFailure(info: FailureInfo): string {
  const local = new Date(info.when).toLocaleString();
  return [
    `Time:       ${local} (${info.when})`,
    info.kind === "script" ? `Error:      script error` : `Request:    ${info.method} ${info.path}`,
    info.kind === "script" ? null : `Status:     ${statusLabel(info.status)}`,
    `Reference:  ${info.requestId ?? "—"}`,
    `Message:    ${info.message}`,
    `Page:       ${location.origin}${location.pathname}${info.page}`,
    `What next:  ${nextStep(info)}`,
  ]
    .filter(Boolean)
    .join("\n");
}

export function describeAll(list: FailureInfo[], header: string): string {
  return [`${header}\nBrowser: ${navigator.userAgent}`, ...list.map((f, i) => `#${i + 1}\n${describeFailure(f)}`)].join("\n\n");
}
