import { useState } from "react";
import { CircleCheck, FlaskConical, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "../api";
import { supportsNow, toOptionsSource, type DataConfigDraft, type EditableParameter } from "../dataConfig";
import type { OptionsPreview, ParameterType, ReportMeta } from "../types";
import DataConfigSaveBar from "./DataConfigSaveBar";
import DateTimeField from "./DateTimeField";
import RequestFields from "./RequestFields";
import { LinesSkeleton } from "./Skeletons";

const TEXT_TYPES: { value: ParameterType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "datetime", label: "Date & time" },
  { value: "time", label: "Time" },
];

const NOW_MEANING: Record<"date" | "datetime" | "time", string> = {
  date: "today's date",
  datetime: "the current date and time",
  time: "the current time",
};

/** The template page's "Parameters" tab: the filter parameters the person running
 * the report is asked for -- what each one is called, how it's entered, what it
 * starts with, and (for a choice list) where its choices come from. Where the
 * report's *data* comes from is the Data source tab; both edit one draft
 * (dataConfig.ts) and save together. Managers only: the data config can hold
 * header values and the full option lists a grant is meant to narrow, so it's
 * kept off the public report metadata (api/app/routers/reports.py). */
export default function ParametersTab({
  report,
  draft,
  canManageConnections,
  canManageSecrets,
  orgId,
}: {
  report: ReportMeta;
  draft: DataConfigDraft;
  canManageConnections: boolean;
  canManageSecrets: boolean;
  orgId: string;
}) {
  if (draft.status === "idle" || draft.status === "loading") {
    return (
      <div className="panel data-config">
        <h2 className="panel-title">Parameters</h2>
        <LinesSkeleton count={4} />
      </div>
    );
  }

  return (
    <div className="panel data-config">
      <h2 className="panel-title">Parameters</h2>
      <p className="panel-subtitle">
        What a person is asked for when they run this report. Where its data comes from is set on the Data source tab.
      </p>

      {draft.loadError && <p className="alert alert-error">{draft.loadError}</p>}

      <section className="data-config-section">
        <h3 className="data-config-heading">Filter parameters</h3>
        <p className="field-hint data-config-hint">
          A <strong>choice list</strong> can be limited per person or role in the Access Privilege tab (for example, a branch filter that lists every
          branch, limited so someone only gets theirs). <strong>Free text</strong> can't be limited.
        </p>

        {draft.parameters.map((p) => (
          <ParameterCard
            key={p.key}
            p={p}
            reportId={report.report_id}
            draft={draft}
            canManageConnections={canManageConnections}
            canManageSecrets={canManageSecrets}
            orgId={orgId}
          />
        ))}

        <button type="button" className="btn btn-sm" onClick={draft.addParameter}>
          <Plus size={14} /> Add parameter
        </button>
      </section>

      <DataConfigSaveBar draft={draft} here="parameters" />
    </div>
  );
}

