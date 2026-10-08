import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { ArrowDownAZ, ArrowUpAZ, Check, Copy, FileCode, FileSpreadsheet, FileText, History, Plus, Search, SearchX, X } from "lucide-react";
import { api } from "../api";
import { useCopy } from "../hooks";
import { versionName, type AuthInfo, type ReportMeta, type TemplateExt } from "../types";
import RegisterDialog from "./RegisterDialog";
import ViewSwitch, { readView, saveView, type LayoutView } from "./ViewSwitch";
import { CardGridSkeleton, ListSkeleton } from "./Skeletons";

const VIEW_KEY = "portal_gallery_view";
/** The Templates page is a flat catalogue of every template -- grid or list. The folder tree lives on Reports
 * (where people browse to *run* things); here, where a template is also listed is on its own Shortcuts tab. */
type GalleryView = Exclude<LayoutView, "tree">;
const GALLERY_VIEWS = ["grid", "list"] as const;
type ExtFilter = "all" | TemplateExt;

const SORT_KEY = "portal_gallery_sort";
type SortKey = "name-asc" | "name-desc" | "updated-desc";
const SORT_LABELS: Record<SortKey, string> = {
  "name-asc": "Name (A–Z)",
  "name-desc": "Name (Z–A)",
  "updated-desc": "Recently updated",
};
const SORT_ICONS: Record<SortKey, typeof ArrowDownAZ> = {
  "name-asc": ArrowDownAZ,
  "name-desc": ArrowUpAZ,
  "updated-desc": History,
};
const SORT_ORDER: SortKey[] = ["name-asc", "name-desc", "updated-desc"];

function IdChip({ id }: { id: string }) {
  const [copied, copy] = useCopy();
  return (
    <span className={`id-chip${copied ? " copied" : ""}`} onClick={(e) => e.stopPropagation()}>
      {id}
      <button type="button" onClick={() => copy(id)} title="Copy report_id" aria-label={copied ? "Copied report ID" : "Copy report ID"}>
        {copied ? <Check size={12} strokeWidth={3} aria-hidden="true" /> : <Copy size={12} aria-hidden="true" />}
      </button>
      {/* Announced to screen readers when it appears; the tick on the button is the visual half of the same message. */}
      {copied && (
        <span className="id-chip-toast" role="status">
          Copied report ID
        </span>
      )}
    </span>
  );
}

function TemplateCard({ report, index, onOpen }: { report: ReportMeta; index: number; onOpen: () => void }) {
  return (
    <article className="card" style={{ "--i": index } as CSSProperties} onClick={onOpen}>
      <div className="card-top">
        <h3 className="card-name">{report.name}</h3>
        <span className="card-top-badges">
          {report.is_public && <span className="badge badge-public">Public</span>}
          <span className={`badge badge-${report.template_ext}`}>{report.template_ext}</span>
        </span>
      </div>
      {/* Always rendered, even blank -- .card-desc reserves two lines'
          worth of height either way, so a card with no description is
          never shorter than one that has it (matters most in a CSS
          Grid row that's otherwise alone, with nothing else to stretch
          against -- see styles/pages.css's own note on .card-desc). */}
      <p className="card-desc">{report.description}</p>
      <IdChip id={report.report_id} />
      <div className="card-meta">
        <span>{versionName(report.version, report.version_label)}</span>
        <span>{new Date(report.updated_at).toLocaleDateString()}</span>
      </div>
    </article>
  );
}

const FILE_ICONS = { docx: FileText, xlsx: FileSpreadsheet, html: FileCode } as const;

/** The template's type as a small file tile -- glyph over extension, colour-coded like the type badges. */
function FileTile({ ext }: { ext: ReportMeta["template_ext"] }) {
  const Icon = FILE_ICONS[ext];
  return (
    <span className={`file-tile badge-${ext}`} title={`${ext.toUpperCase()} template`}>
      <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
      <span>{ext}</span>
    </span>
  );
}

