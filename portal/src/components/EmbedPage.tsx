import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { api, ApiError, type EmbedAuth } from "../api";
import type { ReportMeta, TemplateExt } from "../types";
import ReportSkeleton from "./ReportSkeleton";

const ReportViewer = lazy(() => import("./ReportViewer"));

// Every message this page sends/receives is tagged with this so a
// listener can ignore unrelated postMessage traffic on the same window
// (browser extensions, other embedded widgets, etc.) without guessing.
const SOURCE = "aksor-report-viewer";

// How long to give the embedding page to answer our `ready` with its parameters before
// assuming nobody will, and looking the report up to show its own sample data instead.
// The host normally replies within a few milliseconds; this only bounds the fallback.
const EMBEDDER_GRACE_MS = 750;

interface ContextMessage {
  source: typeof SOURCE;
  type: "render";
  /** JSON-serializable context to render this report against -- same
   * shape POST /reports/{id}/render's body expects. */
  context: Record<string, unknown>;
}

/** The other way in: no data at all, just the report's parameter values --
 * with an API client's id + secret an admin granted the report (api/app/clients.py).
 * The server fetches the data itself, so the host page never handles it -- and what it posts is small and
 * readable. */
interface ParametersMessage {
  source: typeof SOURCE;
  type: "render";
  parameters: Record<string, string>;
  clientId?: string;
  clientSecret?: string;
}

type InboundMessage = ContextMessage | ParametersMessage;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInboundMessage(data: unknown): data is InboundMessage {
  if (!isPlainObject(data) || data.source !== SOURCE || data.type !== "render") return false;
  if ("parameters" in data) {
    return (
      isPlainObject(data.parameters) &&
      Object.values(data.parameters).every((v) => typeof v === "string") &&
      (data.clientId === undefined) === (data.clientSecret === undefined) &&
      (data.clientId === undefined || (typeof data.clientId === "string" && typeof data.clientSecret === "string"))
    );
  }
  return isPlainObject(data.context);
}

// ReportViewer refetches whenever its contextData *reference* changes; for a
// run by parameters the data comes from the server (via `renderer`), not from
// that prop -- so hand it one stable empty object, and bump `refreshKey` per run.
const NO_CONTEXT: Record<string, unknown> = {};

function postToParent(message: Record<string, unknown>) {
  // Embeds only ever exist inside someone else's page -- `window === top`
  // means this URL was opened directly (e.g. while testing it), and
  // there's no parent to tell anything.
  if (window.parent === window) return;
  // Payloads here (a page count, a short error string, a "ready" ping)
  // carry nothing sensitive -- the render API itself is already public,
  // unauthenticated (see api/app/routers/reports.py) -- so a wildcard
  // target lets this work for an embedder on any origin without them
  // having to register one with us first.
  window.parent.postMessage({ source: SOURCE, ...message }, "*");
}

/** Chrome-less report viewer meant to live in a third party's <iframe>,
 * reachable only by direct URL (`#/embed/<report_id>`) -- never linked to
 * from anywhere inside the app itself, and deliberately outside
 * App.tsx's auth gate: the render/read endpoints it calls are already
 * fully public (see reports.py's module docstring), so requiring a
 * console sign-in here would just be friction with no security behind
 * it, and would make embedding on someone else's page impossible anyway.
 *
 * Context data reaches it two ways, and both can be used together:
 *  1. A `?context=<JSON>` query param inside the hash, e.g.
 *     `#/embed/abc123?context=%7B%22name%22%3A%22Sok%22%7D` -- enough on
 *     its own for a static embed, no parent-page JS required.
 *  2. `postMessage({ source: "aksor-report-viewer", type: "render",
 *     context: {...} }, embedOrigin)` from the parent page at any time
 *     after this posts its own `{ source, type: "ready" }` -- lets one
 *     embedded iframe be updated live (a form the visitor is filling
 *     in, a record picker, etc.) without a reload. See IntegrationTab.tsx
 *     for a copy-pasteable snippet of both.
 * A report with a server-side data source can be driven by parameters
 * instead of data: `postMessage({ source, type: "render", parameters: {...},
 * clientId, clientSecret })`, an API client an admin granted this report
 * (api/app/clients.py). This frame then asks POST /reports/{id}/embed-run,
 * and the *server* fetches the data -- the host page never handles it, and
 * without a valid client nothing is fetched (unlike the two ways above, which
 * only format data the caller already holds). Note the secret passes through
 * the host page's JavaScript, so anyone who can open that page can read it:
 * grant such a client only the reports every visitor of that page may see.
 *
 * If none has supplied anything yet, this falls back to the report's
 * own saved sample context (Preview tab > "Save as sample") so a
 * bare `<iframe src=".../#/embed/abc123">` still shows *something*
 * real rather than a blank frame.
 */
