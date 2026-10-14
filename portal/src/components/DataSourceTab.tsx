import { useEffect, useState } from "react";
import { Cable, Database, DatabaseZap, FlaskConical, Layers } from "lucide-react";
import { api, ApiError } from "../api";
import { sourceConfigured, type DataConfigDraft, type EditableSource } from "../dataConfig";
import type { DatasetSummary, DataSourceType } from "../types";
import ConfirmDialog from "./ConfirmDialog";
import DataConfigSaveBar from "./DataConfigSaveBar";
import JdbcSourceFields from "./JdbcSourceFields";
import RequestFields from "./RequestFields";
import { LinesSkeleton } from "./Skeletons";
import StaticSourceFields from "./StaticSourceFields";

const TYPES: { id: DataSourceType; label: string; blurb: string; icon: typeof Cable; name: string }[] = [
  { id: "static", label: "Sample data", blurb: "Fixed JSON — to design a template and show it before real data exists", icon: FlaskConical, name: "sample data" },
  { id: "rest", label: "REST API", blurb: "Call an HTTP endpoint that answers with a JSON object", icon: Cable, name: "REST API" },
  { id: "jdbc", label: "Database", blurb: "Run a read-only SQL query on Oracle, PostgreSQL, MySQL, SQL Server, MariaDB or Db2", icon: Database, name: "database" },
  { id: "dataset", label: "A dataset", blurb: "Share a dataset's source, filters and measures with other reports", icon: Layers, name: "dataset" },
];

const nameOf = (type: DataSourceType) => TYPES.find((t) => t.id === type)?.name ?? type;

/** What would be lost, in a few words -- shown in the warning before a source is switched away from. */
function describeLoss(source: EditableSource): string {
  if (source.type === "dataset") return source.dataset ? `dataset “${source.dataset}”` : "";
  if (source.type === "jdbc") {
    const queries = source.jdbc.queries;
    const query = queries[0].query.trim().replace(/\s+/g, " ");
    return [
      source.jdbc.connection && `connection “${source.jdbc.connection}”`,
      queries.length > 1 ? `its ${queries.length} queries` : query && `the query “${query.length > 48 ? `${query.slice(0, 48)}…` : query}”`,
    ]
      .filter(Boolean)
      .join(" and ");
  }
  if (source.type === "static") return `${source.staticText.trim().length.toLocaleString()} characters of sample data`;
  const r = source.request;
  return [r.connection && `connection “${r.connection}”`, r.url.trim() && `the URL “${r.url.trim().length > 48 ? `${r.url.trim().slice(0, 48)}…` : r.url.trim()}”`, r.headersText.trim() && "its headers", r.authType !== "none" && "its authentication"]
    .filter(Boolean)
    .join(", ");
}

type Pending = { kind: "type"; type: DataSourceType } | { kind: "off" };

/** The template page's "Data source" tab: where the *server* gets this report's
 * data when someone runs it -- after checking their access to the values they
 * picked. Separate from Parameters (what a person is asked for) because a
 * source is its own thing, of three kinds: fixed sample data (to build a
 * template before any real source exists), a REST API, or a database query.
 * Reaching either through a connection (Admin > Connections) means a moved
 * host is one edit there, not one per report.
 *
 * Switching kind throws the old kind's settings away (they mean nothing to the
 * new one), so when there's something to lose it asks first -- see `pending`. */
