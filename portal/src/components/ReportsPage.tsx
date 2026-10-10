import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  ArrowDownAZ,
  ArrowUpAZ,
  ChevronRight,
  Link2,
  Eye,
  History,
  Inbox,
  Play,
  Search,
  SearchX,
  Settings2,
  Star,
  X,
} from "lucide-react";
import { api } from "../api";
import { useFavoriteReports } from "../favorites";
import { buildReportTree, folderIds } from "../reportTree";
import ReportsTree, { useTreeCollapsed } from "./ReportsTree";
import ViewSwitch, { readView, saveView, TreeCollapseButtons, type LayoutView } from "./ViewSwitch";
import { CardGridSkeleton, ListSkeleton } from "./Skeletons";
import type { AccessibleReport, ReportAccessLevel } from "../types";

const VIEW_KEY = "portal_reports_view";
type ReportsView = LayoutView;

const SORT_KEY = "portal_reports_sort";
type SortKey = "name-asc" | "name-desc" | "updated-desc";
const SORT_LABELS: Record<SortKey, string> = {
  "name-asc": "Name (A–Z)",
  "name-desc": "Name (Z–A)",
  "updated-desc": "Recently updated",
};
const SORT_ICONS: Record<SortKey, typeof Eye> = {
  "name-asc": ArrowDownAZ,
  "name-desc": ArrowUpAZ,
  "updated-desc": History,
};
const SORT_ORDER: SortKey[] = ["name-asc", "name-desc", "updated-desc"];

// What the viewer may do with a report. View and Run are plain labels -- the
// card itself is how you run a report. Manage is different: it's the way into
// the report's *template* (its settings, filters, data, protected terms,
// access), so for a manager that chip is a button that goes there instead of
// letting the click fall through to the card and run the report.
const ACCESS: Record<ReportAccessLevel, { label: string; hint: string; Icon: typeof Eye }> = {
  view: { label: "View", hint: "Your access: you can see that this report exists, but not open it", Icon: Eye },
  render: { label: "Run", hint: "Your access: you can open this report, choose its filters and run it", Icon: Play },
  manage: {
    label: "Manage",
    hint: "Manage this report: edit its template, filters, data source, protected terms and who has access",
    Icon: Settings2,
  },
};

function AccessChip({ report, onManage }: { report: AccessibleReport; onManage: (id: string) => void }) {
  const { label, hint, Icon } = ACCESS[report.access_level];
  const content = (
    <>
      <Icon size={13} strokeWidth={1.8} aria-hidden="true" />
      {label}
    </>
  );
  if (report.access_level !== "manage") {
    return (
      <span className="access-chip" title={hint}>
        {content}
      </span>
    );
  }
  return (
    <button
      type="button"
      className="access-chip access-chip-action"
      title={hint}
      aria-label={`Manage ${report.name}`}
      onClick={(e) => {
        // Inside a card that runs the report on click -- this is not that.
        e.stopPropagation();
        onManage(report.report_id);
      }}
    >
      {content}
      {/* The cue that this one goes somewhere, unlike the View/Run labels. */}
      <ChevronRight size={12} strokeWidth={2} className="access-chip-go" aria-hidden="true" />
    </button>
  );
}

function StarButton({ name, starred, onToggle }: { name: string; starred: boolean; onToggle: () => void }) {
  const label = starred ? `Remove ${name} from your starred reports` : `Star ${name} to find it faster on Home`;
  return (
    <button
      type="button"
      className={`star-btn${starred ? " starred" : ""}`}
      aria-pressed={starred}
      aria-label={label}
      data-tip={starred ? "Starred" : "Star"}
      onClick={(e) => {
        e.stopPropagation(); // the card around it runs the report on click
        onToggle();
      }}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <Star size={16} strokeWidth={1.8} fill={starred ? "currentColor" : "none"} aria-hidden="true" />
    </button>
  );
}