function ParameterCard({
  p,
  reportId,
  draft,
  canManageConnections,
  canManageSecrets,
  orgId,
}: {
  p: EditableParameter;
  reportId: string;
  draft: DataConfigDraft;
  canManageConnections: boolean;
  canManageSecrets: boolean;
  orgId: string;
}) {
  const update = (patch: Partial<EditableParameter>) => draft.updateParameter(p.key, patch);

  function changeType(textType: ParameterType) {
    // A default only makes sense in the type it was written for -- "H.E" isn't a date.
    update({ textType, defaultValue: "", defaultMode: p.defaultMode === "now" && supportsNow(textType) ? "now" : "none" });
  }

  return (
    <div className="data-config-card">
      <div className="data-config-row param-head">
        <label>
          <span>Name</span>
          <input
            type="text"
            className="mono-input"
            value={p.name}
            placeholder="p_branch"
            maxLength={64}
            onChange={(e) => update({ name: e.target.value })}
          />
        </label>
        <label>
          <span>Label shown to the user</span>
          <input type="text" value={p.label} placeholder="Branch" maxLength={200} onChange={(e) => update({ label: e.target.value })} />
        </label>
        <label>
          <span>Kind</span>
          <select value={p.kind} onChange={(e) => update({ kind: e.target.value as "choices" | "text" })}>
            <option value="choices">Choice list</option>
            <option value="text">Free text</option>
          </select>
        </label>
        <button
          type="button"
          className="btn btn-ghost btn-sm icon-only data-config-remove"
          title="Remove this parameter"
          aria-label={`Remove ${p.label || p.name || "this parameter"}`}
          onClick={() => draft.removeParameter(p.key)}
        >
          <Trash2 size={15} />
        </button>
      </div>

      {p.kind === "text" ? (
        <div className="data-config-row param-detail">
          <label>
            <span>Input type</span>
            <select value={p.textType} onChange={(e) => changeType(e.target.value as ParameterType)}>
              {TEXT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <DefaultValue p={p} update={update} />
          <label className="checkbox-label data-config-required">
            <input type="checkbox" checked={p.required} onChange={(e) => update({ required: e.target.checked })} />
            <span>Required</span>
          </label>
        </div>
      ) : (
        <ChoiceSource
          p={p}
          reportId={reportId}
          draft={draft}
          update={update}
          canManageConnections={canManageConnections}
          canManageSecrets={canManageSecrets}
          orgId={orgId}
        />
      )}
    </div>
  );
}

/** What the run form starts this field with. Text and numbers take a typed
 * value; dates and times can also mean "now" -- read from the viewer's clock when
 * the form opens -- which is what `now()` is. */
function DefaultValue({ p, update }: { p: EditableParameter; update: (patch: Partial<EditableParameter>) => void }) {
  const temporal = supportsNow(p.textType);

  if (!temporal) {
    return (
      <label className="param-default">
        <span>Default value</span>
        <input
          type={p.textType === "number" ? "number" : "text"}
          step={p.textType === "number" ? "any" : undefined}
          value={p.defaultValue}
          placeholder="None"
          maxLength={200}
          onChange={(e) => update({ defaultValue: e.target.value, defaultMode: e.target.value.trim() ? "fixed" : "none" })}
        />
      </label>
    );
  }

  const kind = p.textType as "date" | "datetime" | "time";
  return (
    <div className="param-default">
      <span className="field-label" id={`default-${p.key}`}>
        Default value
      </span>
      <div className="param-default-row">
        <div className="segmented segmented-sm" role="group" aria-labelledby={`default-${p.key}`}>
          {(
            [
              ["none", "None"],
              ["fixed", "Fixed"],
              ["now", "now()"],
            ] as const
          ).map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              className={`segmented-btn${p.defaultMode === mode ? " active" : ""}${mode === "now" ? " mono" : ""}`}
              aria-pressed={p.defaultMode === mode}
              onClick={() => update({ defaultMode: mode, defaultValue: mode === "fixed" ? p.defaultValue : "" })}
            >
              {label}
            </button>
          ))}
        </div>
        {p.defaultMode === "fixed" && (
          <div className="param-default-fixed">
            <DateTimeField kind={kind} value={p.defaultValue} onChange={(iso) => update({ defaultValue: iso })} />
          </div>
        )}
      </div>
      {p.defaultMode === "now" && (
        <span className="run-field-note">Starts as {NOW_MEANING[kind]}, taken from the browser when the report is opened.</span>
      )}
    </div>
  );
}

/** A choice list's choices: typed here, one per line, or fetched from a REST
 * API -- through a connection or a full URL -- with JSONPaths saying where the
 * list, and each choice's value and label, are in the response. */
