import { lazy, Suspense, useCallback, useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { Braces, CodeXml, Database, Eye, FileText, History, Link2, Maximize2, Minimize2, Plus, ShieldCheck, SlidersHorizontal, SpellCheck, type LucideIcon } from "lucide-react";
import { api, ApiError } from "../api";
import { useDataConfigDraft } from "../dataConfig";
import { initialValue } from "../dateFormat";
import { downloadBlob } from "../download";
import { useDialogRef } from "../hooks";
import { PREVIEW_LAYOUT_CODE, parsePreviewLayout, type PreviewLayout } from "../preferences";
import { checkCode, isCodeError, suggestCode } from "../reportCode";
import {
  FORMATS_BY_EXT,
  type AuthInfo,
  type Grant,
  type ReportChangelog,
  type ReportMeta,
  type ReportParameter,
  type ReportSchema,
  type TemplateFont,
  type RunForm,
  type Role,
  type User,
  versionName,
} from "../types";
import { useUserSettings } from "../userSettings";
import ConfirmDialog from "./ConfirmDialog";
import DataSourceTab from "./DataSourceTab";
import HistoryTab from "./HistoryTab";
import IntegrationTab from "./IntegrationTab";
import ParametersTab from "./ParametersTab";
import ProtectedTermsTab from "./ProtectedTermsTab";
import { ParameterField } from "./RunReportPage";
import ReplaceTemplate from "./ReplaceTemplate";
import FolderPicker from "./FolderPicker";
import ReportCodeField from "./ReportCodeField";
import ShortcutsField from "./ShortcutsField";
import ReportSkeleton from "./ReportSkeleton";
import { LinesSkeleton } from "./Skeletons";
import TemplateDownloadButtons from "./TemplateDownload";

// Lazy -- pdfjs-dist alone is well over a third of this app's entire
// bundle (see ReportViewer.tsx), and the vast majority of sessions never
// open this tab at all. Split it into its own chunk, fetched only once
// someone actually clicks "Render preview", instead of paying that
// weight on every page load.
const ReportViewer = lazy(() => import("./ReportViewer"));

// Not backend-enforced (ReportUpdate has no length cap) -- purely a UX
// ceiling, same values RegisterDialog.tsx uses for the same two fields
// at register time, kept in sync so an editable report doesn't accept
// more than a freshly-registered one did.
const NAME_MAX = 100;
const DESCRIPTION_MAX = 500;

type Tab = "overview" | "placeholders" | "parameters" | "datasource" | "preview" | "access" | "shortcuts" | "integration" | "terms" | "history";

// Order = how soon a manager needs the tab, then what it costs to open --
// most needed and cheapest first, occasional and heavy last. What "cost"
// means for each (requests fired on open):
//   overview, placeholders, integration  none -- TemplateDetail already loaded
//                                      the report, its schema and its change log
//   parameters, datasource             1 between them (the data config, which both edit as
//                                      one draft that survives switching from one to the other)
//   preview                            none to open; the heavy part is the click
//                                      (a server-side render + the lazy pdf.js viewer)
//   access                             3, incl. the organization's whole user list
//   terms                              3 (term sets can run to thousands of terms)
//   history                            1, and it grows with every change made
// So: set it up (overview, placeholders), make it runnable (parameters, then
// where its data comes from), check it (preview), publish it (access,
// integration), then the occasional and look-back tabs (terms, history). Access and terms only show to someone
// holding the global report:manage permission (GLOBAL_ONLY_TABS below).
//
// Labels vs ids: the labels are what a person reads, the ids follow the
// backend's vocabulary (schema, data-config, access grants, protected terms).
// What each covers -- "Placeholders" lists the {{ fields }} the template
// expects; "Parameters" is what a person picks when running it (the filters
// on the Run page, whose icon it shares); "Data source" is where the server
// gets its rows (a REST API today -- kept apart from the filters because a
// source is its own thing, and other kinds can join it); "Access Privilege" is who holds view /
// render / manage on it; "Protected Terms" is the Khmer words kept
// unbroken across lines.
const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "overview", label: "Overview", icon: FileText },
  { id: "placeholders", label: "Placeholders", icon: Braces },
  { id: "parameters", label: "Parameters", icon: SlidersHorizontal },
  { id: "datasource", label: "Data source", icon: Database },
  { id: "preview", label: "Preview", icon: Eye },
  { id: "access", label: "Access Privilege", icon: ShieldCheck },
  { id: "shortcuts", label: "Shortcuts", icon: Link2 },
  { id: "integration", label: "Integration", icon: CodeXml },
  { id: "terms", label: "Protected Terms", icon: SpellCheck },
  { id: "history", label: "History", icon: History },
];

// Two tabs call routes that need the blanket report:manage permission rather
// than a grant on one report -- Access Privilege (the grants API) and Protected
// Terms (listing the organization's shared sets) -- so a per-report manager
// doesn't get those. Parameters, whose routes accept a report-level grant, is
// theirs too.
const GLOBAL_ONLY_TABS: Tab[] = ["access", "terms"];

/** A tab's place in the URL, #/reports/<id>/<slug>. The Overview is the
 * default and has none (so every existing #/reports/<id> link is unchanged);
 * Protected Terms reads better spelled out, and matches the admin route of the
 * same name. */
function tabSlug(id: Tab): string | undefined {
  if (id === "overview") return undefined;
  return id === "terms" ? "protected-terms" : id === "datasource" ? "data-source" : id;
}