function TemplateRow({ report, index, onOpen }: { report: ReportMeta; index: number; onOpen: () => void }) {
  return (
    <article className="list-row list-row-file" style={{ "--i": index } as CSSProperties} onClick={onOpen}>
      <FileTile ext={report.template_ext} />
      <div className="list-row-main">
        <div className="list-row-title">
          <h3>{report.name}</h3>
          {report.is_public && <span className="badge badge-public">Public</span>}
        </div>
        <p className="list-row-desc" title={report.description || undefined} aria-hidden={report.description ? undefined : true}>
          {report.description || "\u00a0"}
        </p>
      </div>
      <div className="list-row-side">
        <div className="list-row-meta">
          <span>{versionName(report.version, report.version_label)}</span>
          <span>{new Date(report.updated_at).toLocaleDateString()}</span>
        </div>
        <IdChip id={report.report_id} />
      </div>
    </article>
  );
}

export default function Gallery({ auth, onOpenReport }: { auth: AuthInfo; onOpenReport: (id: string) => void }) {
  const [reports, setReports] = useState<ReportMeta[] | null>(null);
  const [query, setQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [extFilter, setExtFilter] = useState<ExtFilter>("all");
  const [view, setView] = useState<GalleryView>(() => readView(VIEW_KEY, GALLERY_VIEWS) as GalleryView);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>(() => {
    try {
      const stored = localStorage.getItem(SORT_KEY);
      return stored === "name-asc" || stored === "name-desc" || stored === "updated-desc" ? stored : "updated-desc";
    } catch {
      return "updated-desc";
    }
  });

  function load() {
    api
      .listReports()
      .then(setReports)
      .catch(() => setError("Couldn't load templates — is the API reachable?"));
  }

  useEffect(load, []);

  function changeView(next: GalleryView) {
    setView(next);
    saveView(VIEW_KEY, next);
  }

  function changeSort(next: SortKey) {
    setSort(next);
    try {
      localStorage.setItem(SORT_KEY, next);
    } catch {
      // best-effort only — sort preference just won't persist
    }
  }

  const counts = useMemo(() => {
    const c = { docx: 0, xlsx: 0, html: 0 };
    for (const r of reports ?? []) c[r.template_ext]++;
    return c;
  }, [reports]);

  const filtered = useMemo(() => {
    if (!reports) return [];
    const q = query.trim().toLowerCase();
    const matches = reports.filter((r) => {
      if (extFilter !== "all" && r.template_ext !== extFilter) return false;
      if (!q) return true;
      return (
        r.name.toLowerCase().includes(q) ||
        r.report_id.includes(q) ||
        (r.code ?? "").includes(q) ||
        (r.description ?? "").toLowerCase().includes(q)
      );
    });
    const sorted = [...matches];
    if (sort === "name-asc") sorted.sort((a, b) => a.name.localeCompare(b.name));
    else if (sort === "name-desc") sorted.sort((a, b) => b.name.localeCompare(a.name));
    else sorted.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    return sorted;
  }, [reports, query, extFilter, sort]);

  const hasActiveFilters = query.trim() !== "" || extFilter !== "all";

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Templates</h1>
          <p className="page-subtitle">Register, integrate, and manage the templates this console can render.</p>
        </div>
      </div>

      <div className="gallery-toolbar">
        <form
          className="search-form search-form-compact"
          onSubmit={(e) => {
            e.preventDefault();
            searchInputRef.current?.blur();
          }}
        >
          <div className="search search-icon-field">
            <Search size={16} className="search-icon" aria-hidden="true" />
            <input
              ref={searchInputRef}
              type="text"
              placeholder="Search templates by name, id, or description…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query && (
              <button type="button" className="search-clear" onClick={() => setQuery("")} data-tip="Clear search" aria-label="Clear search">
                <X size={14} />
              </button>
            )}
          </div>
          <button type="submit" className="btn search-submit" data-tip="Search" aria-label="Search">
            <Search size={16} />
          </button>
        </form>

        {/* Type filter, view toggle, sort, and Register move together (see
            .gallery-toolbar-actions) -- at a width too narrow for the whole
            toolbar, this whole group wraps below the search field as one
            block, instead of just the trailing button landing alone on an
            orphaned line while its siblings stay put a row above. */}
        <div className="gallery-toolbar-actions">
          <div className="segmented ext-filter" role="group" aria-label="Filter by file type">
            <button
              type="button"
              className={`segmented-btn${extFilter === "all" ? " active" : ""}`}
              onClick={() => setExtFilter("all")}
              data-tip="All file types"
            >
              All
              <span className="count">{counts.docx + counts.xlsx + counts.html}</span>
            </button>
            <button
              type="button"
              className={`segmented-btn${extFilter === "docx" ? " active" : ""}`}
              onClick={() => setExtFilter("docx")}
              data-tip="Word templates (.docx)"
            >
              <span className="dot dot-docx" />
              DOCX
              <span className="count">{counts.docx}</span>
            </button>
            <button
              type="button"
              className={`segmented-btn${extFilter === "xlsx" ? " active" : ""}`}
              onClick={() => setExtFilter("xlsx")}
              data-tip="Excel templates (.xlsx)"
            >
              <span className="dot dot-xlsx" />
              XLSX
              <span className="count">{counts.xlsx}</span>
            </button>
            <button
              type="button"
              className={`segmented-btn${extFilter === "html" ? " active" : ""}`}
              onClick={() => setExtFilter("html")}
              data-tip="HTML templates"
            >
              <span className="dot dot-html" />
              HTML
              <span className="count">{counts.html}</span>
            </button>
          </div>

          <ViewSwitch view={view} views={GALLERY_VIEWS} onChange={(v) => changeView(v as GalleryView)} />

          <div className="segmented" role="group" aria-label="Sort templates">
            {SORT_ORDER.map((key) => {
              const Icon = SORT_ICONS[key];
              return (
                <button
                  key={key}
                  type="button"
                  className={`segmented-btn icon-only${sort === key ? " active" : ""}`}
                  onClick={() => changeSort(key)}
                  data-tip={SORT_LABELS[key]}
                  aria-label={SORT_LABELS[key]}
                >
                  <Icon size={16} />
                </button>
              );
            })}
          </div>

          {/* Icon + label, not a literal "+" -- the label itself drops out below
              .btn-register's own breakpoint (see responsive.css) so this stays
              a single-line, fixed-height control at any width instead of its
              text wrapping onto a second line and making it taller than the
              segmented controls beside it. */}
          <button type="button" className="btn btn-primary btn-register" onClick={() => setRegisterOpen(true)} data-tip="Register template" aria-label="Register template">
            <Plus size={16} aria-hidden="true" />
            <span className="btn-register-label">Register template</span>
          </button>
        </div>
      </div>

      {error && <p className="alert alert-error">{error}</p>}

      {reports === null && !error && (view === "list" ? <ListSkeleton /> : <CardGridSkeleton />)}

      {reports !== null && filtered.length === 0 && (
        <div className="empty-state">
          {reports.length === 0 ? (
            <div className="glyph-lg">ក</div>
          ) : (
            <SearchX className="empty-state-icon" size={40} strokeWidth={1.4} aria-hidden="true" />
          )}
          <p>{reports.length === 0 ? "No templates registered yet." : "No templates match your search and filters."}</p>
          {hasActiveFilters && reports.length > 0 && (
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setQuery("");
                setExtFilter("all");
              }}
            >
              Clear filters
            </button>
          )}
        </div>
      )}

      {filtered.length > 0 && view === "grid" && (
        <div className="card-grid">
          {filtered.map((report, i) => (
            <TemplateCard key={report.report_id} report={report} index={i} onOpen={() => onOpenReport(report.report_id)} />
          ))}
        </div>
      )}

      {filtered.length > 0 && view === "list" && (
        <div className="list">
          {filtered.map((report, i) => (
            <TemplateRow key={report.report_id} report={report} index={i} onOpen={() => onOpenReport(report.report_id)} />
          ))}
        </div>
      )}

      <RegisterDialog
        open={registerOpen}
        auth={auth}
        onClose={() => setRegisterOpen(false)}
        onCreated={(report) => setReports((prev) => [...(prev ?? []), report])}
      />
    </div>
  );
}
