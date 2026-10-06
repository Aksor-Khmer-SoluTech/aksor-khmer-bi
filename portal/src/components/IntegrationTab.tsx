import { BATCH_RENDER_ENABLED } from "../features";
import { useState } from "react";
import { apiBaseUrl } from "../api";
import { FORMATS_BY_EXT, type RenderFormat, type ReportMeta } from "../types";
import CodeSnippet from "./CodeSnippet";

/** `ref` is what identifies the template in every snippet: its report_id, or its
 * code -- the API accepts either wherever an ID goes (see report_ref.py). */
function buildSnippets(report: ReportMeta, format: RenderFormat, ref: string) {
  const base = apiBaseUrl();
  const id = ref;
  const sample = report.sample_context ?? { field_name: "..." };
  const payload = JSON.stringify(sample);
  const payloadPy = JSON.stringify(sample, null, 4);

  // The portal's own origin, not the API's -- #/embed/<id> is a page
  // this app serves itself (see EmbedPage.tsx), separate from the api
  // service buildSnippets' other snippets call directly.
  const embedOrigin = window.location.origin;
  const embedUrl = `${embedOrigin}/#/embed/${id}`;
  const embedUrlWithContext = `${embedUrl}?context=${encodeURIComponent(payload)}`;

  const embedHtml = `<!-- Static: context baked into the URL, works with zero JavaScript -->
<iframe
  src="${embedUrlWithContext}"
  width="100%"
  height="720"
  style="border: 0"
  title="${report.name}"
></iframe>`;

  const embedJs = `// Dynamic: update what's shown without reloading the <iframe> --
// e.g. re-render against whatever the visitor just filled in a form with.
const iframe = document.querySelector("iframe[data-report='${id}']");

window.addEventListener("message", (event) => {
  if (event.data?.source !== "aksor-report-viewer") return;
  if (event.data.type === "ready") {
    // Safe to postMessage now -- send the first render.
    iframe.contentWindow.postMessage(
      { source: "aksor-report-viewer", type: "render", context: ${payload} },
      "${embedOrigin}"
    );
  }
  if (event.data.type === "rendered") console.log(\`Rendered \${event.data.pageCount} page(s)\`);
  if (event.data.type === "error") console.error("Report render failed:", event.data.message);
});

// <iframe data-report="${id}" src="${embedUrl}"></iframe>`;

  const curl = `curl -X POST "${base}/api/v1/reports/${id}/render?format=${format}" \\
  -H "Content-Type: application/json" \\
  -d '${payload}' \\
  -o output.${format}`;

  const js = `const resp = await fetch("${base}/api/v1/reports/${id}/render?format=${format}", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(${payload}),
});
const blob = await resp.blob(); // pdf/png can be shown inline; docx/xlsx should be saved`;

  const python = `import requests

resp = requests.post(
    "${base}/api/v1/reports/${id}/render",
    params={"format": "${format}"},
    json=${payloadPy},
)
resp.raise_for_status()
with open("output.${format}", "wb") as f:
    f.write(resp.content)`;

  const batchCurl = `curl -X POST "${base}/api/v1/reports/${id}/render/batch?format=${format}" \\
  -H "Content-Type: application/json" \\
  -d '[${payload}, ${payload}]' \\
  -o output.zip`;

  return { curl, js, python, batchCurl, embedHtml, embedJs, embedUrl };
}

