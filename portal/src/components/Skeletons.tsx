import type { CSSProperties } from "react";

/** Shared shimmer shapes for every page's loading state -- each reuses the
 * real layout class (`.data-table`, `.card`, `.stat-row`, `.meter`, ...) so
 * the skeleton occupies exactly the space the real content will, and only
 * the leaf bars (`.skel-*`, see styles/pages.css) are skeleton-specific.
 * Pick whichever shape matches what's loading rather than a bare spinner. */

const WIDTHS = ["92%", "78%", "86%", "64%"];

/** A `.data-table` with the real header labels (so the columns don't jump
 * when data arrives) and shimmer body rows. */
export function TableSkeleton({ columns, rows = 6 }: { columns: string[]; rows?: number }) {
  return (
    <table className="data-table" aria-hidden="true">
      <thead>
        <tr>
          {columns.map((c, j) => (
            <th key={j}>{c}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, i) => (
          <tr key={i} style={{ cursor: "default" }}>
            {columns.map((_, j) => (
              <td key={j}>
                <div className="skel skel-table-cell" style={{ width: j === 0 ? "70%" : WIDTHS[j % WIDTHS.length] }} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A `.card-grid` of card-shaped placeholders (title, optionally a type
 * badge, two description lines, a pill-shaped chip and a date in the meta
 * row) -- matches Gallery's TemplateCard (which has the badge) and
 * ReportsPage's ReportCard (which, since it doesn't show template format,
 * doesn't -- pass `badge={false}`) alike. */
export function CardGridSkeleton({ count = 6, badge = true }: { count?: number; badge?: boolean }) {
  return (
    <div className="card-grid" role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card card-skeleton" style={{ "--i": i } as CSSProperties} aria-hidden="true">
          <div className="card-top">
            <div className="skel skel-card-title" />
            {badge && <div className="skel skel-card-badge" />}
          </div>
          <div className="skel-card-desc-lines">
            <div className="skel skel-card-desc" />
            <div className="skel skel-card-desc" />
          </div>
          <div className="card-meta">
            <div className="skel skel-card-chip" />
            <div className="skel skel-card-date" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** The `.list` counterpart to CardGridSkeleton -- one `.list-row` shape per
 * placeholder instead of a card. Same `badge` toggle, same reason. */
export function ListSkeleton({ count = 6, badge = true }: { count?: number; badge?: boolean }) {
  return (
    <div className="list" role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="list-row list-row-skeleton" style={{ "--i": i } as CSSProperties} aria-hidden="true">
          <div className="list-row-main">
            <div className="list-row-title">
              {badge && <div className="skel skel-row-badge" />}
              <div className="skel skel-row-title" />
            </div>
            <div className="skel skel-row-desc" />
          </div>
          <div className="skel skel-row-chip" />
          <div className="skel skel-row-date" />
        </div>
      ))}
    </div>
  );
}

/** A `.stat-row` of big-number tiles -- Dashboard's job totals, Schedules'
 * today's-runs counts, Monitor's process stats. */
export function StatRowSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="stat-row" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i}>
          <div className="skel skel-stat-number" />
          <div className="skel skel-stat-label" />
        </div>
      ))}
    </div>
  );
}

/** A MetricMeter-shaped placeholder: label + value row above a track, the
 * track itself just `.meter`'s own real background/border with a shimmer
 * filling it end to end rather than a fake percentage. */
export function MeterSkeleton() {
  return (
    <div className="meter-row" aria-hidden="true">
      <div className="meter-row-head">
        <div className="skel skel-meter-label" />
        <div className="skel skel-meter-value" />
      </div>
      <div className="meter">
        <div className="skel skel-meter-fill" />
      </div>
    </div>
  );
}

/** A few pill-shaped chips -- for a `.field-pills` list (permission/role
 * grant chips) that's still loading. */
export function PillsSkeleton({ count = 3 }: { count?: number }) {
  const widths = [64, 88, 52, 76];
  return (
    <>
      <span className="sr-only">Loading…</span>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skel skel-pill" style={{ width: widths[i % widths.length] }} aria-hidden="true" />
      ))}
    </>
  );
}

/** Plain shimmer text lines -- the catch-all for a small "Loading…" spot
 * inside an already-open panel or dialog (a permission group, an activity
 * feed, a settings section) where a bespoke shape isn't worth building. */
export function LinesSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="skel-lines" role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skel skel-line" style={{ width: WIDTHS[i % WIDTHS.length] }} aria-hidden="true" />
      ))}
    </div>
  );
}

/** Indented rows standing in for the Resources folder tree while it loads. */
export function TreeSkeleton({ count = 7 }: { count?: number }) {
  const depths = [0, 1, 1, 0, 1, 2, 1];
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="skel skel-tree-row"
          style={{ marginLeft: (depths[i % depths.length] || 0) * 20, width: WIDTHS[i % WIDTHS.length] }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}
