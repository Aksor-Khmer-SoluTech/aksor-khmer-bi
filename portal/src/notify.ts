// A failed request must always reach the person who caused it, never only the browser's network tab.
// Pages that show an error themselves (an alert above a form, a message inside a dialog) keep doing so; this
// is the net under everything else: `reportError(err)` raises a toast, and main.tsx sends every unhandled
// promise rejection here too, so an async click handler that forgot its try/catch still says what went wrong.
//
// Plain module state (no React) so api.ts and event listeners can call it; Toaster.tsx subscribes.
import { ApiError } from "./api";
import { recordFailure, type FailureInfo } from "./errorLog";

export type ToastKind = "error" | "success" | "info";

export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  message: string;
  /** Shown under "Technical details" with a Copy button. */
  info?: FailureInfo;
}

type Listener = (toasts: Toast[]) => void;

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<Listener>();
const MAX_TOASTS = 4;

function emit(): void {
  for (const l of listeners) l(toasts);
}

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener);
  listener(toasts);
  return () => listeners.delete(listener);
}

export function dismissToast(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export function notify(kind: ToastKind, title: string, message = "", info?: FailureInfo): void {
  // The same failure twice in a row (a retry, two panels loading the same list) is one toast, not a stack.
  const last = toasts[toasts.length - 1];
  if (last && last.kind === kind && last.title === title && last.message === message) return;
  toasts = [...toasts, { id: nextId++, kind, title, message, info }].slice(-MAX_TOASTS);
  emit();
}

/** Headline for a failure, by what the status means to the person using the portal. */
function titleFor(err: unknown): string {
  if (!(err instanceof ApiError)) return "Something went wrong";
  if (err.status === 0) return "Can't reach the server";
  if (err.status === 403) return "Not allowed";
  if (err.status === 404) return "Not found";
  if (err.status === 409) return "Conflict";
  if (err.status === 413) return "Too large";
  if (err.status === 422 || err.status === 400) return "Please check the values";
  if (err.status === 429) return "Too many requests";
  if (err.status >= 500) return "Server error";
  return "Request failed";
}

function isIgnorable(err: unknown): boolean {
  // Cancelled on purpose (a newer request replaced it, the page closed).
  // pdf.js rejects a page render that was cancelled for a newer one the same way.
  const name = (err as { name?: unknown } | null)?.name;
  if (name === "AbortError" || name === "RenderingCancelledException") return true;
  // The session ended: api.ts already sends the person back to the sign-in page.
  if (err instanceof ApiError && err.status === 401) return true;
  return false;
}

/** The technical details of any failure: an API error's own, or -- for a bug in the page -- a new "script" entry
 * (recorded once per error object). */
const scriptInfo = new WeakMap<object, FailureInfo>();
export function failureInfo(err: unknown): FailureInfo {
  if (err instanceof ApiError && err.info) return err.info;
  const key = typeof err === "object" && err !== null ? err : null;
  const known = key ? scriptInfo.get(key) : undefined;
  if (known) return known;
  const message = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
  const info = recordFailure({ kind: "script", method: "", path: "", status: 0, requestId: null, message });
  if (key) scriptInfo.set(key, info);
  return info;
}

/** Show a failure as a toast. `context` names what was being done ("Delete template") when the message alone
 * wouldn't say. */
export function reportError(err: unknown, context?: string): void {
  if (isIgnorable(err)) return;
  const message = err instanceof Error ? err.message : typeof err === "string" ? err : "An unexpected error occurred.";
  notify("error", context ? `${context} — ${titleFor(err)}` : titleFor(err), message, failureInfo(err));
}

/** For lookups that fill in a page's extras (organization names, role lists): a 403/404 there just means this
 * person can't see that list, which the page already copes with, so only real failures are raised. */
export function reportLoadError(err: unknown, context?: string): void {
  if (err instanceof ApiError && (err.status === 403 || err.status === 404)) return;
  reportError(err, context);
}
