import { useState, type FormEvent } from "react";
import { Braces, Hash, Plus, ScanSearch, ShieldAlert, Sigma, Trash2, type LucideIcon } from "lucide-react";
import { api, ApiError } from "../../api";
import ModalClose from "../../components/ModalClose";
import { useDialogRef } from "../../hooks";
import type { ApprovedRoutine, ConnectionSummary, DiscoveredRoutines, RoutineKind } from "../../types";

/** Which stored procedures and functions a SQL Server connection lets reports call (api/app/routines.py). A report
 * author only ever picks one of these on a query card -- nobody types EXEC -- and the call is built on the server
 * from the approved name, its values bound. Discover lists what the connection's own login may run; it approves
 * nothing until it's ticked and saved. */

export const ROUTINE_KIND: Record<RoutineKind, { label: string; short: string; icon: LucideIcon; gives: string }> = {
  procedure: { label: "Stored procedure", short: "Procedure", icon: Sigma, gives: "its result sets" },
  table_function: { label: "Table-valued function", short: "Table function", icon: Braces, gives: "rows" },
  scalar_function: { label: "Scalar function", short: "Scalar function", icon: Hash, gives: "one value" },
};

/** "@branch nvarchar(10), @from date" -> parameters. */
function parseParameters(text: string): ApprovedRoutine["parameters"] {
  return text
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [name, ...type] = part.split(/\s+/);
      return { name: name.startsWith("@") ? name : `@${name}`, type: type.join(" ") || null };
    });
}

export const signature = (r: ApprovedRoutine) => `${r.name}(${r.parameters.map((p) => (p.type ? `${p.name} ${p.type}` : p.name)).join(", ")})`;