/** The dataset a report is built on: pick one, see what it brings. */
function DatasetPicker({ value, onChange }: { value: string; onChange: (name: string) => void }) {
  const [list, setList] = useState<DatasetSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.datasets
      .list()
      .then(setList)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the datasets"));
  }, []);
  const chosen = list?.find((d) => d.name === value);
  return (
    <div className="mt-3.5 grid gap-2.5">
      <label className="mb-0">
        <span>Dataset</span>
        <select value={value} required onChange={(e) => onChange(e.target.value)} disabled={list === null}>
          <option value="" disabled>
            {list === null ? "Loading…" : list.length ? "Choose a dataset…" : "No dataset yet"}
          </option>
          {value && list && !chosen && <option value={value}>{value} (not found)</option>}
          {list?.map((d) => (
            <option key={d.id} value={d.name}>
              {d.title} · {d.name}
            </option>
          ))}
        </select>
      </label>
      {error && <p className="alert alert-error">{error}</p>}
      {chosen && (
        <p className="field-hint m-0">
          {chosen.description ? `${chosen.description.trim().replace(/[.!?។]?$/, (end) => end || ".")} ` : ""}It brings {chosen.parameter_count} filter{chosen.parameter_count === 1 ? "" : "s"},{" "}
          {chosen.measure_count} measure{chosen.measure_count === 1 ? "" : "s"} (in a template: <code className="mono">{"{{ measures.<key> }}"}</code>), and
          its data. This report's own filters give way to the dataset's.
          {chosen.access_mode === "restricted" && " Its access is restricted: only the people and roles it lists can run this report, and only with their values."}
        </p>
      )}
      {list !== null && list.length === 0 && (
        <p className="field-hint m-0">
          Make one under <a href="#/admin/datasets">Manage → Datasets</a>, or save this report's own source as a dataset.
        </p>
      )}
    </div>
  );
}