function ChoiceSource({
  p,
  reportId,
  draft,
  update,
  canManageConnections,
  canManageSecrets,
  orgId,
}: {
  p: EditableParameter;
  reportId: string;
  draft: DataConfigDraft;
  update: (patch: Partial<EditableParameter>) => void;
  canManageConnections: boolean;
  canManageSecrets: boolean;
  orgId: string;
}) {
  return (
    <div className="param-choices">
      <div className="param-choices-head">
        <span className="field-label" id={`from-${p.key}`}>
          Choices come from
        </span>
        <div className="segmented segmented-sm" role="group" aria-labelledby={`from-${p.key}`}>
          {(
            [
              ["list", "A fixed list"],
              ["api", "A REST API"],
            ] as const
          ).map(([from, label]) => (
            <button
              key={from}
              type="button"
              className={`segmented-btn${p.choicesFrom === from ? " active" : ""}`}
              aria-pressed={p.choicesFrom === from}
              onClick={() => update({ choicesFrom: from })}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {p.choicesFrom === "list" ? (
        <label>
          <span>Choices — one per line, as “value” or “value | label”</span>
          <textarea
            className="mono-input"
            rows={5}
            value={p.optionsText}
            placeholder={"BR01 | Phnom Penh\nBR02 | Siem Reap"}
            onChange={(e) => update({ optionsText: e.target.value })}
          />
        </label>
      ) : (
        <>
          <RequestFields
            value={p.request}
            onChange={(patch) => update({ request: { ...p.request, ...patch } })}
            connections={draft.connections?.filter((c) => c.kind === "rest") ?? null}
            connectionsAvailable={draft.connectionsAvailable}
            canManageConnections={canManageConnections}
            canManageSecrets={canManageSecrets}
            orgId={orgId}
            bodyHint="Request body (a JSON object, sent as is)"
            urlExample="https://erp.example.com/api/branches"
          />

          <h4 className="param-mapping-heading">Reading the response</h4>
          <div className="data-config-row param-mapping">
            <label>
              <span>Items path</span>
              <input
                type="text"
                className="mono-input"
                value={p.itemsPath}
                placeholder="$.data[*]"
                onChange={(e) => update({ itemsPath: e.target.value })}
              />
            </label>
            <label>
              <span>Value</span>
              <input
                type="text"
                className="mono-input"
                value={p.valuePath}
                placeholder="code"
                onChange={(e) => update({ valuePath: e.target.value })}
              />
            </label>
            <label>
              <span>Label (optional)</span>
              <input
                type="text"
                className="mono-input"
                value={p.labelPath}
                placeholder="${code} - ${nameEn}"
                onChange={(e) => update({ labelPath: e.target.value })}
              />
            </label>
          </div>
          <p className="field-hint data-config-hint">
            <strong>Items path</strong> is where the list is in the response — <code className="mono">$.data[*]</code> for
            {" { \"data\": [ … ] }"}; leave it empty when the response is the list itself. <strong>Value</strong> and <strong>Label</strong> are
            read from each item: a key (<code className="mono">code</code>), a path (<code className="mono">name.en</code>,{" "}
            <code className="mono">tags[0]</code>) or text mixing several ({" "}
            <code className="mono">{"${code} - ${nameEn}"}</code>).
          </p>
          <ChoicePreview p={p} reportId={reportId} />
        </>
      )}
    </div>
  );
}

/** "Test": call the source the way the server would -- with what's typed, saved or
 * not -- and show the choices the paths produce, or the reason they can't. */
function ChoicePreview({ p, reportId }: { p: EditableParameter; reportId: string }) {
  const [state, setState] = useState<
    { status: "idle" } | { status: "loading" } | { status: "ok"; result: OptionsPreview } | { status: "error"; message: string }
  >({ status: "idle" });

  async function test() {
    setState({ status: "loading" });
    try {
      setState({ status: "ok", result: await api.previewOptions(reportId, toOptionsSource(p)) });
    } catch (err) {
      setState({ status: "error", message: err instanceof ApiError && typeof err.message === "string" ? err.message : "Couldn't test this source" });
    }
  }

  const shown = state.status === "ok" ? state.result.options.slice(0, 8) : [];
  return (
    <div className="param-preview">
      <button type="button" className="btn btn-sm" onClick={test} disabled={state.status === "loading"}>
        {state.status === "loading" ? <span className="spinner" /> : <FlaskConical size={14} aria-hidden="true" />}
        Test choices
      </button>
      <div aria-live="polite">
        {state.status === "error" && <p className="alert alert-error param-preview-result">{state.message}</p>}
        {state.status === "ok" && (
          <div className="param-preview-result param-preview-ok">
            <p className="param-preview-count">
              <CircleCheck size={15} aria-hidden="true" />
              {state.result.total === 0
                ? "The request worked, but the paths found no choices."
                : `${state.result.total} choice${state.result.total === 1 ? "" : "s"} found${state.result.total > shown.length ? ` — first ${shown.length}` : ""}`}
            </p>
            {shown.length > 0 && (
              <table className="param-preview-table">
                <thead>
                  <tr>
                    <th>Value</th>
                    <th>Label</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((o) => (
                    <tr key={o.value}>
                      <td className="mono">{o.value}</td>
                      <td>{o.label ?? <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