export default function RoutinesDialog({ connection, onClose, onSaved }: { connection: ConnectionSummary; onClose: () => void; onSaved: () => void }) {
  const ref = useDialogRef(true);
  const [approved, setApproved] = useState<ApprovedRoutine[]>(connection.routines ?? []);
  const [found, setFound] = useState<DiscoveredRoutines | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ name: string; kind: RoutineKind; params: string }>({ name: "", kind: "procedure", params: "" });

  const isApproved = (name: string) => approved.some((r) => r.name.toLowerCase() === name.toLowerCase());

  async function discover() {
    setDiscovering(true);
    setError(null);
    try {
      setFound(await api.connections.discoverRoutines(connection.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't read the catalog");
    } finally {
      setDiscovering(false);
    }
  }

  function toggle(routine: ApprovedRoutine, on: boolean) {
    setApproved((prev) => (on ? [...prev.filter((r) => r.name !== routine.name), routine] : prev.filter((r) => r.name.toLowerCase() !== routine.name.toLowerCase())));
  }

  function addTyped() {
    const name = draft.name.trim();
    if (!name) return;
    toggle({ name, kind: draft.kind, parameters: parseParameters(draft.params) }, true);
    setDraft({ name: "", kind: draft.kind, params: "" });
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.connections.setRoutines(connection.id, [...approved].sort((a, b) => a.name.localeCompare(b.name)));
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog ref={ref} className="modal conn-dialog conn-dialog-wide jdbc-dialog" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">Procedures &amp; functions</h2>
      <p className="panel-subtitle">
        What reports may call on <span className="mono">{connection.name}</span>. A report author picks one of these on a query card — nobody types{" "}
        <span className="mono">EXEC</span> — and every value is bound, never pasted into SQL. It runs on every run, preview and scheduled job.
      </p>
      <form onSubmit={save} className="grid gap-4">
        <section className="jdbc-section mb-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="jdbc-heading mb-0">Approved ({approved.length})</h3>
            <button type="button" className="btn btn-sm" onClick={discover} disabled={discovering}>
              {discovering ? <span className="spinner" /> : <ScanSearch size={14} aria-hidden="true" />} Discover
            </button>
          </div>
          {approved.length === 0 ? (
            <p className="field-hint">None yet. Press Discover to list what this connection's login may run, or type one in below.</p>
          ) : (
            <ul className="m-0 mt-2 grid list-none gap-1.5 p-0">
              {[...approved]
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((r) => {
                  const K = ROUTINE_KIND[r.kind];
                  return (
                    <li key={r.name} className="flex items-center gap-2.5 rounded-[10px] border border-border-soft bg-bg-raised px-3 py-2">
                      <K.icon size={15} className="shrink-0 text-accent-strong" aria-hidden="true" />
                      <div className="min-w-0 flex-1">
                        <div className="mono truncate text-[0.84rem]">{signature(r)}</div>
                        <div className="text-[0.74rem] text-text-faint">
                          {K.label} — gives {K.gives}
                        </div>
                      </div>
                      <button type="button" className="btn btn-ghost btn-sm icon-only" aria-label={`Withdraw ${r.name}`} onClick={() => toggle(r, false)}>
                        <Trash2 size={14} />
                      </button>
                    </li>
                  );
                })}
            </ul>
          )}
        </section>

        {found && (
          <section className="jdbc-section mb-0">
            <h3 className="jdbc-heading">What {connection.name}'s login may run</h3>
            {found.can_write && (
              <p className="alert alert-warning m-0 mb-2.5 flex items-start gap-2">
                <ShieldAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
                <span>
                  This login can also change data (it writes, owns or alters the database). A procedure approved here could then change data
                  whenever a report runs. Give reports a login that can only <span className="mono">EXECUTE</span> these routines and read.
                </span>
              </p>
            )}
            {found.routines.length === 0 ? (
              <p className="field-hint">It may run none. Grant it EXECUTE (procedures, scalar functions) or SELECT (table-valued functions) first.</p>
            ) : (
              <div className="grid gap-1">
                {found.routines.map((r) => {
                  const K = ROUTINE_KIND[r.kind];
                  return (
                    <label key={r.name} className="checkbox-label mb-0 items-start rounded-md px-1.5 py-1 hover:bg-bg-panel">
                      <input type="checkbox" checked={isApproved(r.name)} onChange={(e) => toggle(r, e.target.checked)} />
                      <span className="min-w-0">
                        <span className="mono block truncate text-[0.84rem] text-text">{signature(r)}</span>
                        <span className="text-[0.74rem] text-text-faint">{K.label}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
            {found.skipped_output.length > 0 && (
              <p className="field-hint mt-2">
                Not offered — they have OUTPUT parameters, which reports can't use: <span className="mono">{found.skipped_output.join(", ")}</span>
              </p>
            )}
          </section>
        )}

        <section className="jdbc-section mb-0">
          <h3 className="jdbc-heading">Or type one in</h3>
          <div className="grid grid-cols-1 gap-x-3 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,0.9fr)_minmax(0,1.6fr)_auto] sm:items-end">
            <label>
              <span>Name (schema.name)</span>
              <input type="text" className="mono-input" placeholder="dbo.GetSalesByBranch" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </label>
            <label>
              <span>Kind</span>
              <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as RoutineKind })}>
                {(Object.keys(ROUTINE_KIND) as RoutineKind[]).map((k) => (
                  <option key={k} value={k}>
                    {ROUTINE_KIND[k].label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Parameters, in order</span>
              <input type="text" className="mono-input" placeholder="@branch nvarchar(10), @from date" value={draft.params} onChange={(e) => setDraft({ ...draft, params: e.target.value })} />
            </label>
            <button type="button" className="btn mb-3.5" onClick={addTyped} disabled={!draft.name.trim()}>
              <Plus size={14} aria-hidden="true" /> Add
            </button>
          </div>
          <p className="field-hint m-0">Discover is easier and gets the parameters right; typing is for a login that can't read the catalog.</p>
        </section>

        {error && <p className="alert alert-error m-0">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving && <span className="spinner" />}
            Save
          </button>
        </div>
      </form>
    </dialog>
  );
}
