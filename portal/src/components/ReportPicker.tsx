import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { ReportMeta } from "../types";

/** A checklist of reports to grant an API client — shared by the create dialog
 * (ClientFormDialog) and the existing-client Reports tab (ClientReportsPanel),
 * so both scale the same way as the template list grows: a live search (name,
 * code, or format), select-all/clear scoped to whatever's currently filtered
 * rather than the whole list, and a running count so a long grant is easy to
 * review before saving. The list itself was already a fixed-height scroll
 * area; search is what makes that height still usable once there are more
 * reports than fit in it. */
export default function ReportPicker({
  reports,
  selected,
  onToggle,
  onSelectMany,
}: {
  reports: ReportMeta[];
  selected: Set<string>;
  onToggle: (reportId: string) => void;
  /** Replace the whole selection -- used by "Select all"/"Clear", scoped to the filtered set. */
  onSelectMany: (reportIds: string[]) => void;
}) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return reports;
    return reports.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        (r.code ?? "").toLowerCase().includes(q) ||
        (r.description ?? "").toLowerCase().includes(q) ||
        r.template_ext.includes(q)
    );
  }, [reports, query]);

  const allFilteredSelected = filtered.length > 0 && filtered.every((r) => selected.has(r.report_id));

  function selectAllFiltered() {
    const next = new Set(selected);
    filtered.forEach((r) => next.add(r.report_id));
    onSelectMany(Array.from(next));
  }

  function clearFiltered() {
    const filteredIds = new Set(filtered.map((r) => r.report_id));
    onSelectMany(Array.from(selected).filter((id) => !filteredIds.has(id)));
  }

  if (reports.length === 0) {
    return <p className="muted" style={{ fontSize: "0.85rem" }}>No reports in this organization yet.</p>;
  }

  return (
    <div className="report-picker">
      <div className="report-picker-toolbar">
        <div className="search search-icon-field">
          <Search size={14} className="search-icon" aria-hidden="true" />
          <input
            type="text"
            placeholder="Filter by name, code or format…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <button type="button" className="link-btn" onClick={allFilteredSelected ? clearFiltered : selectAllFiltered} disabled={filtered.length === 0}>
          {allFilteredSelected ? "Clear" : query ? "Select filtered" : "Select all"}
        </button>
      </div>

      <div className="report-pick" role="group" aria-label="Reports it may run">
        {filtered.length === 0 ? (
          <p className="muted report-pick-empty">No reports match “{query}”.</p>
        ) : (
          filtered.map((r) => (
            <label key={r.report_id} className="permission-row">
              <input type="checkbox" checked={selected.has(r.report_id)} onChange={() => onToggle(r.report_id)} />
              <span className={`badge badge-${r.template_ext}`}>{r.template_ext}</span>
              <span className="report-pick-name">
                {r.name}
                {/* The report's own description, shown in full -- not clamped, unlike the
                    gallery/reports cards -- since this is what decides whether to grant it. */}
                {r.description && <span className="muted report-pick-summary">{r.description}</span>}
                <span className="muted permission-desc mono">{r.code ?? r.report_id}</span>
              </span>
            </label>
          ))
        )}
      </div>

      <p className="field-hint report-picker-count">
        {selected.size === 0 ? "None selected" : `${selected.size} report${selected.size === 1 ? "" : "s"} selected`}
        {query && filtered.length !== reports.length ? ` — showing ${filtered.length} of ${reports.length}` : ""}
      </p>
    </div>
  );
}
