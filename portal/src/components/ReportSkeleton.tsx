/** A document-shaped shimmer placeholder standing in for whatever page is
 * about to appear -- used both by ReportViewer itself (waiting on its
 * first PDF) and by RunReportPage's Suspense boundary (the ReportViewer
 * chunk still loading). Same markup in both spots so there's no visual
 * pop when the real viewer mounts and takes over: a spinner + "Rendering…"
 * looks nothing like the page it's about to be replaced by, this does.
 *
 * `leaving` is for the moment the real page has arrived: the skeleton
 * lifts out of the layout and dissolves over the page instead of
 * disappearing (see ReportViewer.tsx's `skelLeaving`). */
export default function ReportSkeleton({ leaving = false }: { leaving?: boolean }) {
  return (
    <div className={`report-viewer-skeleton${leaving ? " is-leaving" : ""}`} role="status" aria-live="polite">
      <span className="sr-only">Rendering report…</span>
      <div className="skel-page" aria-hidden="true">
        <div className="skel skel-doc-title" />
        <div className="skel skel-doc-line" style={{ width: "72%" }} />
        <div className="skel skel-doc-line" style={{ width: "88%" }} />
        <div className="skel skel-doc-line" style={{ width: "58%" }} />
        <div className="skel-doc-gap" />
        <div className="skel-doc-table">
          <div className="skel skel-doc-row skel-doc-row-head" />
          <div className="skel skel-doc-row" />
          <div className="skel skel-doc-row" />
          <div className="skel skel-doc-row" />
        </div>
        <div className="skel-doc-gap" />
        <div className="skel skel-doc-line skel-doc-total" />
      </div>
    </div>
  );
}

/** The whole viewer frame -- border, toolbar row, stage -- with the toolbar
 * as shimmer bars and the page as ReportSkeleton. This is what stands in
 * while the (heavy, lazy) ReportViewer chunk downloads: it is the same box,
 * the same height, so when the real viewer mounts only the *contents*
 * change, rather than a bare stage growing a border and a toolbar. */
export function ReportViewerShell() {
  return (
    <div className="report-viewer" aria-busy="true">
      <div className="report-viewer-toolbar" aria-hidden="true">
        <span className="skel report-viewer-toolbar-skel" style={{ width: 118 }} />
        <span className="report-viewer-divider" />
        <span className="skel report-viewer-toolbar-skel" style={{ width: 74 }} />
        <span className="report-viewer-divider" />
        <span className="skel report-viewer-toolbar-skel" style={{ width: 96 }} />
        <span className="report-viewer-divider" />
        <span className="skel report-viewer-toolbar-skel" style={{ width: 28 }} />
        <span className="report-viewer-divider" />
        <span className="skel report-viewer-toolbar-skel" style={{ width: 84 }} />
        <span className="report-viewer-progress" />
      </div>
      <div className="report-viewer-stage">
        <ReportSkeleton />
      </div>
    </div>
  );
}