export default function IntegrationTab({ report, onOpenOverview }: { report: ReportMeta; onOpenOverview: () => void }) {
  const formats = FORMATS_BY_EXT[report.template_ext];
  // The embed viewer pages through a rendered PDF (see EmbedPage.tsx) --
  // an xlsx-sourced template has no PDF rendering path at all (see
  // types.ts's FORMATS_BY_EXT), so there's nothing to embed for one.
  const canEmbed = formats.includes("pdf");
  const [format, setFormat] = useState<RenderFormat>(formats[0]);
  // A template with a code defaults to it: it's the address that survives
  // moving between environments, and the one an integration should hold.
  const [chosen, setChosen] = useState<"id" | "code">(report.code ? "code" : "id");
  const by = report.code ? chosen : "id";
  const ref = by === "code" && report.code ? report.code : report.report_id;
  const snippets = buildSnippets(report, format, ref);

  return (
    <div className="stack">
      <div className="panel">
        <h2 className="panel-title">Call this template from your app</h2>
        <p className="panel-subtitle">
          Every snippet below is filled in with this template's real{" "}
          {by === "code" ? <strong>code</strong> : <span className="mono">report_id</span>}
          {report.sample_context ? " and its saved sample context" : " — save a sample in Preview for realistic example data"}.
        </p>
        <div className="row" style={{ marginBottom: 10, alignItems: "flex-start" }}>
          <div className="field-block" style={{ flex: "0 0 auto", margin: 0 }}>
            <span className="field-label text-[0.82rem]">Address it by</span>
            <div className="segmented" role="group" aria-label="Address this template by">
              <button
                type="button"
                className={`segmented-btn${by === "id" ? " active" : ""}`}
                aria-pressed={by === "id"}
                onClick={() => setChosen("id")}
              >
                ID
              </button>
              <button
                type="button"
                className={`segmented-btn${by === "code" ? " active" : ""}`}
                aria-pressed={by === "code"}
                disabled={!report.code}
                title={report.code ? undefined : "This template has no code yet"}
                onClick={() => setChosen("code")}
              >
                Code
              </button>
            </div>
          </div>
          <label style={{ flex: "0 0 140px" }}>
            <span>Format</span>
            <select value={format} onChange={(e) => setFormat(e.target.value as RenderFormat)}>
              {formats.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="field-hint" style={{ margin: "0 0 16px" }}>
          {report.code ? (
            by === "code" ? (
              <>
                By code, the same calls work in every environment that has a template with the code{" "}
                <span className="mono">{report.code}</span>. If the code is ever changed or removed they stop working; the ID never does.
              </>
            ) : (
              <>
                The ID is different in every environment. Switch to <strong>Code</strong> for calls that don't have to be
                edited when you deploy elsewhere.
              </>
            )
          ) : (
            <>
              No code yet — the ID is different in every environment.{" "}
              <button type="button" className="link-btn" onClick={onOpenOverview}>
                Set a code
              </button>{" "}
              (like <span className="mono">revenue-comparison</span>) to call this template by code instead.
            </>
          )}
        </p>
        <CodeSnippet
          snippets={[
            { label: "curl", language: "bash", code: snippets.curl },
            { label: "JavaScript", language: "javascript", code: snippets.js },
            { label: "Python", language: "python", code: snippets.python },
          ]}
        />
      </div>

      {BATCH_RENDER_ENABLED && (
        <div className="panel">
          <h2 className="panel-title">Render many at once</h2>
          <p className="panel-subtitle">Same endpoint family, a JSON array in — one ZIP of rendered files out.</p>
          <CodeSnippet snippets={[{ label: "curl", language: "bash", code: snippets.batchCurl }]} />
        </div>
      )}

      {canEmbed && (
        <div className="panel">
          <h2 className="panel-title">Embed the viewer</h2>
          <p className="panel-subtitle">
            A full page/first/next/last, zoom, export, and print toolbar — the same one on the Preview tab — dropped
            straight into your own page. No sign-in required: <span className="mono">{snippets.embedUrl}</span>{" "}
            calls the same public render endpoint the snippets above do.
          </p>
          <CodeSnippet
            snippets={[
              { label: "HTML", language: "html", code: snippets.embedHtml },
              { label: "JavaScript (dynamic)", language: "javascript", code: snippets.embedJs },
            ]}
          />
          <p className="field-hint" style={{ marginTop: 12, marginBottom: 0 }}>
            Add <span className="mono">?theme=dark</span> to match a dark host page, or{" "}
            <span className="mono">?toolbar=0</span> for just the document with no controls at all.
          </p>
        </div>
      )}
    </div>
  );
}