// Size/position/corner utilities per PreviewLayout choice (see
// preferences.ts) -- the entrance animation comes from the matching
// `report-viewer-drawer-*` class instead (pages.css), keyed off the same id.
//
// right/left: a full-height sheet flush to one edge. m-0 + inset-* override
// dialog.modal's own `margin: auto` centering (elements.css), and the
// screen-edge corners are squared off so it sits flush -- the inner corners
// keep .modal's own radius.
// center: the largest standard modal -- nearly the whole window, leaving
// just a small even margin (1.5rem) of dimmed page on every side, and no
// max-width cap so it keeps that margin on a wide monitor instead of
// floating in the middle of it. Keeps .modal's centering and its rounded
// corners on all four sides.
// Every layout goes edge-to-edge and square below the md breakpoint, where
// there's no room for anything else (min-w-0 too: the drawers' 420px floor
// would otherwise overflow a phone) -- which is also why the header's
// maximize button is hidden there: it would have nothing left to do.
//
// `maximized` is the header button's toggle: the same dialog grown to the
// whole viewport, square and borderless. Each layout keeps the anchoring
// (right-0 / left-0 / auto-margin centering) it has in `normal` and only
// changes size and corners -- swapping anchors (e.g. right-0 -> left-0)
// would make the box jump instead of growing outward from where it was,
// since `auto` isn't animatable. `max-h-screen` matters for the center
// layout: the UA stylesheet caps a dialog at `100% - 36px` tall, which
// would otherwise leave a strip at the bottom.
const DRAWER_LAYOUT_CLASSES: Record<PreviewLayout, { normal: string; maximized: string }> = {
  right: {
    normal:
      "m-0 inset-y-0 right-0 left-auto h-screen max-h-screen w-[42vw] min-w-[420px] max-w-none rounded-r-none max-md:w-full max-md:min-w-0 max-md:rounded-none",
    maximized: "m-0 inset-y-0 right-0 left-auto h-screen max-h-screen w-screen min-w-0 max-w-none rounded-none border-0",
  },
  left: {
    normal:
      "m-0 inset-y-0 left-0 right-auto h-screen max-h-screen w-[42vw] min-w-[420px] max-w-none rounded-l-none max-md:w-full max-md:min-w-0 max-md:rounded-none",
    maximized: "m-0 inset-y-0 left-0 right-auto h-screen max-h-screen w-screen min-w-0 max-w-none rounded-none border-0",
  },
  center: {
    normal:
      "h-[calc(100vh-3rem)] w-[calc(100vw-3rem)] max-w-none max-md:h-full max-md:max-h-full max-md:w-full max-md:rounded-none",
    maximized: "h-screen max-h-screen w-screen max-w-none rounded-none border-0",
  },
};

const has = (auth: AuthInfo, code: string) => auth.isSuperuser || auth.permissions.includes(code);

/** Bare <input type="date"> values are pinned to a full-day ISO instant --
 * see UserDetailPanel.tsx's toExpiresAt for why a bare date can't be
 * compared directly against a timestamp. */
function toExpiresAt(dateInput: string): string | null {
  return dateInput ? `${dateInput}T23:59:59Z` : null;
}

function skeletonFromFields(fields: string[]): Record<string, unknown> {
  const obj: Record<string, unknown> = {};
  for (const f of fields) obj[f] = "";
  return obj;
}

