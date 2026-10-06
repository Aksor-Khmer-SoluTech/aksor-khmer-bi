import {
  ChevronDown,
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
  Download,
  Files,
  Printer,
  RefreshCw,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import * as pdfjsLib from "pdfjs-dist";
import pdfjsWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { REPORT_SCROLLBARS_CODE, parseReportScrollbars } from "../preferences";
import { useOptionalUserSettings } from "../userSettings";
import RenderErrorPanel from "./RenderErrorPanel";
import { downloadBlob } from "../download";
import ReportSkeleton from "./ReportSkeleton";
import { FORMATS_BY_EXT, type RenderErrorInfo, type RenderFormat, type RenderResult, type TemplateExt } from "../types";

// Bundled, not CDN -- a version mismatch between a CDN worker and this
// package's own API surface throws at parse time, and self-hosting via
// Vite's `?url` import keeps the worker byte-for-byte pinned to whatever
// pdfjs-dist version is actually installed.
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorkerUrl;

const ZOOM_PRESETS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.15;
// The last zoom level is remembered per browser, so a reader who works at 150% doesn't reset it on every report.
const ZOOM_KEY = "portal_report_zoom";

function clampZoom(z: number): number {
  return Math.min(Math.max(MIN_ZOOM, z), MAX_ZOOM);
}

function storedZoom(): number {
  try {
    const value = Number(localStorage.getItem(ZOOM_KEY));
    return Number.isFinite(value) && value > 0 ? clampZoom(value) : 1;
  } catch {
    return 1; // storage can be blocked (private window, site data off) -- the viewer just starts at 100%
  }
}

const FORMAT_LABEL: Record<RenderFormat, string> = {
  pdf: "PDF document",
  docx: "Word document (.docx)",
  xlsx: "Excel workbook (.xlsx)",
  png: "Image (.png)",
};

/** A self-contained paginated report viewer -- first/previous/next/last
 * page, direct page entry, zoom, refresh, an export menu covering every
 * format this template supports, and print -- the same toolbar shape
 * JasperReports/Crystal Reports/SSRS's own embedded viewers use, since
 * under the hood they're all doing the same thing this is: rendering one
 * PDF and paging a client-side renderer through it. Only mounted for
 * `docx`-sourced templates (see TemplateDetail.tsx) -- an `xlsx` template
 * has no PDF rendering path (see types.ts's FORMATS_BY_EXT) and so has
 * nothing here to page through.
 */
export default function ReportViewer({
  reportId,
  reportName,
  templateExt,
  contextData,
  renderer,
  hideToolbar = false,
  onRendered,
  onRenderError,
  refreshKey = 0,
  onBusyChange,
  onDescribed,
}: {
  reportId: string;
  reportName: string;
  templateExt: TemplateExt;
  contextData: Record<string, unknown>;
  /** How to obtain a render. Omitted, it POSTs `contextData` to the public
   * /render route (the Templates preview and embeds). RunReportPage passes
   * one that goes through the authenticated /run route instead, so the
   * initial PDF *and* every export-menu format are checked against the
   * user's grants server-side. Read through a ref: it's typically an
   * inline arrow, and depending on it would refetch on every render. */
  renderer?: (format: RenderFormat, part?: number) => Promise<RenderResult>;
  /** For an embed that wants "just the document, no chrome" (see
   * EmbedPage.tsx's `?toolbar=0`) -- page nav/zoom/export/print all stay
   * unreachable when this is set, so only pass it when the embedder has
   * their own controls or genuinely just wants a static-looking page. */
  hideToolbar?: boolean;
  /** Fired after each successful render -- EmbedPage.tsx relays this to
   * the embedding parent via postMessage; TemplateDetail.tsx's own use
   * has no need for it and just omits the prop. */
  onRendered?: (pageCount: number) => void;
  onRenderError?: (message: string) => void;
  /** Bump to render again *in place*: the current page stays on screen
   * (dimmed) until the new one is ready, instead of the viewer being
   * remounted -- which would blank the toolbar, drop the zoom, and swap a
   * finished page for a skeleton on every re-run. */
  refreshKey?: number;
  /** True while a render is in flight (first load, refresh, or a bumped
   * `refreshKey`), false once it has settled either way -- lets a caller
   * disable its own "run" control for exactly that window. */
  onBusyChange?: (busy: boolean) => void;
  /** Fired after a render whose response says what report it was (name + template type) --
   * i.e. a run by parameters, where the caller hasn't looked the report up. Lets EmbedPage
   * show the right export formats without a lookup. */
  onDescribed?: (report: { name: string; ext: TemplateExt }) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<PDFDocumentProxy | null>(null);
  const pdfBlobRef = useRef<Blob | null>(null);
  const renderTaskRef = useRef<RenderTask | null>(null);
  const rendererRef = useRef(renderer);
  rendererRef.current = renderer;
  // The report's own name once a run has told us it -- kept in a ref, not read from `reportName`,
  // because `reportName` is a dependency of the fetch below: changing it after the first render
  // would run the report a second time.
  const describedNameRef = useRef<string | null>(null);
  // `part` picks one file of a report the server has split (see
  // api/app/report_split.py); leave it out to get the whole thing.
  const fetchRender = (format: RenderFormat, partNo?: number) =>
    rendererRef.current ? rendererRef.current(format, partNo) : api.render(reportId, contextData, format, reportName, partNo);

  const [loading, setLoading] = useState(true);
  // The reader's scrollbar preference (Settings > Preferences); an embedded viewer has no account, so the system default.
  const alwaysScrollbars = parseReportScrollbars(useOptionalUserSettings()?.get(REPORT_SCROLLBARS_CODE)) === "always";
  const [error, setError] = useState<string | null>(null);
  const [errorInfo, setErrorInfo] = useState<RenderErrorInfo | undefined>(undefined);
  const [pageNum, setPageNum] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [numPages, setNumPages] = useState(0);
  const [zoom, setZoom] = useState(storedZoom);
  const [zoomMenuOpen, setZoomMenuOpen] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [exportBusy, setExportBusy] = useState<RenderFormat | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // A report over the server's per-file row limit is several files. The
  // preview shows one at a time (`part`, 1-based); Export gets them all.
  const [part, setPart] = useState(1);
  const [parts, setParts] = useState(1);
  // Bumped per loaded document so the page is repainted even when the new
  // one has the same page count/number/zoom as the one it replaces.
  const [docKey, setDocKey] = useState(0);
  // The skeleton hangs around, out of flow, for one short beat after the
  // first page arrives and dissolves *over* it -- rather than vanishing
  // and leaving the stage bare until the page fades in.
  const [skelLeaving, setSkelLeaving] = useState(false);
  const requestRef = useRef(0);

  const formats = FORMATS_BY_EXT[templateExt];
  const hasDoc = numPages > 0 && !error;
  const showSkeleton = (loading && !hasDoc) || skelLeaving;

  const loadPdf = useCallback(async () => {
    // Only the newest request may touch state: a slower, older one landing
    // late would otherwise replace the page the user is looking at.
    const request = ++requestRef.current;
    const isLatest = () => request === requestRef.current;
    setLoading(true);
    setError(null);
    setErrorInfo(undefined);
    setExportError(null);
    try {
      const rendered = await fetchRender("pdf", part);
      const { blob } = rendered;
      const buf = await blob.arrayBuffer();
      const doc = await pdfjsLib.getDocument({ data: buf }).promise;
      if (!isLatest()) {
        doc.destroy();
        return;
      }
      const wasEmpty = pdfRef.current === null;
      renderTaskRef.current?.cancel();
      pdfRef.current?.destroy();
      pdfRef.current = doc;
      pdfBlobRef.current = blob;
      if (rendered.report) {
        describedNameRef.current = rendered.report.name;
        onDescribed?.(rendered.report);
      }
      setParts(rendered.parts);
      setNumPages(doc.numPages);
      setPageNum(1);
      setPageInput("1");
      setDocKey((k) => k + 1);
      if (wasEmpty) setSkelLeaving(true);
      onRendered?.(doc.numPages);
    } catch (err) {
      if (!isLatest()) return;
      // Whatever the server said is shown as it is: someone testing a template needs the real reason, not
      // "couldn't render". Only a failure with no answer at all (the API unreachable) falls back to a sentence.
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof TypeError
            ? "Couldn't reach the API — it may be down, restarting, or blocked. Check the API log and your connection."
            : `Couldn't render a preview: ${err instanceof Error ? err.message : String(err)}`;
      // A failed re-run shouldn't leave the previous run's page sitting
      // under the error as if it were this run's result.
      renderTaskRef.current?.cancel();
      pdfRef.current?.destroy();
      pdfRef.current = null;
      pdfBlobRef.current = null;
      setNumPages(0);
      setError(message);
      setErrorInfo(err instanceof ApiError ? err.renderError : undefined);
      onRenderError?.(message);
    } finally {
      if (isLatest()) setLoading(false);
    }
    // onRendered/onRenderError/onDescribed intentionally excluded -- an inline
    // arrow function prop (EmbedPage.tsx's postMessage relay) is a new
    // reference every render; depending on it would re-trigger a render
    // fetch that only reportId/contextData/reportName should cause.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId, contextData, reportName, part]);

  // A new run, other data, or another report can change how many files there
  // are -- so it goes back to file 1 rather than asking for a part that may
  // no longer exist. (Changing `part` changes loadPdf, which re-runs this.)
  const scope = useRef({ refreshKey, contextData, reportId });
  useEffect(() => {
    const before = scope.current;
    if (before.refreshKey !== refreshKey || before.contextData !== contextData || before.reportId !== reportId) {
      scope.current = { refreshKey, contextData, reportId };
      if (part !== 1) {
        setPart(1);
        return;
      }
    }
    loadPdf();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reportId/contextData/part are read via `scope`/loadPdf on purpose
  }, [loadPdf, reloadKey, refreshKey]);

  useEffect(() => {
    onBusyChange?.(loading);
    // The callback is read fresh each time `loading` flips; depending on it
    // would re-announce the same state whenever the parent re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  useEffect(() => {
    if (!skelLeaving) return;
    const timer = setTimeout(() => setSkelLeaving(false), 420);
    return () => clearTimeout(timer);
  }, [skelLeaving]);

  useEffect(() => {
    return () => {
      pdfRef.current?.destroy();
    };
  }, []);

  const renderPage = useCallback(async () => {
    const doc = pdfRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas) return;
    const page = await doc.getPage(pageNum);
    // Canvas backing store at devicePixelRatio so retina screens don't
    // see a blurry upscale; CSS size stays at the logical (1x) size.
    const dpr = window.devicePixelRatio || 1;
    const viewport = page.getViewport({ scale: zoom * dpr });
    const cssWidth = `${viewport.width / dpr}px`;
    const cssHeight = `${viewport.height / dpr}px`;
    // A brand-new canvas has no size yet, so give it its box straight away
    // (otherwise it sits at the 300x150 default until the page is ready).
    // Once it has been painted, its size only ever changes together with
    // its pixels, below.
    if (!canvas.dataset.painted) {
      canvas.style.width = cssWidth;
      canvas.style.height = cssHeight;
    }

    // Paint offscreen, then swap the finished bitmap in synchronously.
    // Resizing the visible canvas clears it, and pdf.js finishes drawing a
    // few frames later -- painting straight onto it shows a blank white
    // sheet flashing on every zoom step, page turn and re-run.
    const buffer = document.createElement("canvas");
    buffer.width = viewport.width;
    buffer.height = viewport.height;
    const bufferCtx = buffer.getContext("2d");
    if (!bufferCtx) return;

    renderTaskRef.current?.cancel();
    const task = page.render({ canvasContext: bufferCtx, viewport });
    renderTaskRef.current = task;
    try {
      await task.promise;
    } catch (err) {
      if ((err as { name?: string })?.name === "RenderingCancelledException") return;
      throw err;
    }
    // A newer render (or a canvas that has since unmounted) took over.
    if (renderTaskRef.current !== task || !canvas.isConnected) return;

    canvas.width = buffer.width;
    canvas.height = buffer.height;
    canvas.style.width = cssWidth;
    canvas.style.height = cssHeight;
    canvas.getContext("2d")?.drawImage(buffer, 0, 0);
    canvas.dataset.painted = "1";
  }, [pageNum, zoom]);

  useEffect(() => {
    if (numPages > 0) renderPage();
  }, [renderPage, numPages, docKey]);

  useEffect(() => {
    setPageInput(String(pageNum));
  }, [pageNum]);

  useEffect(() => {
    if (!zoomMenuOpen && !exportMenuOpen) return;
    function onPointerDown(e: PointerEvent) {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
        setZoomMenuOpen(false);
        setExportMenuOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setZoomMenuOpen(false);
        setExportMenuOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [zoomMenuOpen, exportMenuOpen]);

  function goToPage(n: number) {
    setPageNum(Math.min(Math.max(1, n), numPages || 1));
  }

  function submitPageInput() {
    const n = parseInt(pageInput, 10);
    if (!Number.isNaN(n)) goToPage(n);
    else setPageInput(String(pageNum));
  }

  function setZoomClamped(z: number) {
    const next = clampZoom(z);
    setZoom(next);
    try {
      localStorage.setItem(ZOOM_KEY, String(Math.round(next * 100) / 100));
    } catch {
      /* not remembered this time; the zoom itself still applies */
    }
  }

  async function handleExport(format: RenderFormat) {
    setExportMenuOpen(false);
    setExportError(null);
    setExportBusy(format);
    try {
      if (format === "pdf" && pdfBlobRef.current && parts === 1) {
        downloadBlob(pdfBlobRef.current, `${describedNameRef.current ?? reportName}.pdf`);
      } else {
        const { blob, filename } = await fetchRender(format);
        downloadBlob(blob, filename);
      }
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : "Export failed");
    } finally {
      setExportBusy(null);
    }
  }

  function handlePrint() {
    if (!pdfBlobRef.current) return;
    const url = URL.createObjectURL(pdfBlobRef.current);
    const iframe = document.createElement("iframe");
    // Off-screen, not display:none -- a hidden-by-display iframe never
    // fires a layout/paint pass in some browsers, and print() on it
    // silently no-ops.
    Object.assign(iframe.style, { position: "fixed", right: "0", bottom: "0", width: "0", height: "0", border: "0" });
    iframe.src = url;
    document.body.appendChild(iframe);
    iframe.onload = () => {
      iframe.contentWindow?.focus();
      iframe.contentWindow?.print();
      setTimeout(() => {
        document.body.removeChild(iframe);
        URL.revokeObjectURL(url);
      }, 1000);
    };
  }

  return (
    <div className="report-viewer">
      {!hideToolbar && (
      <div className="report-viewer-toolbar" ref={toolbarRef}>
        <div className="report-viewer-group">
          <button type="button" className="report-viewer-btn" onClick={() => goToPage(1)} disabled={pageNum <= 1} title="First page">
            <ChevronFirst size={17} />
          </button>
          <button
            type="button"
            className="report-viewer-btn"
            onClick={() => goToPage(pageNum - 1)}
            disabled={pageNum <= 1}
            title="Previous page"
          >
            <ChevronLeft size={17} />
          </button>
          <button
            type="button"
            className="report-viewer-btn"
            onClick={() => goToPage(pageNum + 1)}
            disabled={pageNum >= numPages}
            title="Next page"
          >
            <ChevronRight size={17} />
          </button>
          <button
            type="button"
            className="report-viewer-btn"
            onClick={() => goToPage(numPages)}
            disabled={pageNum >= numPages}
            title="Last page"
          >
            <ChevronLast size={17} />
          </button>
        </div>

        <div className="report-viewer-divider" />

        <div className="report-viewer-page-input">
          <input
            type="text"
            inputMode="numeric"
            value={pageInput}
            onChange={(e) => setPageInput(e.target.value)}
            onBlur={submitPageInput}
            onKeyDown={(e) => e.key === "Enter" && submitPageInput()}
            disabled={numPages === 0}
          />
          <span>of {numPages || "…"}</span>
        </div>

        <div className="report-viewer-divider" />

        <div className="report-viewer-group">
          <button type="button" className="report-viewer-btn" onClick={() => setZoomClamped(zoom - ZOOM_STEP)} disabled={zoom <= MIN_ZOOM} title="Zoom out">
            <ZoomOut size={16} />
          </button>
          <button type="button" className="report-viewer-btn" onClick={() => setZoomClamped(zoom + ZOOM_STEP)} disabled={zoom >= MAX_ZOOM} title="Zoom in">
            <ZoomIn size={16} />
          </button>
          <div className="report-viewer-menu-anchor">
            <button
              type="button"
              className="report-viewer-btn report-viewer-zoom-btn"
              onClick={() => {
                setZoomMenuOpen((o) => !o);
                setExportMenuOpen(false);
              }}
            >
              {Math.round(zoom * 100)}%
              <ChevronDown size={13} />
            </button>
            {zoomMenuOpen && (
              <div className="report-viewer-menu" role="menu">
                {ZOOM_PRESETS.map((z) => (
                  <button
                    key={z}
                    type="button"
                    className={`report-viewer-menu-item ${Math.abs(z - zoom) < 0.01 ? "active" : ""}`}
                    onClick={() => {
                      setZoomClamped(z);
                      setZoomMenuOpen(false);
                    }}
                  >
                    {Math.round(z * 100)}%
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="report-viewer-divider" />

        <button
          type="button"
          className="report-viewer-btn"
          onClick={() => setReloadKey((k) => k + 1)}
          title="Refresh"
          disabled={loading}
        >
          <RefreshCw size={15} className={loading ? "report-viewer-spin" : ""} />
        </button>

        <div className="report-viewer-divider" />

        <div className="report-viewer-menu-anchor">
          <button
            type="button"
            className="report-viewer-btn report-viewer-zoom-btn"
            onClick={() => {
              setExportMenuOpen((o) => !o);
              setZoomMenuOpen(false);
            }}
            disabled={exportBusy !== null}
          >
            {exportBusy ? <span className="spinner" /> : <Download size={15} />}
            Export
            <ChevronDown size={13} />
          </button>
          {exportMenuOpen && (
            <div className="report-viewer-menu report-viewer-menu-right" role="menu">
              {formats.map((f) => (
                <button key={f} type="button" className="report-viewer-menu-item" onClick={() => handleExport(f)}>
                  {FORMAT_LABEL[f]}
                  {parts > 1 && <span className="report-viewer-menu-note">{parts} files, as a ZIP</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="report-viewer-divider" />

        <button type="button" className="report-viewer-btn" onClick={handlePrint}
          disabled={!pdfBlobRef.current}
          title={parts > 1 ? `Print file ${part} of ${parts}` : "Print"}
        >
          <Printer size={17} />
        </button>

        {loading && <span className="report-viewer-progress" aria-hidden="true" />}
      </div>
      )}

      {!hideToolbar && parts > 1 && (
        <div className="report-viewer-parts" role="group" aria-label="Report files">
          <span className="report-viewer-parts-text">
            <Files size={14} aria-hidden="true" />
            Split into <strong>{parts} files</strong> — previewing
          </span>
          <button
            type="button"
            className="report-viewer-btn"
            onClick={() => setPart((p) => Math.max(1, p - 1))}
            disabled={part <= 1 || loading}
            aria-label="Previous file"
            title="Previous file"
          >
            <ChevronLeft size={16} />
          </button>
          <select value={part} onChange={(e) => setPart(Number(e.target.value))} disabled={loading} aria-label="File to preview">
            {Array.from({ length: parts }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                File {i + 1} of {parts}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="report-viewer-btn"
            onClick={() => setPart((p) => Math.min(parts, p + 1))}
            disabled={part >= parts || loading}
            aria-label="Next file"
            title="Next file"
          >
            <ChevronRight size={16} />
          </button>
          <span className="report-viewer-parts-hint">Export downloads all {parts} as a ZIP.</span>
        </div>
      )}

      {!hideToolbar && exportError && <p className="alert alert-error report-viewer-export-error">{exportError}</p>}

      <div className={`report-viewer-stage${alwaysScrollbars ? " scrollbars-always" : ""}`} aria-busy={loading}>
        {/* Stays mounted while a re-run loads (dimmed, see .is-stale) so the
            previous page isn't yanked out from under the reader. */}
        {hasDoc && <canvas ref={canvasRef} className={`report-viewer-canvas${loading ? " is-stale" : ""}`} />}
        {showSkeleton && <ReportSkeleton leaving={skelLeaving} />}
        {!loading && error &&
          (errorInfo ? <RenderErrorPanel message={error} info={errorInfo} /> : <p className="alert alert-error">{error}</p>)}
      </div>
    </div>
  );
}