export default function EmbedPage({ reportId }: { reportId: string }) {
  const [report, setReport] = useState<ReportMeta | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [contextData, setContextData] = useState<Record<string, unknown> | null>(null);
  // Set instead of contextData when the host posts parameters (and
  // an API client's credentials). `id` counts runs, so a new one re-renders in place rather than remounting.
  const [paramRun, setParamRun] = useState<{ parameters: Record<string, string>; auth: EmbedAuth; id: number } | null>(null);

  // Query params live inside the hash (`#/embed/<id>?a=b`), not in
  // location.search -- see hooks.ts's parseHash. Deliberately *not*
  // memoized on mount: this component doesn't remount on every hash
  // change (App.tsx keeps the same <EmbedPage> as long as `reportId`
  // itself is unchanged), so a mount-once snapshot of the query string
  // would go stale the moment a real embedder's <iframe> is asked to
  // change just its query params on an already-loaded frame.
  const [, queryStr] = window.location.hash.split("?");
  const params = new URLSearchParams(queryStr ?? "");

  const hideToolbar = params.get("toolbar") === "0";
  const theme = params.get("theme");

  // Set the moment either the URL's ?context or a postMessage supplies
  // real data -- guards the sample-context fallback below from
  // clobbering it if the report's own metadata (a network call) happens
  // to resolve *after* one of those, which a fast parent-page
  // postMessage easily wins the race against.
  const externalContextRef = useRef(false);

  // Applied directly (not through preferences.ts's localStorage-backed
  // helpers) -- an embed's theme is the embedder's call via the URL,
  // independent of whatever the visitor last picked in the full console.
  useEffect(() => {
    if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Running a report by parameters needs nothing about the report up front: the run's own response
  // says its name and template type (`runInfo`, via ReportViewer's onDescribed). So the report is not
  // looked up on load. The embedding page gets a moment to send its parameters -- it does, as soon
  // as it sees our `ready` -- and the lookup happens only if none arrive (the bare-URL sample
  // fallback), or if a `context` message / `?context=` URL does, which need the report's shape.
  // A parameter-driven embed therefore makes no request but the run itself.
  const [graceOver, setGraceOver] = useState(false);
  const [runInfo, setRunInfo] = useState<{ name: string; ext: TemplateExt } | null>(null);
  const lookupStarted = useRef(false);
  const hasUrlContext = params.has("context");

  useEffect(() => {
    setReport(null);
    setRunInfo(null);
    setGraceOver(false);
    lookupStarted.current = false;
    const timer = setTimeout(() => setGraceOver(true), EMBEDDER_GRACE_MS);
    return () => clearTimeout(timer);
  }, [reportId]);

  useEffect(() => {
    if (paramRun || report || lookupStarted.current) return;
    if (!(graceOver || hasUrlContext || contextData)) return;
    lookupStarted.current = true;
    api.getReport(reportId).then(setReport).catch((err) => setLoadError(err instanceof ApiError ? err.message : "Report not found"));
  }, [reportId, paramRun, report, graceOver, hasUrlContext, contextData]);

  // The URL's own ?context (if present) wins once the report metadata
  // needed to know its shape has loaded; otherwise fall back to the
  // template's saved sample so a bare embed URL isn't just a blank frame.
  useEffect(() => {
    if (!report || externalContextRef.current) return;
    const fromUrl = params.get("context");
    if (fromUrl) {
      try {
        externalContextRef.current = true;
        setContextData(JSON.parse(fromUrl));
        return;
      } catch {
        setLoadError("The context= URL parameter isn't valid JSON.");
        return;
      }
    }
    if (report.sample_context) setContextData(report.sample_context);
    // `queryStr`, not `params` -- a fresh URLSearchParams instance is a
    // new object every render even when its contents are identical, so
    // depending on the object itself would refire this every render and
    // (since JSON.parse also returns a new object each time) never
    // settle. The raw string it's built from has normal value equality.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, queryStr]);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (!isInboundMessage(event.data)) return;
      externalContextRef.current = true;
      setLoadError(null);
      const message = event.data;
      if ("parameters" in message) {
        const auth: EmbedAuth = { clientId: message.clientId, clientSecret: message.clientSecret };
        setParamRun((previous) => ({ parameters: message.parameters, auth, id: (previous?.id ?? 0) + 1 }));
      } else {
        setParamRun(null);
        setContextData(message.context);
      }
    }
    window.addEventListener("message", onMessage);
    postToParent({ type: "ready", reportId });
    return () => window.removeEventListener("message", onMessage);
  }, [reportId]);

  if (loadError && !report && !paramRun) {
    return (
      <div className="embed-page-status">
        <p className="alert alert-error">{loadError}</p>
      </div>
    );
  }

  if (!report && !paramRun) {
    return (
      <div className="embed-page-status">
        <ReportSkeleton />
      </div>
    );
  }

  if (!contextData && !paramRun) {
    return (
      <div className="embed-page-status">
        <p className="muted" style={{ textAlign: "center", maxWidth: 360 }}>
          Waiting for data to render <strong>{report?.name ?? reportId}</strong> against — pass it as this URL's{" "}
          <span className="mono">?context=</span> parameter, or postMessage{" "}
          <span className="mono">{`{ source: "${SOURCE}", type: "render", context: {...} }`}</span> to this frame
          (or, for a report with a data source, <span className="mono">parameters</span>, plus an API client's{" "}
          <span className="mono">clientId</span> + <span className="mono">clientSecret</span>).
        </p>
      </div>
    );
  }

  return (
    <div className="embed-page">
      <Suspense
        fallback={
          <div className="embed-page-status">
            <ReportSkeleton />
          </div>
        }
      >
        <ReportViewer
          // The ref the embedder put in the URL (normally the report's code), not the id it
          // resolved to: Aksor accepts either on every report route, and a code is the same
          // in every environment -- so requests all name the report the way the embedder did.
          reportId={reportId}
          // Stable for the life of a run by parameters: ReportViewer refetches when this changes.
          reportName={paramRun ? reportId : (report?.name ?? reportId)}
          templateExt={(paramRun ? runInfo?.ext : undefined) ?? report?.template_ext ?? "docx"}
          onDescribed={setRunInfo}
          contextData={paramRun ? NO_CONTEXT : contextData ?? NO_CONTEXT}
          renderer={
            paramRun
              ? (format, part) => api.embedRunReport(reportId, paramRun.parameters, paramRun.auth, format, reportId, part)
              : undefined
          }
          refreshKey={paramRun?.id ?? 0}
          hideToolbar={hideToolbar}
          onRendered={(pageCount) => postToParent({ type: "rendered", reportId, pageCount })}
          onRenderError={(message) => postToParent({ type: "error", reportId, message })}
        />
      </Suspense>
    </div>
  );
}