function OverviewTab({
  report,
  changelog,
  onUpdated,
  onDeleted,
  onOpenHistory,
}: {
  report: ReportMeta;
  changelog: ReportChangelog | null;
  onUpdated: (r: ReportMeta) => void;
  onDeleted: () => void;
  onOpenHistory: () => void;
}) {
  const [name, setName] = useState(report.name);
  const [description, setDescription] = useState(report.description ?? "");
  const [code, setCode] = useState(report.code ?? "");
  const [folderId, setFolderId] = useState<string | null>(report.folder_id);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  async function saveMeta(e: FormEvent) {
    e.preventDefault();
    setSaveError(null);
    setCodeError(null);
    setSaved(false);
    if (checkCode(code)) return; // the field is already saying why
    // The code is only sent when it changed: omitted leaves it alone, null removes it.
    const nextCode = code.trim() === "" ? null : code.trim();
    const codeChanged = nextCode !== (report.code ?? null);
    try {
      const folderChanged = folderId !== report.folder_id;
      const updated = await api.updateReport(report.report_id, {
        name,
        description,
        ...(codeChanged ? { code: nextCode } : {}),
        ...(folderChanged ? { folder_id: folderId } : {}),
      });
      setFolderId(updated.folder_id);
      onUpdated(updated);
      setCode(updated.code ?? "");
      setSaved(true);
    } catch (err) {
      if (err instanceof ApiError && codeChanged && isCodeError(err.status, err.message)) setCodeError(err.message);
      else setSaveError(err instanceof ApiError ? err.message : "Update failed");
    }
  }

  async function handleDelete() {
    await api.deleteReport(report.report_id);
    onDeleted();
  }

  return (
    <div className="panel overview-grid">
      <section>
        <h2 className="panel-title">Metadata</h2>
        <p className="panel-subtitle">{versionName(report.version, report.version_label)} · created {new Date(report.created_at).toLocaleString()}</p>
        <form onSubmit={saveMeta}>
          <label>
            <span className="field-label-row">
              <span>Name</span>
              <span className={`char-counter${name.length >= NAME_MAX ? " char-counter-limit" : ""}`}>
                {name.length}/{NAME_MAX}
              </span>
            </span>
            <input type="text" required maxLength={NAME_MAX} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <ReportCodeField
            value={code}
            onChange={(v) => {
              setCode(v);
              setCodeError(null);
              setSaved(false);
            }}
            saved={report.code}
            suggestion={suggestCode(name)}
            serverError={codeError}
          />
          <FolderPicker
            value={folderId}
            onChange={(v) => {
              setFolderId(v);
              setSaved(false);
            }}
          />
          <label>
            <span className="field-label-row">
              <span>Description</span>
              <span className={`char-counter${description.length >= DESCRIPTION_MAX ? " char-counter-limit" : ""}`}>
                {description.length}/{DESCRIPTION_MAX}
              </span>
            </span>
            <textarea rows={3} maxLength={DESCRIPTION_MAX} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          {saveError && <p className="alert alert-error">{saveError}</p>}
          {saved && <p className="alert alert-success">Saved.</p>}
          <button type="submit" className="btn btn-primary" disabled={checkCode(code) !== null}>
            Save changes
          </button>
        </form>

      </section>

      <section className="overview-file">
        <h2 className="panel-title">Template file</h2>
        <p className="panel-subtitle">
          The file as uploaded, with its {"{{ placeholders }}"} intact — not a rendering of it. Every download is recorded in History.
        </p>
        <TemplateDownloadButtons report={report} changelog={changelog} />

        <h2 className="panel-title" style={{ marginTop: 28 }}>
          Replace template file
        </h2>
        <p className="panel-subtitle">
          Upload a new file to make it the next version. The report_id and integration links stay the same, and the file being replaced
          stays downloadable in History.
        </p>
        <ReplaceTemplate report={report} changelog={changelog} onReplaced={onUpdated} onOpenHistory={onOpenHistory} />

        <div className="danger-zone">
          <span className="field-label">Danger zone</span>
          <p className="field-hint" style={{ margin: "0 0 10px" }}>
            Deleting a template is permanent and can't be undone.
          </p>
          <button type="button" className="btn btn-danger" onClick={() => setConfirmOpen(true)}>
            Delete this template
          </button>
        </div>
      </section>

      <ConfirmDialog
        open={confirmOpen}
        title="Delete template?"
        body={`"${report.name}" and its render history link will be gone for good.`}
        onConfirm={() => {
          setConfirmOpen(false);
          handleDelete();
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

const FONT_STATUS: Record<TemplateFont["status"], { label: string; hint: string }> = {
  uploaded: { label: "Added", hint: "Added under Resources > Fonts" },
  installed: { label: "Installed", hint: "Installed on the server" },
  substituted: { label: "Substituted", hint: "The server doesn't have it, but a metric-compatible font stands in (same character widths), so the layout holds" },
  missing: { label: "Missing", hint: "The server doesn't have it and has no matching stand-in: the renderer picks a default, so line breaks and widths can change" },
};

/** The fonts the template file names, each marked with what the server will really draw with. A font that is
 * substituted or missing changes line breaks and widths -- better to learn that here than from a printed PDF. */
function TemplateFonts({ reportId }: { reportId: string }) {
  const [fonts, setFonts] = useState<TemplateFont[] | null>(null);
  useEffect(() => {
    api.getReportFonts(reportId).then(setFonts).catch(() => setFonts([]));
  }, [reportId]);
  if (fonts === null || fonts.length === 0) return null;
  const problems = fonts.filter((f) => f.status === "substituted" || f.status === "missing").length;
  return (
    <section className="template-fonts-section">
      <h2 className="panel-title">Fonts it names</h2>
      <p className="panel-subtitle">
        What the template asks for, and what the server will draw with.
        {problems > 0 && (
          <>
            {" "}
            <strong>{problems} {problems === 1 ? "is" : "are"} not on the server</strong> — add {problems === 1 ? "it" : "them"} under{" "}
            <a href="#/resources">Resources → Fonts</a> to keep the layout as designed.
          </>
        )}
      </p>
      <ul className="template-fonts">
        {fonts.map((f) => (
          <li key={f.name}>
            <span className="template-font-name">{f.name}</span>
            <span className={`font-status font-status-${f.status}`} title={FONT_STATUS[f.status].hint}>{FONT_STATUS[f.status].label}</span>
            {f.status === "substituted" && f.resolved_to && <span className="muted">→ drawn as {f.resolved_to}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function PlaceholdersTab({ schema, reportId }: { schema: ReportSchema | null; reportId: string }) {
  if (!schema) return <p className="muted">Detecting placeholders…</p>;
  return (
    <div className="panel">
      <h2 className="panel-title">Detected placeholders</h2>
      <p className="panel-subtitle">
        via <span className="mono">{schema.engine}</span> — {schema.note}
      </p>
      {schema.fields.length === 0 ? (
        <p className="muted">No placeholders detected.</p>
      ) : (
        <div className="field-pills">
          {schema.fields.map((f) => (
            <span className="field-pill" key={f}>
              {f}
            </span>
          ))}
        </div>
      )}
      <TemplateFonts reportId={reportId} />
    </div>
  );
}

/** Where else this template is listed. A shortcut only adds a place to find the report; the access stays the
 * original's -- see ShortcutsField. */
function ShortcutsTab({ report }: { report: ReportMeta }) {
  return (
    <div className="panel">
      <h2 className="panel-title">Shortcuts</h2>
      <p className="panel-subtitle">
        When several departments or teams use this report, list it in each team's own folder so they can arrange their space the way
        they like — without copying it. A shortcut opens this same report and has exactly its permissions; nothing is granted by it, so
        each team still needs access to the report itself (Access Privilege).
      </p>
      <ShortcutsField report={report} />
    </div>
  );
}

// What the viewer is showing: the template against hand-typed sample JSON, or a real run with filter values.
type Viewing = { kind: "sample"; context: Record<string, unknown> } | { kind: "live"; values: Record<string, string> };
const NO_CONTEXT: Record<string, unknown> = {};

/** Two ways to check a template. **Live run** is what the people who open it get: the report's filters, then its
 * data source, then the template -- the same /run route as the Reports page, so defaults, required filters, choice
 * lists, grants and the data source are all exercised. **Sample data** renders the template against JSON typed here,
 * which skips the filters and the data source: right for laying out a template before any data source exists, wrong
 * for testing one. A report with filters or a data source opens on Live run. */
function PreviewTab({
  report,
  schema,
  onSampleSaved,
  unsavedConfig,
}: {
  report: ReportMeta;
  schema: ReportSchema | null;
  onSampleSaved: (ctx: Record<string, unknown>) => void;
  /** The Parameters or Data source tab has changes not yet saved -- a live run uses what is saved. */
  unsavedConfig: boolean;
}) {
  // Only a `docx`-sourced template has a PDF rendering path at all (see
  // types.ts's FORMATS_BY_EXT) -- that's what ReportViewer pages through.
  // An `xlsx` template has nothing to preview, so it keeps the plain
  // render-and-download flow it always had.
  const canPreview = FORMATS_BY_EXT[report.template_ext].includes("pdf");
  const [text, setText] = useState(() =>
    JSON.stringify(report.sample_context ?? skeletonFromFields(schema?.fields ?? []), null, 2)
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [viewing, setViewing] = useState<Viewing | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const { get: getSetting } = useUserSettings();
  const previewLayout = parsePreviewLayout(getSetting(PREVIEW_LAYOUT_CODE));

  // The live-run form: the report's filters as the Reports page would show them (None until loaded; a report
  // with neither filters nor a data source has nothing to run live, so only sample data is offered).
  const [form, setForm] = useState<RunForm | null>(null);
  const [liveAvailable, setLiveAvailable] = useState(false);
  const [mode, setMode] = useState<"live" | "sample">("sample");
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getRunForm(report.report_id).catch(() => null), api.getDataConfig(report.report_id).catch(() => null)]).then(
      ([f, config]) => {
        if (cancelled) return;
        setForm(f);
        const live = f !== null && (f.parameters.length > 0 || Boolean(config?.data_source));
        setLiveAvailable(live);
        if (live && f) {
          setMode("live");
          setValues(
            Object.fromEntries(
              f.parameters.map((p) => [p.name, p.options ? (p.options.length === 1 ? p.options[0].value : "") : initialValue(p.type, p.default_value)]),
            ),
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [report.report_id]);

  // The preview lives in a dialog (a slide-over from the right/left edge,
  // or a centered modal -- a Preferences tab choice, saved to the account)
  // rather than inline in the page -- `open` just tracks whether a render
  // has been requested; closing it clears `viewing` so the next
  // click starts fresh.
  const drawerRef = useDialogRef(canPreview && viewing !== null);
  // Header button's toggle -- session-only, and cleared on close so every
  // open starts in the layout the user picked in Preferences.
  const [maximized, setMaximized] = useState(false);
  const closeDrawer = () => {
    setViewing(null);
    setMaximized(false);
  };

  useEffect(() => {
    if (report.sample_context) {
      setText(JSON.stringify(report.sample_context, null, 2));
    } else if (schema && schema.fields.length > 0) {
      setText(JSON.stringify(skeletonFromFields(schema.fields), null, 2));
    }
    // Only re-seed when we didn't already have a sample and fields just loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema]);

  function parsed(): Record<string, unknown> | null {
    try {
      return JSON.parse(text);
    } catch (err) {
      setError(`Context data isn't valid JSON: ${(err as Error).message}`);
      return null;
    }
  }

  const liveComplete =
    form !== null &&
    form.parameters.every((p) => !p.required || ((p.options === null || p.options.length > 0) && (values[p.name] ?? "") !== ""));

  async function handleRender() {
    setError(null);
    setSaveMsg(null);

    if (mode === "live") {
      if (!form || !liveComplete) return;
      if (canPreview) {
        setViewing({ kind: "live", values: { ...values } });
        return;
      }
      setPending(true);
      try {
        const { blob, filename } = await api.runReport(report.report_id, values, form.formats[0], report.name);
        downloadBlob(blob, filename);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Run failed");
      } finally {
        setPending(false);
      }
      return;
    }

    const data = parsed();
    if (!data) return;

    if (canPreview) {
      // ReportViewer does its own PDF render (and its export menu covers
      // every format this template supports) -- this just hands it the
      // context to render against.
      setViewing({ kind: "sample", context: data });
      return;
    }

    setPending(true);
    try {
      const { blob, filename } = await api.render(report.report_id, data, "xlsx", report.name);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Render failed");
    } finally {
      setPending(false);
    }
  }

  async function handleSaveSample() {
    setError(null);
    const data = parsed();
    if (!data) return;
    try {
      await api.updateReport(report.report_id, { sample_context: data });
      onSampleSaved(data);
      setSaveMsg("Saved as this template's sample context.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    }
  }

  const live = mode === "live" && liveAvailable;

  return (
    <div className="panel panel-fill">
      <h2 className="panel-title">Preview</h2>
      <p className="panel-subtitle">
        {live
          ? "Run this report the way the people who open it will: choose the filters, and it fetches its data and renders."
          : canPreview
            ? "Render this template against context data and page through the result, right here."
            : "Render this template against context data, right here."}
      </p>

      <div className="preview-toolbar">
        {liveAvailable && (
          <div className="segmented" role="group" aria-label="What to preview with">
            <button type="button" className={`segmented-btn${live ? " active" : ""}`} onClick={() => setMode("live")}>
              Live run
            </button>
            <button type="button" className={`segmented-btn${!live ? " active" : ""}`} onClick={() => setMode("sample")}>
              Sample data
            </button>
          </div>
        )}
        <div className="preview-actions">
          <button type="button" className="btn btn-primary" onClick={handleRender} disabled={pending || (live && !liveComplete)}>
            {pending && <span className="spinner" />}
            {live ? (canPreview ? "Run report" : "Run and download") : canPreview ? "Render preview" : "Render & download"}
          </button>
          {!live && (
            <button type="button" className="btn" onClick={handleSaveSample}>
              Save as sample
            </button>
          )}
        </div>
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {saveMsg && <p className="alert alert-success">{saveMsg}</p>}
      {live && form ? (
        <>
          {unsavedConfig && (
            <p className="alert alert-warning">
              The Parameters or Data source tab has unsaved changes. A live run uses what is saved — save them first to test them here.
            </p>
          )}
          {form.parameters.length > 0 ? (
            <div className="preview-filters">
              {form.parameters.map((p) => (
                <ParameterField key={p.name} parameter={p} value={values[p.name] ?? ""} onChange={(next) => setValues((prev) => ({ ...prev, [p.name]: next }))} />
              ))}
            </div>
          ) : (
            <p className="muted">This report has no filters — it just fetches its data and renders.</p>
          )}
        </>
      ) : (
        <>
          {liveAvailable && (
            <p className="field-hint" style={{ margin: "0 0 8px" }}>
              Sample data skips the filters and the data source: it shows how the template looks with the JSON below, nothing more. Use{" "}
              <strong>Live run</strong> to test the filters and data.
            </p>
          )}
          <label className="fill-field">
            <span>Context data (JSON)</span>
            <textarea className="mono-input json-editor" spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} />
          </label>
        </>
      )}

      {canPreview && (
        <dialog
          ref={drawerRef}
          onCancel={closeDrawer}
          // `open:flex`, not a bare `flex` -- see UserSettingsModal.tsx for
          // why an unconditional display utility on a <dialog> breaks its
          // close(). Size, position and corners come from
          // DRAWER_LAYOUT_CLASSES for whichever layout is currently saved
          // (and whether the header's maximize toggle is on).
          className={`modal open:flex report-viewer-drawer report-viewer-drawer-${previewLayout} flex-col overflow-hidden p-0 ${
            DRAWER_LAYOUT_CLASSES[previewLayout][maximized ? "maximized" : "normal"]
          }`}
        >
          <div className="flex flex-none items-center justify-between gap-3 border-b border-border-soft px-5 py-3">
            <h2 className="m-0 truncate font-display text-[1.05rem] font-semibold text-text">{report.name}</h2>
            <div className="flex flex-none items-center gap-1">
              <button
                type="button"
                className="btn btn-ghost btn-sm icon-only max-md:hidden"
                onClick={() => setMaximized((m) => !m)}
                aria-label={maximized ? "Restore preview size" : "Maximize preview"}
                title={maximized ? "Restore size" : "Maximize"}
              >
                {maximized ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
              </button>
              <button type="button" className="btn btn-ghost btn-sm icon-only" onClick={closeDrawer} aria-label="Close preview">
                ✕
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1">
            {viewing && (
              <Suspense
                fallback={
                  <div className="report-viewer-stage">
                    <ReportSkeleton />
                  </div>
                }
              >
                <ReportViewer
                  reportId={report.report_id}
                  reportName={report.name}
                  templateExt={report.template_ext}
                  contextData={viewing.kind === "sample" ? viewing.context : NO_CONTEXT}
                  renderer={
                    viewing.kind === "live" ? (format, part) => api.runReport(report.report_id, viewing.values, format, report.name, part) : undefined
                  }
                />
              </Suspense>
            )}
          </div>
        </dialog>
      )}
    </div>
  );
}

function AccessTab({ report, onUpdated }: { report: ReportMeta; onUpdated: (r: ReportMeta) => void }) {
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [users, setUsers] = useState<User[] | null>(null);
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [subjectType, setSubjectType] = useState<"user" | "role">("user");
  const [subjectId, setSubjectId] = useState("");
  const [permissionLevel, setPermissionLevel] = useState<"view" | "render" | "manage">("view");
  const [expiry, setExpiry] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<string | null>(null);
  const [publicSaving, setPublicSaving] = useState(false);
  const [publicError, setPublicError] = useState<string | null>(null);
  // The report's choice-list parameters (the only kind a grant can narrow),
  // and the values ticked for each in the grant being drafted: no entry
  // means "all values", an entry means "only these".
  const [limitableParams, setLimitableParams] = useState<ReportParameter[]>([]);
  const [limits, setLimits] = useState<Record<string, string[]>>({});

  useEffect(() => {
    api
      .getDataConfig(report.report_id)
      .then((config) => setLimitableParams(config.parameters.filter((p) => p.options !== null && p.options.length > 0)))
      .catch(() => setLimitableParams([]));
    setLimits({});
  }, [report.report_id]);

  function load() {
    api.grants.reports.list(report.report_id).then(setGrants).catch(() => {});
    api.users.list(report.org_id ?? undefined).then(setUsers).catch(() => {});
    api.roles.list(report.org_id ?? undefined).then(setRoles).catch(() => {});
  }

  useEffect(load, [report.report_id]);

  async function togglePublic(next: boolean) {
    setPublicError(null);
    setPublicSaving(true);
    try {
      onUpdated(await api.updateReport(report.report_id, { is_public: next }));
    } catch (err) {
      setPublicError(err instanceof ApiError ? err.message : "Couldn't update visibility");
    } finally {
      setPublicSaving(false);
    }
  }

  function subjectLabel(g: Grant): string {
    if (!g.subject_id) return "—";
    if (g.subject_type === "role") return roles?.find((r) => r.id === g.subject_id)?.name ?? g.subject_id;
    return users?.find((u) => u.id === g.subject_id)?.username ?? g.subject_id;
  }

  async function grant() {
    if (!subjectId) return;
    setError(null);
    try {
      await api.grants.reports.grant(
        subjectType,
        subjectId,
        report.report_id,
        permissionLevel,
        toExpiresAt(expiry),
        permissionLevel === "view" ? null : limits
      );
      setSubjectId("");
      setExpiry("");
      setLimits({});
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't grant access");
    }
  }

  async function confirmRevoke() {
    if (!revokeTarget) return;
    try {
      await api.grants.reports.revoke(revokeTarget);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't revoke");
    } finally {
      setRevokeTarget(null);
    }
  }

  return (
    <div className="panel">
      <h2 className="panel-title">Access Privilege</h2>
      <p className="panel-subtitle">
        Choose who can view, run or manage this template: everyone in the organization, or specific users and roles, optionally
        until a date.
      </p>

      <div style={{ marginBottom: 18 }}>
        <label className="checkbox-label" style={{ marginBottom: 0 }}>
          <input
            type="checkbox"
            checked={report.is_public}
            disabled={publicSaving}
            onChange={(e) => togglePublic(e.target.checked)}
          />
          Public within this organization
        </label>
        {/* Under the checkbox, in line with its label text -- not pushed to the far edge of the row. */}
        <p className="field-hint" style={{ margin: "4px 0 0 26px" }}>
          Every user in this organization automatically gets <strong>view</strong> access — running it still needs an
          explicit grant below.
        </p>
      </div>
      {publicError && <p className="alert alert-error">{publicError}</p>}

      {error && <p className="alert alert-error">{error}</p>}

      <div className="grant-block">
        {grants
          ?.filter((g) => g.is_active)
          .map((g) => (
            <div key={g.id} className="grant-row">
              <span className={`badge badge-${g.subject_type === "role" ? "system" : "local"}`}>{g.subject_type}</span>
              <span className="mono">{subjectLabel(g)}</span>
              <span className="muted">{g.permission_level}</span>
              <span className="muted">{g.expires_at ? `expires ${new Date(g.expires_at).toLocaleDateString()}` : "no expiry"}</span>
              <button type="button" className="link-btn" onClick={() => setRevokeTarget(g.id)}>
                revoke
              </button>
              {g.parameter_limits && Object.keys(g.parameter_limits).length > 0 && (
                <span className="grant-row-limits">
                  {Object.entries(g.parameter_limits).map(([name, values]) => (
                    <span key={name} className="limit-chip">
                      <strong>{limitableParams.find((p) => p.name === name)?.label ?? name}</strong>: {values.join(", ")}
                    </span>
                  ))}
                </span>
              )}
            </div>
          ))}
        {grants && grants.filter((g) => g.is_active).length === 0 && <p className="muted">No report-specific grants yet.</p>}

        <div className="row grant-form">
          <select value={subjectType} onChange={(e) => setSubjectType(e.target.value as "user" | "role")}>
            <option value="user">User</option>
            <option value="role">Role</option>
          </select>
          <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
            <option value="">{subjectType === "user" ? "Choose a user…" : "Choose a role…"}</option>
            {subjectType === "user"
              ? users?.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username}
                  </option>
                ))
              : roles?.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
          </select>
          <select value={permissionLevel} onChange={(e) => setPermissionLevel(e.target.value as "view" | "render" | "manage")}>
            <option value="view">view</option>
            <option value="render">render</option>
            <option value="manage">manage</option>
          </select>
          <input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} title="Optional expiry date" />
          <button
            type="button"
            className="btn btn-primary"
            onClick={grant}
            disabled={!subjectId || (permissionLevel !== "view" && Object.values(limits).some((v) => v.length === 0))}
          >
            <Plus size={14} /> Grant
          </button>
        </div>

        {permissionLevel !== "view" && limitableParams.length > 0 && (
          <div className="grant-limits">
            <p className="field-hint grant-limits-hint">
              Optionally limit what this grant may run the report with. “All values” leaves a filter unrestricted; “Only these” allows just the
              ticked ones — enforced by the server whenever they run it.
            </p>
            {limitableParams.map((p) => {
              const selected = limits[p.name];
              return (
                <fieldset key={p.name} className="grant-limit">
                  <legend>{p.label ?? p.name}</legend>
                  <label className="checkbox-label">
                    <input
                      type="radio"
                      name={`limit-${p.name}`}
                      checked={selected === undefined}
                      onChange={() =>
                        setLimits((prev) => {
                          const { [p.name]: _dropped, ...rest } = prev;
                          return rest;
                        })
                      }
                    />
                    All values
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="radio"
                      name={`limit-${p.name}`}
                      checked={selected !== undefined}
                      onChange={() => setLimits((prev) => ({ ...prev, [p.name]: prev[p.name] ?? [] }))}
                    />
                    Only these
                  </label>
                  {selected !== undefined && (
                    <div className="grant-limit-options">
                      {p.options?.map((o) => (
                        <label key={o.value} className="checkbox-label">
                          <input
                            type="checkbox"
                            checked={selected.includes(o.value)}
                            onChange={(e) =>
                              setLimits((prev) => ({
                                ...prev,
                                [p.name]: e.target.checked ? [...selected, o.value] : selected.filter((v) => v !== o.value),
                              }))
                            }
                          />
                          {o.label ? `${o.label} (${o.value})` : o.value}
                        </label>
                      ))}
                      {selected.length === 0 && <span className="run-field-note run-field-note-warn">Tick at least one value.</span>}
                    </div>
                  )}
                </fieldset>
              );
            })}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke access"
        body="This takes effect immediately."
        confirmLabel="Revoke"
        onConfirm={confirmRevoke}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}

export default function TemplateDetail({
  reportId,
  tab: urlTab,
  onTabChange,
  onBack,
  onDeleted,
  auth,
}: {
  reportId: string;
  /** The tab's URL slug -- the route is the source of truth for which tab is
   * open, so a tab can be linked to, bookmarked, and survives a reload. */
  tab: string | undefined;
  onTabChange: (slug: string | undefined) => void;
  onBack: () => void;
  onDeleted: () => void;
  auth: AuthInfo;
}) {
  const [report, setReport] = useState<ReportMeta | null>(null);
  const [schema, setSchema] = useState<ReportSchema | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // The template's change log: versions of its file plus every recorded
  // change. Held here (not in the History tab) because the Overview tab
  // needs it too -- to know whether the original upload can still be
  // downloaded -- and both should refresh when the file is replaced.
  const [changelog, setChangelog] = useState<ReportChangelog | null>(null);
  const [changelogError, setChangelogError] = useState<string | null>(null);
  // May this person manage *this* report? The template page is for
  // managers only -- the "Manage" button on the Reports page is what leads
  // here, and it only shows at the Manage level -- but nothing stopped
  // anyone else who opened the URL from seeing (and being offered) the
  // edit and delete controls. The global report:manage permission answers
  // yes at once; otherwise it's whatever level the server says this person
  // holds on this report (a report or folder grant). null = not known yet.
  const [canManage, setCanManage] = useState<boolean | null>(null);

  // What this person may see is known at once from their permissions, so the
  // active tab can be resolved before the report has even loaded.
  const tabs = TABS.filter((t) => !GLOBAL_ONLY_TABS.includes(t.id) || has(auth, "report:manage"));
  // A slug we don't recognise -- or one for a tab this person isn't offered, like
  // /access for a per-report manager -- lands on the Overview.
  const tab: Tab = tabs.find((t) => tabSlug(t.id) === urlTab)?.id ?? "overview";

  // Parameters and Data source are two views of one configuration, so they share
  // a draft -- held here so an edit survives moving from one to the other -- and
  // it's only fetched once either is opened.
  const dataConfig = useDataConfigDraft(reportId, canManage === true && (tab === "parameters" || tab === "datasource"));

  // ...and the URL is corrected to say so (replacing the entry, not adding one),
  // so what's in the address bar is always the tab on screen. Held back until the
  // page is ready: a link to a tab that's valid for this person must never be
  // "corrected" on a guess made before we know who they are.
  useEffect(() => {
    if (report && canManage === true && urlTab !== tabSlug(tab)) onTabChange(tabSlug(tab));
  }, [report, canManage, urlTab, tab, onTabChange]);

  useEffect(() => {
    setReport(null);
    setSchema(null);
    setLoadError(null);
    api.getReport(reportId).then(setReport).catch(() => setLoadError("Template not found."));
    api.getSchema(reportId).then(setSchema).catch(() => {});

    if (has(auth, "report:manage")) {
      setCanManage(true);
      return;
    }
    setCanManage(null);
    let cancelled = false;
    // `reportId` is whatever the URL carries -- an id or a code -- so match on
    // the canonical id the API reports back, not on the route's own string.
    Promise.all([api.getReport(reportId), api.listAccessibleReports()])
      .then(([current, list]) => {
        if (!cancelled) setCanManage(list.some((r) => r.report_id === current.report_id && r.access_level === "manage"));
      })
      .catch(() => {
        if (!cancelled) setCanManage(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `auth` is
    // fixed for the life of a signed-in session; only the report changes.
  }, [reportId]);

  const loadChangelog = useCallback(() => {
    setChangelogError(null);
    api
      .getChangelog(reportId)
      .then(setChangelog)
      .catch((err) => setChangelogError(err instanceof ApiError ? err.message : "Couldn't load the change log"));
  }, [reportId]);

  // Once we know the caller manages this report (the endpoint needs that),
  // and again whenever the file is replaced (a new version).
  useEffect(() => {
    setChangelog(null);
  }, [reportId]);
  useEffect(() => {
    if (canManage) loadChangelog();
  }, [canManage, loadChangelog, report?.version]);

  if (loadError) {
    return (
      <div className="detail-page">
        <button type="button" className="btn-ghost btn" onClick={onBack}>
          ← Back
        </button>
        <p className="alert alert-error" style={{ marginTop: 16 }}>
          {loadError}
        </p>
      </div>
    );
  }

  if (canManage === false) {
    return (
      <div className="detail-page">
        <button type="button" className="btn-ghost btn" onClick={onBack}>
          ← Back to Reports
        </button>
        <div className="empty-state" style={{ marginTop: 16 }}>
          <p>You don't have permission to manage this template.</p>
          <p className="empty-state-hint">
            Managing a template — its settings, filters and data — needs the Manage level on the report. Ask an
            administrator if you need it.
          </p>
        </div>
      </div>
    );
  }

  if (!report || canManage === null) {
    return (
      <div className="detail-page">
        <div className="breadcrumb">
          <button type="button" className="link-btn" onClick={onBack}>
            ← All templates
          </button>
        </div>
        <div className="page-header">
          <div>
            <div className="skel skel-line" style={{ width: 220, height: 22, marginBottom: 8 }} />
            <div className="skel skel-line" style={{ width: 130, height: 12 }} />
          </div>
          <div className="skel skel-card-badge" />
        </div>
        <div className="detail-layout">
          <div className="vtabs" aria-hidden="true">
            {Array.from({ length: 5 }, (_, i) => (
              <div key={i} className="skel skel-line" style={{ height: 34, width: "100%" }} />
            ))}
          </div>
          <div className="panel">
            <LinesSkeleton count={5} />
          </div>
        </div>
      </div>
    );
  }

  // Vertical tablist: Up/Down (wrapping) plus Home/End move selection and
  // focus together -- the ARIA pattern's "automatic activation", which is
  // fine here since every panel is cheap to switch to.
  function onTabKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const i = tabs.findIndex((t) => t.id === tab);
    let next: number;
    if (e.key === "ArrowDown") next = (i + 1) % tabs.length;
    else if (e.key === "ArrowUp") next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    onTabChange(tabSlug(tabs[next].id));
    document.getElementById(`tab-${tabs[next].id}`)?.focus();
  }

  return (
    <div className="detail-page">
      <div className="breadcrumb">
        <button type="button" className="link-btn" onClick={onBack}>
          ← All templates
        </button>
      </div>
      <div className="page-header">
        <div>
          <h1 className="page-title">{report.name}</h1>
          <span className="mono muted">{report.report_id}</span>
          {report.code && (
            <span
              className="ml-2 rounded-full border border-accent-border bg-accent-soft px-2 py-0.5 align-middle font-mono text-[0.72rem] text-accent-strong"
              title="Code — use it instead of the ID in API calls and embed links"
            >
              {report.code}
            </span>
          )}
        </div>
        <span className={`badge badge-${report.template_ext}`}>{report.template_ext}</span>
      </div>

      {report.is_draft && (
        <div className="draft-banner" role="status">
          <span className="badge badge-draft">Draft</span>
          <span className="draft-banner-text">Only people who manage this report can see or run it until it's published.</span>
          <a className="btn btn-sm" href={`#/templates/new/${encodeURIComponent(report.report_id)}`}>
            Continue setup
          </a>
          {has(auth, "report:manage") && (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => api.wizard.publish(report.report_id).then(setReport).catch(() => {})}
            >
              Publish
            </button>
          )}
        </div>
      )}

      <div className="detail-layout">
        <div className="vtabs" role="tablist" aria-orientation="vertical" aria-label="Template sections" onKeyDown={onTabKeyDown}>
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              id={`tab-${id}`}
              type="button"
              role="tab"
              aria-selected={tab === id}
              aria-controls="detail-pane"
              tabIndex={tab === id ? 0 : -1}
              className={`vtab ${tab === id ? "active" : ""}`}
              onClick={() => onTabChange(tabSlug(id))}
            >
              <Icon size={17} strokeWidth={1.6} aria-hidden />
              {label}
              {((id === "parameters" && dataConfig.parametersDirty) || (id === "datasource" && dataConfig.sourceDirty)) && (
                <span className="vtab-dirty" role="img" aria-label="Unsaved changes" title="Unsaved changes" />
              )}
            </button>
          ))}
        </div>

        {/* Keyed on the tab so the enter animation replays on every switch. */}
        <div key={tab} id="detail-pane" className="detail-pane" role="tabpanel" aria-labelledby={`tab-${tab}`}>
          {tab === "overview" && <OverviewTab
              report={report}
              changelog={changelog}
              onUpdated={setReport}
              onDeleted={onDeleted}
              onOpenHistory={() => onTabChange(tabSlug("history"))}
            />}
          {tab === "history" && <HistoryTab report={report} changelog={changelog} error={changelogError} onReload={loadChangelog} onChanged={() => { loadChangelog(); api.getReport(reportId).then(setReport).catch(() => {}); }} />}
          {tab === "placeholders" && <PlaceholdersTab schema={schema} reportId={report.report_id} />}
          {tab === "parameters" && (
            <ParametersTab
              report={report}
              draft={dataConfig}
              canManageConnections={has(auth, "connection:manage")}
              canManageSecrets={has(auth, "secret:manage")}
              orgId={report.org_id ?? auth.orgId ?? "root"}
            />
          )}
          {tab === "datasource" && (
            <DataSourceTab
              draft={dataConfig}
              canManageConnections={has(auth, "connection:manage")}
              canManageSecrets={has(auth, "secret:manage")}
              orgId={report.org_id ?? auth.orgId ?? "root"}
            />
          )}
          {tab === "terms" && has(auth, "report:manage") && (
            <ProtectedTermsTab report={report} canManageSets={has(auth, "protected_terms:manage")} />
          )}
          {tab === "preview" && (
            <PreviewTab
              report={report}
              schema={schema}
              onSampleSaved={(ctx) => setReport({ ...report, sample_context: ctx })}
              unsavedConfig={dataConfig.parametersDirty || dataConfig.sourceDirty}
            />
          )}
          {tab === "access" && has(auth, "report:manage") && <AccessTab report={report} onUpdated={setReport} />}
          {tab === "shortcuts" && <ShortcutsTab report={report} />}
          {tab === "integration" && <IntegrationTab report={report} onOpenOverview={() => onTabChange(undefined)} />}
        </div>
      </div>
    </div>
  );
}
