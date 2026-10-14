import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Eye, EyeOff, Layers, Lock, Play, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import DataSourceTab from "../../components/DataSourceTab";
import SourceRunError, { toRunFailure, type RunFailure } from "../../components/SourceRunError";
import ParametersTab from "../../components/ParametersTab";
import { TableSkeleton } from "../../components/Skeletons";
import { toDataSource, toParameter, useDataConfigDraft, type DataConfigIO } from "../../dataConfig";
import type { AuthInfo, DataConfig, Dataset, DatasetField, DatasetMeasure, DatasetPreview, DatasetSummary, FieldType, MeasureKind } from "../../types";
import { has } from "../sections";
import DatasetAccessTab from "./DatasetAccessTab";

/** Manage → Datasets: a governed source, its filters, what its fields mean and its named measures -- defined once,
 * built on by many reports (api/app/datasets.py). The Source and Filters tabs are the very ones a report's own data
 * source uses (DataSourceTab, ParametersTab), here loading from and saving to the dataset. */

const TYPE_LABEL: Record<FieldType, string> = { text: "Text", number: "Number", money: "Money", date: "Date", datetime: "Date & time", boolean: "Yes / no" };
const TYPE_TONE: Record<FieldType, string> = {
  text: "bg-bg-panel text-text-dim",
  number: "bg-accent-soft text-accent-strong",
  money: "bg-success-soft text-success",
  date: "bg-highlight-soft text-highlight",
  datetime: "bg-highlight-soft text-highlight",
  boolean: "bg-bg-panel text-text-dim",
};
const KIND_LABEL: Record<MeasureKind, string> = {
  sum: "Sum",
  count: "Count of rows",
  count_distinct: "Count distinct",
  avg: "Average",
  min: "Minimum",
  max: "Maximum",
  ratio: "Ratio of two measures",
};
const FORMATS = ["#,##0", "#,##0.00", "#,##0 ៛", "#,##0.00 ៛", "$#,##0.00", "0%", "0.0%", "DD/MM/YYYY"];

type Tab = "source" | "filters" | "fields" | "measures" | "access" | "used";

const keyOf = (label: string) =>
  label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^(\d)/, "m_$1")
    .slice(0, 64) || "measure";

function formula(m: DatasetMeasure, measures: DatasetMeasure[]): string {
  const name = (key: string | null) => measures.find((x) => x.key === key)?.label ?? key ?? "?";
  if (m.kind === "ratio") return `${name(m.numerator)} ÷ ${name(m.denominator)}`;
  const inner = m.kind === "count" ? (m.field ? `${m.field} filled in` : "rows") : (m.field ?? "?");
  const fn = { sum: "SUM", count: "COUNT", count_distinct: "COUNT DISTINCT", avg: "AVG", min: "MIN", max: "MAX" }[m.kind];
  return `${fn}(${inner})${m.where ? ` where ${m.where.field} = ${m.where.value}` : ""}`;
}

// --- the list ---------------------------------------------------------------------------------------------------

