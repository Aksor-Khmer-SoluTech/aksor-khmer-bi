import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";
import { Play, SlidersHorizontal } from "lucide-react";
import { api, ApiError, type EmbedAuth } from "../api";
import { initialValue } from "../dateFormat";
import type { EmbedForm } from "../types";
import { ParameterField } from "./RunReportPage";
import ReportSkeleton from "./ReportSkeleton";

const ReportViewer = lazy(() => import("./ReportViewer"));

const SOURCE = "aksor-report-viewer";
const NO_CONTEXT: Record<string, unknown> = {};

function postToParent(message: Record<string, unknown>) {
  if (window.parent === window) return;
  window.parent.postMessage({ source: SOURCE, ...message }, "*");
}

/** What the host posts to start form mode: a ticket its server obtained, or (for a trusted host) client credentials. */
function parseInit(data: unknown): EmbedAuth | null {
  if (typeof data !== "object" || data === null) return null;
  const d = data as Record<string, unknown>;
  if (d.source !== SOURCE || d.type !== "init") return null;
  if (typeof d.ticket === "string" && d.ticket) return { ticket: d.ticket };
  if (typeof d.clientId === "string" && typeof d.clientSecret === "string") return { clientId: d.clientId, clientSecret: d.clientSecret };
  return null;
}

/** Embed "form mode" (`#/embed/<report>?form=1`): the report's own filter form beside its viewer, all inside the
 * host's iframe, so the host builds no filter UI. The host answers our `ready` with `init` ({ticket}); the
 * form comes from `embed-form`, the run from `embed-run` -- both authorized by the ticket, so no secret is in the
 * page. Filters the ticket presets (`locked`) are neither shown nor sent: the server applies them. */
export default function EmbedFormPage({ reportId }: { reportId: string }) {
  const [auth, setAuth] = useState<EmbedAuth | null>(null);
  const [form, setForm] = useState<EmbedForm | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState<Record<string, string> | null>(null);
  const [runId, setRunId] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const next = parseInit(event.data);
      if (!next) return;
      setError(null);
      setForm(null);
      setSubmitted(null);
      setAuth(next);
    }
    window.addEventListener("message", onMessage);
    postToParent({ type: "ready", reportId });
    return () => window.removeEventListener("message", onMessage);
  }, [reportId]);

  useEffect(() => {
    if (!auth) return;
    let cancelled = false;
    api
      .embedForm(reportId, auth)
      .then((f) => {
        if (cancelled) return;
        setForm(f);
        setValues(
          Object.fromEntries(
            f.parameters
              .filter((p) => !p.locked)
              .map((p) => [p.name, p.options ? (p.options.length === 1 ? p.options[0].value : "") : initialValue(p.type, p.default_value)]),
          ),
        );
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Couldn't open this report";
        setError(message);
        postToParent({ type: "error", reportId, message });
      });
    return () => {
      cancelled = true;
    };
  }, [auth, reportId]);

  // Tell the host the form is on screen, so it can drop its loading state (a run's own `rendered` comes later).
  const formShown = form !== null;
  useEffect(() => {
    if (formShown) postToParent({ type: "formready", reportId });
  }, [formShown, reportId]);

  if (error) {
    return (
      <div className="embed-page-status">
        <p className="alert alert-error">{error}</p>
      </div>
    );
  }
  if (!form || !auth) {
    return (
      <div className="embed-page-status">
        <ReportSkeleton />
      </div>
    );
  }

  const visible = form.parameters.filter((p) => !p.locked);
  const complete = visible.every(
    (p) => !p.required || ((p.options === null || p.options.length > 0) && (values[p.name] ?? "") !== ""),
  );
  const dirty = submitted !== null && visible.some((p) => submitted[p.name] !== values[p.name]);

  function run(e: FormEvent) {
    e.preventDefault();
    if (!complete || busy) return;
    const snapshot = { ...values };
    setBusy(true);
    setSubmitted(snapshot);
    setRunId((n) => n + 1);
    postToParent({ type: "submitted", reportId, parameters: snapshot });
  }

  return (
    <div className="embed-form-page">
      <form className="embed-form-filters" onSubmit={run}>
        <button type="submit" className="btn btn-primary run-sidebar-submit" disabled={!complete || busy} aria-busy={busy}>
          {busy ? <span className="spinner" /> : <Play size={14} aria-hidden="true" />}
          {busy ? "Running…" : "Run report"}
        </button>
        {dirty && <span className="muted run-sidebar-note">Filters changed — run again to update.</span>}
        {visible.length > 0 && (
          <>
            <div className="run-filter-head-label run-sidebar-label">
              <SlidersHorizontal size={13} aria-hidden="true" />
              Filters
            </div>
            <div className="run-fields-vertical">
              {visible.map((p) => (
                <ParameterField
                  key={p.name}
                  parameter={p}
                  value={values[p.name] ?? ""}
                  onChange={(next) => setValues((prev) => ({ ...prev, [p.name]: next }))}
                />
              ))}
            </div>
          </>
        )}
      </form>
      <div className="embed-form-result">
        {submitted ? (
          <Suspense fallback={<ReportSkeleton />}>
            <ReportViewer
              reportId={reportId}
              reportName={form.name}
              templateExt={form.template_ext}
              contextData={NO_CONTEXT}
              renderer={(format, part) => api.embedRunReport(reportId, submitted, auth, format, form.name, part)}
              refreshKey={runId}
              onBusyChange={setBusy}
              onRendered={(pageCount) => postToParent({ type: "rendered", reportId, pageCount })}
              onRenderError={(message) => postToParent({ type: "error", reportId, message })}
            />
          </Suspense>
        ) : (
          <p className="muted embed-form-empty">
            {visible.length === 0 ? "Run the report to preview it here." : "Set your filters, then run the report to preview it here."}
          </p>
        )}
      </div>
    </div>
  );
}