function ReportCard({
  report,
  index,
  onRun,
  onManage,
  starred,
  onToggleStar,
}: {
  report: AccessibleReport;
  index: number;
  onRun: (id: string) => void;
  onManage: (id: string) => void;
  starred: boolean;
  onToggleStar: () => void;
}) {
  // view-only means "you may see this exists", not "you may open it".
  const runnable = report.access_level !== "view";
  return (
    <article
      className={`card report-card${runnable ? " report-card-runnable" : ""}`}
      style={{ "--i": index } as CSSProperties}
      role={runnable ? "link" : undefined}
      tabIndex={runnable ? 0 : undefined}
      aria-label={runnable ? `Open ${report.name}` : undefined}
      onClick={runnable ? () => onRun(report.report_id) : undefined}
      onKeyDown={
        runnable
          ? (e) => {
              if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                onRun(report.report_id);
              }
            }
          : undefined
      }
    >
      <div className="card-top">
        <h3 className="card-name">{report.name}</h3>
        {report.is_draft && <span className="badge badge-draft" title="Not published yet — only people who manage it see it">Draft</span>}
        <StarButton name={report.name} starred={starred} onToggle={onToggleStar} />
      </div>
      {/* Always rendered, even blank -- .card-desc reserves two lines'
          worth of height either way, so a card with no description is
          never shorter than one that has it (matters most in a CSS
          Grid row that's otherwise alone, with nothing else to stretch
          against -- see styles/pages.css's own note on .card-desc). */}
      <p className="card-desc">{report.description}</p>
      <div className="card-meta">
        <AccessChip report={report} onManage={onManage} />
        <span>{new Date(report.updated_at).toLocaleDateString()}</span>
      </div>
    </article>
  );
}

function ReportRow({
  report,
  index,
  onRun,
  onManage,
  starred,
  onToggleStar,
  shortcutFrom,
}: {
  /** Set when this row is a shortcut: where the original is filed. It opens the original, with its access. */
  shortcutFrom?: string;
  report: AccessibleReport;
  index: number;
  onRun: (id: string) => void;
  onManage: (id: string) => void;
  starred: boolean;
  onToggleStar: () => void;
}) {
  const runnable = report.access_level !== "view";
  return (
    <article
      className={`list-row report-card${runnable ? " report-card-runnable" : ""}`}
      style={{ "--i": index } as CSSProperties}
      role={runnable ? "link" : undefined}
      tabIndex={runnable ? 0 : undefined}
      aria-label={runnable ? `Open ${report.name}` : undefined}
      onClick={runnable ? () => onRun(report.report_id) : undefined}
      onKeyDown={
        runnable
          ? (e) => {
              if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                onRun(report.report_id);
              }
            }
          : undefined
      }
    >
      <div className="list-row-main">
        <div className="list-row-title">
          <h3>{report.name}</h3>
          {report.is_draft && <span className="badge badge-draft" title="Not published yet — only people who manage it see it">Draft</span>}
          {shortcutFrom && (
            <span className="shortcut-chip" title={`A shortcut to the report filed in ${shortcutFrom}. It has the original's access.`}>
              <Link2 size={12} aria-hidden="true" /> Shortcut · {shortcutFrom}
            </span>
          )}
        </div>
        <p className="list-row-desc" title={report.description || undefined} aria-hidden={report.description ? undefined : true}>
          {report.description || "\u00a0"}
        </p>
      </div>
      <div className="list-row-meta">
        <AccessChip report={report} onManage={onManage} />
      </div>
      <div className="list-row-meta" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        {new Date(report.updated_at).toLocaleDateString()}
        <StarButton name={report.name} starred={starred} onToggle={onToggleStar} />
      </div>
    </article>
  );
}

/** The end-user counterpart to Gallery (the Templates screen): just the
 * reports the signed-in user was granted -- via a global report:*
 * permission, a report grant, or a folder grant -- each with the level they
 * hold on it. What the list contains is decided server-side
 * (GET /reports/accessible), never by filtering the public every-template
 * list in the browser. */