export default function DatasetsPage({ auth }: { auth: AuthInfo }) {
  const [list, setList] = useState<DatasetSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | "new" | null>(null);

  function load() {
    api.datasets
      .list()
      .then((l) => {
        setList(l);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the datasets"));
  }
  useEffect(load, []);

  if (open) {
    return (
      <DatasetEditor
        key={open}
        id={open === "new" ? null : open}
        auth={auth}
        onClose={() => {
          setOpen(null);
          load();
        }}
        onCreated={(id) => setOpen(id)}
      />
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Datasets</h1>
          <p className="page-subtitle">
            A dataset is the one place a body of data is defined — its source, its filters, what each field means (in English and Khmer) and named
            measures like <em>Net sales</em>. Reports built on it share all of that, so a change here reaches every one of them.
          </p>
        </div>
        <div className="page-header-actions">
          <button type="button" className="btn btn-primary" onClick={() => setOpen("new")}>
            <Plus size={15} aria-hidden="true" /> New Dataset
          </button>
        </div>
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {list === null && !error && <TableSkeleton columns={["Dataset", "Source", "Filters", "Fields", "Measures", "Used by", "Access"]} />}
      {list !== null && list.length === 0 && (
        <div className="empty-state conn-empty">
          <Layers size={30} strokeWidth={1.4} aria-hidden="true" />
          <p>No datasets yet.</p>
          <p className="muted">
            Make one here from a source, or open a report's Data source tab and choose <em>Save this report's data as a dataset</em> — the report keeps
            running exactly as it does, and the next report can share it.
          </p>
        </div>
      )}
      {list !== null && list.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Dataset</th>
              <th>Source</th>
              <th>Filters</th>
              <th>Fields</th>
              <th>Measures</th>
              <th>Used by</th>
              <th>Access</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {list.map((d) => (
              <tr key={d.id} onClick={() => setOpen(d.id)}>
                <td>
                  <div className="font-semibold">{d.title}</div>
                  <div className="mono muted text-[0.75rem]">{d.name}</div>
                </td>
                <td className="muted">
                  {{ jdbc: "Database", rest: "REST API", static: "Sample data" }[d.source_type] ?? d.source_type}
                  {d.connection && <span className="mono"> · {d.connection}</span>}
                </td>
                <td className="mono">{d.parameter_count}</td>
                <td className="mono">{d.field_count}</td>
                <td className="mono">{d.measure_count}</td>
                <td className="mono">{d.report_count === 0 ? <span className="muted">none</span> : `${d.report_count} report${d.report_count === 1 ? "" : "s"}`}</td>
                <td>
                  {d.access_mode === "restricted" ? (
                    <span className="inline-flex items-center gap-1 text-[0.82rem]">
                      <Lock size={13} aria-hidden="true" /> {d.grant_count} grant{d.grant_count === 1 ? "" : "s"}
                    </span>
                  ) : (
                    <span className="muted">Open</span>
                  )}
                </td>
                <td className="muted">{new Date(d.updated_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// --- one dataset ----------------------------------------------------------------------------------------------------

function DatasetEditor({ id, auth, onClose, onCreated }: { id: string | null; auth: AuthInfo; onClose: () => void; onCreated: (id: string) => void }) {
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [title, setTitle] = useState("");
  const [name, setName] = useState("");
  const [nameEdited, setNameEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [fields, setFields] = useState<DatasetField[]>([]);
  const [measures, setMeasures] = useState<DatasetMeasure[]>([]);
  const [baseline, setBaseline] = useState("");
  const [tab, setTab] = useState<Tab>("source");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const orgId = auth.orgId ?? "root";

  // What the draft's save sends besides its own source + filters: read at save time, so the latest edits go.
  const extras = useRef({ title, name, description, fields, measures });
  extras.current = { title, name, description, fields, measures };

  const io = useMemo<DataConfigIO>(
    () => ({
      load: async (): Promise<DataConfig> => {
        if (!id) return { parameters: [], data_source: { type: "jdbc", connection: null, url: "", method: "GET", headers: null, body_template: null, auth: null, queries: null } };
        const d = await api.datasets.get(id);
        setDataset(d);
        setTitle(d.title);
        setName(d.name);
        setDescription(d.description ?? "");
        setFields(d.fields);
        setMeasures(d.measures);
        setBaseline(JSON.stringify({ title: d.title, description: d.description ?? "", fields: d.fields, measures: d.measures }));
        return { parameters: d.parameters, data_source: d.data_source };
      },
      save: async (config: DataConfig): Promise<DataConfig> => {
        const x = extras.current;
        if (!config.data_source) throw new ApiError(400, "A dataset needs a source");
        const body = {
          title: x.title.trim(),
          description: x.description.trim() || null,
          parameters: config.parameters,
          data_source: config.data_source,
          fields: x.fields,
          measures: x.measures,
        };
        const saved = id ? await api.datasets.update(id, body) : await api.datasets.create({ ...body, name: x.name.trim(), org_id: orgId });
        setDataset(saved);
        setFields(saved.fields);
        setMeasures(saved.measures);
        setBaseline(JSON.stringify({ title: saved.title, description: saved.description ?? "", fields: saved.fields, measures: saved.measures }));
        if (!id) onCreated(saved.id);
        return { parameters: saved.parameters, data_source: saved.data_source };
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- created once per dataset
    [id],
  );
  const draft = useDataConfigDraft(`dataset:${id ?? "new"}`, true, io);
  useEffect(() => {
    if (draft.status === "error") setLoadError(draft.loadError);
    if (!id && draft.status === "ready" && !draft.useSource) draft.setUseSource(true);
  }, [draft.status, draft.loadError, id, draft]);

  const ownDirty = JSON.stringify({ title, description, fields, measures }) !== baseline;
  const dirty = draft.parametersDirty || draft.sourceDirty || ownDirty || !id;

  const lists = useMemo(() => [...new Set(fields.map((f) => f.source).filter((s): s is string => !!s))], [fields]);

  if (loadError) return <p className="alert alert-error">{loadError}</p>;

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "source", label: "Source" },
    { id: "filters", label: "Filters", count: draft.parameters.length },
    { id: "fields", label: "Fields", count: fields.length },
    { id: "measures", label: "Measures", count: measures.length },
    ...(dataset ? [{ id: "access" as const, label: dataset.access_mode === "restricted" ? "Access · restricted" : "Access" }] : []),
    { id: "used", label: "Used by", count: dataset?.reports.length ?? 0 },
  ];

  return (
    <div className="grid gap-4">
      <button type="button" className="link-btn inline-flex items-center gap-1.5 justify-self-start text-[0.85rem]" onClick={onClose}>
        <ArrowLeft size={14} aria-hidden="true" /> All datasets
      </button>

      <div className="page-header">
        <div className="min-w-0 flex-1">
          <h1 className="page-title">{title || (id ? "Dataset" : "New dataset")}</h1>
          {dataset && <p className="mono muted m-0 text-[0.8rem]">{dataset.name}</p>}
        </div>
        <div className="page-header-actions">
          {id && (
            <button type="button" className="btn btn-danger" onClick={() => setDeleteOpen(true)}>
              <Trash2 size={14} aria-hidden="true" /> Delete
            </button>
          )}
          <button type="button" className="btn btn-primary" onClick={() => draft.save()} disabled={draft.saving || !dirty || !title.trim() || (!id && !name.trim())}>
            {draft.saving && <span className="spinner" />}
            {id ? "Save changes" : "Create dataset"}
          </button>
        </div>
      </div>
      {draft.saveError && <p className="alert alert-error m-0">{draft.saveError}</p>}
      {draft.saved && !dirty && <p className="alert alert-success m-0">Saved. Reports built on it use this from their next run.</p>}
      {deleteError && <p className="alert alert-error m-0">{deleteError}</p>}

      <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,2fr)]">
        <label>
          <span>Title</span>
          <input
            type="text"
            maxLength={120}
            value={title}
            placeholder="Branch sales"
            onChange={(e) => {
              setTitle(e.target.value);
              if (!id && !nameEdited) setName(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
            }}
          />
        </label>
        <label>
          <span>Name (used in reports)</span>
          {id ? (
            <input type="text" className="mono-input" value={name} readOnly aria-readonly="true" />
          ) : (
            <input
              type="text"
              className="mono-input"
              maxLength={64}
              pattern="[a-z0-9]+([\-_][a-z0-9]+)*"
              value={name}
              placeholder="branch-sales"
              onChange={(e) => {
                setNameEdited(true);
                setName(e.target.value);
              }}
            />
          )}
        </label>
        <label>
          <span>
            Description <span className="muted">(optional)</span>
          </span>
          <input type="text" maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Every sale line with its branch, product and customer" />
        </label>
      </div>

      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className={`tab ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
            {t.count !== undefined && <span className="ml-1.5 rounded-full bg-bg-panel px-1.5 text-[0.72rem] text-text-dim">{t.count}</span>}
          </button>
        ))}
      </div>

      {tab === "source" && (
        <DataSourceTab draft={draft} canManageConnections={has(auth, "connection:manage")} canManageSecrets={has(auth, "secret:manage")} orgId={orgId} forDataset />
      )}
      {tab === "filters" && (
        <ParametersTab
          draft={draft}
          canManageConnections={has(auth, "connection:manage")}
          canManageSecrets={has(auth, "secret:manage")}
          orgId={orgId}
          tryOptions={(source) => api.datasets.previewOptions(source, orgId)}
        />
      )}
      {(tab === "fields" || tab === "measures") && (
        <PreviewBar
          draft={draft}
          fields={fields}
          measures={measures}
          orgId={orgId}
          onResult={(p) => {
            setPreview(p);
            if (!p.missing.length) setFields(p.fields);
          }}
        />
      )}
      {tab === "fields" && <FieldsTable fields={fields} onChange={setFields} />}
      {tab === "measures" && <MeasuresEditor measures={measures} onChange={setMeasures} fields={fields} lists={lists} results={preview?.measures ?? {}} />}
      {tab === "access" && dataset && <DatasetAccessTab dataset={dataset} onModeChange={(mode) => setDataset({ ...dataset, access_mode: mode })} />}
      {tab === "used" && (
        <div className="grid gap-2">
          {(dataset?.reports ?? []).length === 0 ? (
            <p className="muted">No report is built on it yet. On a report's Data source tab, choose <em>A dataset</em>.</p>
          ) : (
            dataset!.reports.map((r) => (
              <a key={r.report_id} href={`#/reports/${encodeURIComponent(r.code ?? r.report_id)}/data-source`} className="rounded-[10px] border border-border-soft px-3.5 py-2.5 text-text no-underline hover:border-accent-border">
                <b className="font-semibold">{r.name}</b> {r.code && <span className="mono muted text-[0.8rem]">{r.code}</span>}
              </a>
            ))
          )}
          <p className="field-hint">A change to the source, a filter, a field or a measure reaches all of them on their next run.</p>
        </div>
      )}

      <ConfirmDialog
        open={deleteOpen}
        title="Delete dataset"
        body={`Delete “${title}”? This can't be undone. It's refused while a report is built on it.`}
        confirmLabel="Delete"
        onConfirm={async () => {
          setDeleteOpen(false);
          try {
            await api.datasets.delete(id!);
            onClose();
          } catch (err) {
            setDeleteError(err instanceof ApiError ? err.message : "Couldn't delete it");
          }
        }}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}

// --- run it once ----------------------------------------------------------------------------------------------------

function PreviewBar({
  draft,
  fields,
  measures,
  orgId,
  onResult,
}: {
  draft: ReturnType<typeof useDataConfigDraft>;
  fields: DatasetField[];
  measures: DatasetMeasure[];
  orgId: string;
  onResult: (p: DatasetPreview) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [failure, setFailure] = useState<RunFailure | null>(null);
  const [last, setLast] = useState<DatasetPreview | null>(null);
  const params = draft.parameters.filter((p) => p.name.trim());

  async function run() {
    setRunning(true);
    setFailure(null);
    try {
      const result = await api.datasets.preview({
        org_id: orgId,
        parameters: draft.parameters.map(toParameter),
        data_source: toDataSource(draft.source),
        fields,
        measures,
        values,
      });
      setLast(result);
      onResult(result);
    } catch (err) {
      setFailure(toRunFailure(err, "Couldn't run it"));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="grid gap-2.5 rounded-[12px] border border-border-soft bg-bg-raised p-3.5">
      <div className="flex flex-wrap items-end gap-3">
        {params.map((p) => {
          const key = p.name.trim();
          const options = p.kind === "choices" && p.choicesFrom === "list" ? (toParameter(p).options ?? []) : null;
          const change = (value: string) => setValues((v) => ({ ...v, [key]: value }));
          return (
            <label key={p.key} className="mb-0 min-w-[9rem]">
              <span>{p.label || p.name}</span>
              {options ? (
                <select value={values[key] ?? ""} onChange={(e) => change(e.target.value)}>
                  <option value="">Choose…</option>
                  {options.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label ?? o.value}
                    </option>
                  ))}
                </select>
              ) : (
                <input type="text" value={values[key] ?? ""} placeholder="test value" onChange={(e) => change(e.target.value)} />
              )}
            </label>
          );
        })}
        <button type="button" className="btn" onClick={run} disabled={running}>
          {running ? <span className="spinner" /> : <Play size={14} aria-hidden="true" />} Run it
        </button>
        <span className="muted text-[0.8rem]">
          {last && !last.missing.length
            ? `${last.elapsed_ms} ms — fields found and measures worked out from this run`
            : "Runs the source once with these values: finds the fields and works out each measure. Nothing is saved."}
        </span>
      </div>
      {last?.missing.length ? <p className="alert alert-warning m-0">It needs a test value for {last.missing.join(", ")} first.</p> : null}
      {failure && !running && <SourceRunError failure={failure} kind={draft.source.type} onRetry={run} />}
    </div>
  );
}

// --- fields ---------------------------------------------------------------------------------------------------------

function FieldsTable({ fields, onChange }: { fields: DatasetField[]; onChange: (f: DatasetField[]) => void }) {
  const set = (i: number, patch: Partial<DatasetField>) => onChange(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  if (!fields.length) {
    return <p className="muted">No fields yet. Press <b>Run it</b> above: every column the source returns is listed here, to name and format.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-[12px] border border-border-soft">
      <datalist id="dataset-formats">
        {FORMATS.map((f) => (
          <option key={f} value={f} />
        ))}
      </datalist>
      <table className="data-table static-rows min-w-[820px]">
        <thead>
          <tr>
            <th>Column</th>
            <th>Type</th>
            <th>Label</th>
            <th>Label (ខ្មែរ)</th>
            <th>Shown as</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {fields.map((f, i) => (
            <tr key={`${f.source}.${f.name}`} className={f.hidden ? "opacity-50" : ""}>
              <td className="mono text-[0.8rem]">
                {f.source && <span className="text-text-faint">{f.source}.</span>}
                {f.name}
              </td>
              <td>
                <select value={f.type} onChange={(e) => set(i, { type: e.target.value as FieldType })} className={`min-w-[7.5rem] rounded-md px-1.5 py-1 text-[0.78rem] ${TYPE_TONE[f.type]}`} aria-label={`Type of ${f.name}`}>
                  {(Object.keys(TYPE_LABEL) as FieldType[]).map((t) => (
                    <option key={t} value={t}>
                      {TYPE_LABEL[t]}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input type="text" maxLength={100} value={f.label ?? ""} placeholder={f.name} onChange={(e) => set(i, { label: e.target.value || null })} aria-label={`Label for ${f.name}`} />
              </td>
              <td>
                <input type="text" maxLength={100} value={f.label_km ?? ""} onChange={(e) => set(i, { label_km: e.target.value || null })} aria-label={`Khmer label for ${f.name}`} />
              </td>
              <td>
                <input type="text" list="dataset-formats" maxLength={40} value={f.format ?? ""} placeholder="As is" onChange={(e) => set(i, { format: e.target.value || null })} aria-label={`Format for ${f.name}`} />
              </td>
              <td>
                <button type="button" className="btn btn-ghost btn-sm icon-only" aria-pressed={!f.hidden} title={f.hidden ? "Hidden from report authors" : "Visible"} onClick={() => set(i, { hidden: !f.hidden })}>
                  {f.hidden ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- measures -------------------------------------------------------------------------------------------------------

const EMPTY_MEASURE: DatasetMeasure = { key: "", label: "", label_km: null, kind: "sum", source: null, field: null, where: null, numerator: null, denominator: null, format: null };

function MeasuresEditor({
  measures,
  onChange,
  fields,
  lists,
  results,
}: {
  measures: DatasetMeasure[];
  onChange: (m: DatasetMeasure[]) => void;
  fields: DatasetField[];
  lists: string[];
  results: Record<string, { text: string; value: number | null }>;
}) {
  const [editing, setEditing] = useState<{ index: number | null; m: DatasetMeasure } | null>(null);
  const [keyEdited, setKeyEdited] = useState(false);

  function commit() {
    if (!editing) return;
    const m = { ...editing.m, key: editing.m.key || keyOf(editing.m.label) };
    onChange(editing.index === null ? [...measures, m] : measures.map((x, i) => (i === editing.index ? m : x)));
    setEditing(null);
  }

  const m = editing?.m;
  const set = (patch: Partial<DatasetMeasure>) => editing && setEditing({ ...editing, m: { ...editing.m, ...patch } });
  const source = m?.source ?? lists[0] ?? null;
  const columns = fields.filter((f) => (f.source ?? null) === source);
  const others = measures.filter((x, i) => x.kind !== "ratio" && i !== editing?.index);

  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
        {measures.map((x, i) => (
          <div key={x.key} className="grid gap-1.5 rounded-[12px] border border-border-soft bg-bg-raised p-3.5">
            <div className="flex items-start justify-between gap-2">
              <div>
                <b className="font-semibold">{x.label}</b>
                {x.label_km && <div className="text-[0.82rem] text-text-dim">{x.label_km}</div>}
              </div>
              <div className="flex gap-1">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setKeyEdited(true); setEditing({ index: i, m: x }); }}>
                  Edit
                </button>
                <button type="button" className="btn btn-ghost btn-sm icon-only" aria-label={`Remove ${x.label}`} onClick={() => onChange(measures.filter((_, j) => j !== i))}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            <code className="mono overflow-x-auto rounded-md bg-bg-panel px-2 py-1.5 text-[0.75rem] whitespace-nowrap">{formula(x, measures)}</code>
            <div className="flex items-baseline justify-between text-[0.78rem] text-text-faint">
              <span>Last run</span>
              <b className="text-[1.05rem] font-semibold text-text tabular-nums">{results[x.key]?.text ?? "—"}</b>
            </div>
            <div className="text-[0.74rem] text-text-faint">
              In a template: <code className="mono">{`{{ measures.${x.key} }}`}</code>
            </div>
          </div>
        ))}
        {!editing && (
          <button
            type="button"
            className="grid min-h-[120px] place-items-center rounded-[12px] border-[1.5px] border-dashed border-border text-text-dim hover:border-accent-border hover:text-accent-strong"
            onClick={() => {
              setKeyEdited(false);
              setEditing({ index: null, m: { ...EMPTY_MEASURE, source: lists[0] ?? null } });
            }}
          >
            <span className="grid justify-items-center gap-1">
              <Plus size={20} aria-hidden="true" /> Add a measure
            </span>
          </button>
        )}
      </div>

      {m && (
        <div className="grid gap-3 rounded-[12px] border border-border-soft bg-bg-raised p-3.5">
          <b className="font-semibold">{editing!.index === null ? "New measure" : `Edit ${m.label || "measure"}`}</b>
          <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-3">
            <label>
              <span>Name</span>
              <input type="text" maxLength={100} value={m.label} placeholder="Net sales" onChange={(e) => set({ label: e.target.value, ...(keyEdited ? {} : { key: keyOf(e.target.value) }) })} />
            </label>
            <label>
              <span>Name (ខ្មែរ)</span>
              <input type="text" maxLength={100} value={m.label_km ?? ""} onChange={(e) => set({ label_km: e.target.value || null })} />
            </label>
            <label>
              <span>Key (in templates)</span>
              <input type="text" className="mono-input" maxLength={64} value={m.key} onChange={(e) => { setKeyEdited(true); set({ key: e.target.value }); }} />
            </label>
            <label>
              <span>Calculation</span>
              <select value={m.kind} onChange={(e) => set({ kind: e.target.value as MeasureKind })}>
                {(Object.keys(KIND_LABEL) as MeasureKind[]).map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABEL[k]}
                  </option>
                ))}
              </select>
            </label>
            {m.kind === "ratio" ? (
              <>
                <label>
                  <span>Of (on top)</span>
                  <select value={m.numerator ?? ""} onChange={(e) => set({ numerator: e.target.value || null })}>
                    <option value="">Choose a measure…</option>
                    {others.map((o) => (
                      <option key={o.key} value={o.key}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Divided by</span>
                  <select value={m.denominator ?? ""} onChange={(e) => set({ denominator: e.target.value || null })}>
                    <option value="">Choose a measure…</option>
                    {others.map((o) => (
                      <option key={o.key} value={o.key}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            ) : (
              <>
                {lists.length > 1 && (
                  <label>
                    <span>Over</span>
                    <select value={source ?? ""} onChange={(e) => set({ source: e.target.value || null, field: null, where: null })}>
                      {lists.map((l) => (
                        <option key={l} value={l}>
                          {l}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <label>
                  <span>{m.kind === "count" ? "Of (optional)" : "Of"}</span>
                  <select value={m.field ?? ""} onChange={(e) => set({ field: e.target.value || null })}>
                    <option value="">{m.kind === "count" ? "Every row" : "Choose a field…"}</option>
                    {columns.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.label || c.name}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            <label>
              <span>Shown as</span>
              <input type="text" list="measure-formats" maxLength={40} value={m.format ?? ""} placeholder="#,##0.00" onChange={(e) => set({ format: e.target.value || null })} />
              <datalist id="measure-formats">
                {FORMATS.filter((f) => !f.startsWith("DD")).map((f) => (
                  <option key={f} value={f} />
                ))}
              </datalist>
            </label>
            {m.kind !== "ratio" && (
              <div className="grid grid-cols-2 gap-x-3 sm:col-span-2">
                <label>
                  <span>
                    Only where <span className="muted">(optional)</span>
                  </span>
                  <select value={m.where?.field ?? ""} onChange={(e) => set({ where: e.target.value ? { field: e.target.value, value: m.where?.value ?? "" } : null })}>
                    <option value="">Every row</option>
                    {columns.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.label || c.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>is</span>
                  <input type="text" disabled={!m.where} value={m.where?.value ?? ""} placeholder="Diesel" onChange={(e) => set({ where: { field: m.where!.field, value: e.target.value } })} />
                </label>
              </div>
            )}
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn btn-primary btn-sm" onClick={commit} disabled={!m.label.trim() || (m.kind === "ratio" ? !m.numerator || !m.denominator : m.kind !== "count" && !m.field)}>
              {editing!.index === null ? "Add measure" : "Done"}
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <span className="muted self-center text-[0.8rem]">Saved with the dataset — press Save changes above.</span>
          </div>
        </div>
      )}
    </div>
  );
}