/** Make this report's own source and filters into a dataset, and build the report on it. */
function SaveAsDataset({ reportId, reportName, onDone }: { reportId: string; reportName: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(reportName);
  const [name, setName] = useState(reportName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "dataset");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!open) {
    return (
      <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>
        <DatabaseZap size={14} aria-hidden="true" /> Save this report's data as a dataset
      </button>
    );
  }
  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.datasets.fromReport(reportId, name.trim(), title.trim());
      setOpen(false);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't make the dataset");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="grid gap-2.5 rounded-[12px] border border-border-soft p-3.5">
      <p className="m-0 text-[0.85rem] text-text-dim">
        This report's source and filters become a dataset that other reports can share, and this report is built on it — it runs exactly as now.
      </p>
      <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
        <label className="mb-0">
          <span>Title</span>
          <input type="text" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="mb-0">
          <span>Name (used in reports)</span>
          <input type="text" className="mono-input" maxLength={64} pattern="[a-z0-9]+([\-_][a-z0-9]+)*" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
      </div>
      {error && <p className="alert alert-error m-0">{error}</p>}
      <div className="flex gap-2">
        <button type="button" className="btn btn-primary btn-sm" onClick={save} disabled={busy || !title.trim() || !name.trim()}>
          {busy && <span className="spinner" />} Make the dataset
        </button>
        <button type="button" className="btn btn-sm" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function DataSourceTab({
  draft,
  canManageConnections,
  canManageSecrets,
  orgId,
  forDataset = false,
  report,
  canManageDatasets = false,
}: {
  draft: DataConfigDraft;
  canManageConnections: boolean;
  canManageSecrets: boolean;
  orgId: string;
  /** In a dataset's own editor: it always has a source, and can't be built on another dataset. */
  forDataset?: boolean;
  /** The report whose source this is -- offers "save as a dataset". */
  report?: { report_id: string; name: string };
  canManageDatasets?: boolean;
}) {
  const [pending, setPending] = useState<Pending | null>(null);

  if (draft.status === "idle" || draft.status === "loading") {
    return (
      <div className="panel data-config">
        <h2 className="panel-title">Data source</h2>
        <LinesSkeleton count={4} />
      </div>
    );
  }

  const filterDefs = draft.parameters
    .filter((p) => p.name.trim())
    .map((p) => ({ name: p.name.trim(), type: p.kind === "text" ? p.textType : "text" }));
  const filters = filterDefs.map((f) => f.name);
  const { source } = draft;
  const configured = sourceConfigured(source);
  const restConnections = draft.connections?.filter((c) => c.kind === "rest") ?? null;
  const jdbcConnections = draft.connections?.filter((c) => c.kind === "jdbc") ?? null;

  function requestType(type: DataSourceType) {
    if (type === source.type) return;
    if (configured) setPending({ kind: "type", type });
    else draft.setSourceType(type);
  }

  function requestOff(on: boolean) {
    if (on || !configured) draft.setUseSource(on);
    else setPending({ kind: "off" });
  }

  function confirm() {
    if (pending?.kind === "type") draft.setSourceType(pending.type);
    if (pending?.kind === "off") draft.setUseSource(false);
    setPending(null);
  }

  const loss = describeLoss(source);
  const saved = draft.savedSource ? " It's saved on the report now, so this takes effect when you save." : "";
  const warning =
    pending?.kind === "type"
      ? `This report's ${nameOf(source.type)} source${loss ? ` (${loss})` : ""} has settings that don't carry over to ${nameOf(pending.type)}. ` +
        `Switching removes them from the form, and from the report when you save.${saved}`
      : pending?.kind === "off"
        ? `This report's ${nameOf(source.type)} source${loss ? ` (${loss})` : ""} will be removed when you save, and the report will render from its filter values alone.${saved}`
        : "";

  return (
    <div className="panel data-config">
      <h2 className="panel-title">{forDataset ? "Source" : "Data source"}</h2>
      <p className="panel-subtitle">
        {forDataset
          ? "Where this dataset's data comes from. Every report built on it reads through here, after the person's access to the values they picked has been checked."
          : "Where the server gets this report's data when it's run. It's only called after the person's access to the values they picked has been checked."}
      </p>

      {draft.loadError && <p className="alert alert-error">{draft.loadError}</p>}

      <section className="data-config-section">
        {!forDataset && (
          <label className="checkbox-label data-config-toggle">
            <input type="checkbox" checked={draft.useSource} onChange={(e) => requestOff(e.target.checked)} />
            <span>Get this report's data from a source when it's run</span>
          </label>
        )}
        {!draft.useSource && !forDataset && (
          <p className="field-hint">
            Without one, the report is rendered from the filter values alone (the API's public render route is unaffected either way).
          </p>
        )}

        {draft.useSource && (
          <>
            <div className="source-types" role="radiogroup" aria-label="Kind of data source">
              {TYPES.filter((t) => !(forDataset && t.id === "dataset")).map(({ id, label, blurb, icon: Icon }) => (
                <label key={id} className={`source-type${source.type === id ? " selected" : ""}`}>
                  <input type="radio" name="source-type" value={id} checked={source.type === id} onChange={() => requestType(id)} />
                  <Icon size={20} aria-hidden="true" />
                  <span className="source-type-label">{label}</span>
                  <span className="source-type-blurb">{blurb}</span>
                </label>
              ))}
            </div>

            {source.type === "static" && (
              <StaticSourceFields text={source.staticText} onChange={draft.setStaticText} error={draft.staticError} />
            )}

            {source.type === "rest" && (
              <>
                <RequestFields
                  value={source.request}
                  onChange={draft.updateRequest}
                  connections={restConnections}
                  connectionsAvailable={draft.connectionsAvailable}
                  canManageConnections={canManageConnections}
                  canManageSecrets={canManageSecrets}
                  orgId={orgId}
                  placeholders={filters}
                  bodyHint="Request body (JSON or text; {{ name }} works inside string values)"
                  urlExample={`https://erp.example.com/api/sales${filters[0] ? `?${filters[0]}={{ ${filters[0]} }}` : ""}`}
                />
                <p className="field-hint data-config-hint">The response must be a JSON object; its keys become the template's fields.</p>
              </>
            )}

            {source.type === "dataset" && <DatasetPicker value={source.dataset} onChange={draft.setDataset} />}

            {source.type === "jdbc" && (
              <JdbcSourceFields
                value={source.jdbc}
                onChange={draft.updateJdbc}
                connections={jdbcConnections}
                connectionsAvailable={draft.connectionsAvailable}
                canManageConnections={canManageConnections}
                filters={filterDefs}
              />
            )}
          </>
        )}
      </section>

      {report && canManageDatasets && draft.savedSource && !draft.sourceDirty && draft.useSource && source.type !== "dataset" && (
        <div className="mt-4">
          <SaveAsDataset reportId={report.report_id} reportName={report.name} onDone={draft.reload} />
        </div>
      )}

      <DataConfigSaveBar draft={draft} here="source" />

      <ConfirmDialog
        open={pending !== null}
        title={pending?.kind === "off" ? "Remove the data source?" : `Switch to ${pending?.kind === "type" ? nameOf(pending.type) : ""}?`}
        body={warning}
        confirmLabel={pending?.kind === "off" ? "Remove source" : "Switch and discard"}
        onConfirm={confirm}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}