export default function ReportsPage({
  username,
  onRunReport,
  onManageTemplate,
}: {
  username: string;
  onRunReport: (id: string) => void;
  onManageTemplate: (id: string) => void;
}) {
  const { favorites, isFavorite, toggle } = useFavoriteReports(username);
  const [reports, setReports] = useState<AccessibleReport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [view, setView] = useState<ReportsView>(() => readView(VIEW_KEY));
  const [sort, setSort] = useState<SortKey>(() => {
    try {
      const stored = localStorage.getItem(SORT_KEY);
      return stored === "name-asc" || stored === "name-desc" || stored === "updated-desc" ? stored : "updated-desc";
    } catch {
      return "updated-desc";
    }
  });

  useEffect(() => {
    api
      .listAccessibleReports()
      .then(setReports)
      .catch(() => setError("Couldn't load your reports — is the API reachable?"));
  }, []);

  function changeView(next: ReportsView) {
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

  const filtered = useMemo(() => {
    if (!reports) return [];
    const q = query.trim().toLowerCase();
    const matches = q
      ? reports.filter((r) => r.name.toLowerCase().includes(q) || (r.description ?? "").toLowerCase().includes(q))
      : reports;
    const sorted = [...matches];
    if (sort === "name-asc") sorted.sort((a, b) => a.name.localeCompare(b.name));
    else if (sort === "name-desc") sorted.sort((a, b) => b.name.localeCompare(a.name));
    else sorted.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    // Starred reports first, in whatever order was chosen.
    return [...sorted.filter((r) => isFavorite(r.report_id)), ...sorted.filter((r) => !isFavorite(r.report_id))];
    // eslint-disable-next-line react-hooks/exhaustive-deps -- isFavorite is a new function each render; `favorites` is what it reads
  }, [reports, query, sort, favorites]);

  const hasActiveSearch = query.trim() !== "";
  const tree = useMemo(() => buildReportTree(filtered, (r) => r.report_id), [filtered]);
  const { collapsed, toggle: toggleFolder, collapseAll, expandAll } = useTreeCollapsed(username);
  const allFolders = useMemo(() => folderIds(tree.folders), [tree]);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Reports</h1>
          <p className="page-subtitle">The reports you've been given access to.</p>
        </div>
      </div>

      {(reports === null || reports.length > 0) && (
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
                placeholder="Search your reports by name or description…"
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

          <ViewSwitch view={view} onChange={changeView} />

          {view === "tree" && allFolders.length > 0 && !hasActiveSearch && (
            <TreeCollapseButtons onExpandAll={expandAll} onCollapseAll={() => collapseAll(allFolders)} />
          )}

          <div className="segmented" role="group" aria-label="Sort reports">
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
        </div>
      )}

      {error && <p className="alert alert-error">{error}</p>}

      {reports === null && !error && (view !== "grid" ? <ListSkeleton badge={false} /> : <CardGridSkeleton badge={false} />)}

      {reports !== null && reports.length === 0 && (
        <div className="empty-state">
          <Inbox className="empty-state-icon" size={40} strokeWidth={1.4} aria-hidden="true" />
          <p>No reports have been shared with you yet.</p>
          <p className="empty-state-hint">Ask an administrator to give you access to a report.</p>
        </div>
      )}

      {reports !== null && reports.length > 0 && filtered.length === 0 && (
        <div className="empty-state">
          <SearchX className="empty-state-icon" size={40} strokeWidth={1.4} aria-hidden="true" />
          <p>No reports match your search.</p>
          {hasActiveSearch && (
            <button type="button" className="link-btn" onClick={() => setQuery("")}>
              Clear search
            </button>
          )}
        </div>
      )}

      {filtered.length > 0 && view === "grid" && (
        <div className="card-grid">
          {filtered.map((report, i) => (
            <ReportCard key={report.report_id} report={report} index={i} onRun={onRunReport} onManage={onManageTemplate} starred={isFavorite(report.report_id)} onToggleStar={() => toggle(report.report_id)} />
          ))}
        </div>
      )}

      {filtered.length > 0 && view === "tree" && (
        <ReportsTree
          tree={tree}
          idOf={(r) => r.report_id}
          collapsed={collapsed}
          forceOpen={hasActiveSearch}
          onToggle={toggleFolder}
          renderReport={(report, i, entry) => (
            <ReportRow report={report} index={i} shortcutFrom={entry?.shortcutFrom} onRun={onRunReport} onManage={onManageTemplate} starred={isFavorite(report.report_id)} onToggleStar={() => toggle(report.report_id)} />
          )}
        />
      )}

      {filtered.length > 0 && view === "list" && (
        <div className="list">
          {filtered.map((report, i) => (
            <ReportRow key={report.report_id} report={report} index={i} onRun={onRunReport} onManage={onManageTemplate} starred={isFavorite(report.report_id)} onToggleStar={() => toggle(report.report_id)} />
          ))}
        </div>
      )}
    </div>
  );
}
