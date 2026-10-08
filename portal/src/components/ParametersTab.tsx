import { useState, type CSSProperties } from "react";
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronDown, ChevronUp, CircleCheck, FlaskConical, GripVertical, ListOrdered, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "../api";
import { supportsMonthDay, supportsNow, toOptionsSource, type DataConfigDraft, type EditableParameter } from "../dataConfig";
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

/** The expression default a parameter keeps when its type changes, if the new type still supports it. */
function keepMode(mode: EditableParameter["defaultMode"], type: EditableParameter["textType"]): EditableParameter["defaultMode"] {
  if (mode === "now") return supportsNow(type) ? "now" : "none";
  if (mode === "firstDay" || mode === "lastDay") return supportsMonthDay(type) ? mode : "none";
  return "none";
}

const MODE_LABELS = { now: "now()", firstDay: "firstDayOfMonth()", lastDay: "lastDayOfMonth()" } as const;

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
  // "Reorder" folds every card down to one line, so a long list can be rearranged without scrolling past forms.
  const [compact, setCompact] = useState(false);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  if (draft.status === "idle" || draft.status === "loading") {
    return (
      <div className="panel data-config">
        <h2 className="panel-title">Parameters</h2>
        <LinesSkeleton count={4} />
      </div>
    );
  }

  const keys = draft.parameters.map((p) => p.key);
  // Spoken by screen readers while a card is moved with the keyboard -- by name and position, not by an internal id.
  const nameOf = (id: string | number) => {
    const found = draft.parameters.find((p) => p.key === Number(id));
    return found?.label || found?.name || "this parameter";
  };
  const positionOf = (id: string | number) => keys.indexOf(Number(id)) + 1;
  const announcements = {
    onDragStart: ({ active }: { active: { id: string | number } }) => `Picked up ${nameOf(active.id)}, position ${positionOf(active.id)} of ${keys.length}.`,
    onDragOver: ({ active, over }: { active: { id: string | number }; over: { id: string | number } | null }) =>
      over ? `${nameOf(active.id)} is over position ${positionOf(over.id)} of ${keys.length}.` : undefined,
    onDragEnd: ({ active, over }: { active: { id: string | number }; over: { id: string | number } | null }) =>
      over ? `${nameOf(active.id)} moved to position ${positionOf(over.id)} of ${keys.length}.` : `${nameOf(active.id)} was dropped where it was.`,
    onDragCancel: ({ active }: { active: { id: string | number } }) => `Moving ${nameOf(active.id)} was cancelled; it is still at position ${positionOf(active.id)}.`,
  };
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    draft.moveParameter(keys.indexOf(Number(active.id)), keys.indexOf(Number(over.id)));
  };

  return (
    <div className="panel data-config">
      <h2 className="panel-title">Parameters</h2>
      <p className="panel-subtitle">
        What a person is asked for when they run this report. Where its data comes from is set on the Data source tab.
      </p>

      {draft.loadError && <p className="alert alert-error">{draft.loadError}</p>}

      <section className="data-config-section">
        <div className="spread">
          <h3 className="data-config-heading">Filter parameters</h3>
          {draft.parameters.length > 1 && (
            <button type="button" className={`btn btn-sm${compact ? " btn-primary" : ""}`} aria-pressed={compact} onClick={() => setCompact((c) => !c)}>
              <ListOrdered size={14} aria-hidden="true" /> {compact ? "Done reordering" : "Reorder"}
            </button>
          )}
        </div>
        <p className="field-hint data-config-hint">
          People see the filters <strong>in this order</strong> when they run the report. Drag a card by its handle (or use the arrows) to move it.
        </p>
        <p className="field-hint data-config-hint">
          A <strong>choice list</strong> can be limited per person or role in the Access Privilege tab (for example, a branch filter that lists every
          branch, limited so someone only gets theirs). <strong>Free text</strong> can't be limited.
        </p>

        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd} accessibility={{ announcements }}>
          <SortableContext items={keys} strategy={verticalListSortingStrategy}>
            {draft.parameters.map((p, index) => (
              <ParameterCard
                key={p.key}
                p={p}
                index={index}
                count={draft.parameters.length}
                compact={compact}
                reportId={report.report_id}
                draft={draft}
                canManageConnections={canManageConnections}
                canManageSecrets={canManageSecrets}
                orgId={orgId}
              />
            ))}
          </SortableContext>
        </DndContext>

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
  index,
  count,
  compact,
  reportId,
  draft,
  canManageConnections,
  canManageSecrets,
  orgId,
}: {
  p: EditableParameter;
  index: number;
  count: number;
  compact: boolean;
  reportId: string;
  draft: DataConfigDraft;
  canManageConnections: boolean;
  canManageSecrets: boolean;
  orgId: string;
}) {
  const update = (patch: Partial<EditableParameter>) => draft.updateParameter(p.key, patch);
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: p.key });
  // Slide vertically only: a card never drifts sideways while it is dragged.
  const style: CSSProperties = { transform: CSS.Translate.toString(transform ? { ...transform, x: 0 } : null), transition };
  const title = p.label || p.name || "this parameter";

  function changeType(textType: ParameterType) {
    // A default only makes sense in the type it was written for -- "H.E" isn't a date.
    update({ textType, defaultValue: "", defaultMode: keepMode(p.defaultMode, textType) });
  }

  const rail = (
    <div className="param-rail">
      <button
        type="button"
        ref={setActivatorNodeRef}
        className="param-grip"
        aria-label={`Move ${title}: position ${index + 1} of ${count}. Press space, then the arrow keys.`}
        data-tip="Drag to reorder"
        {...attributes}
        {...listeners}
      >
        <GripVertical size={16} aria-hidden="true" />
      </button>
      <span className="param-position" aria-hidden="true">{index + 1}</span>
      <div className="param-arrows">
        <button type="button" className="param-arrow" disabled={index === 0} onClick={() => draft.moveParameter(index, index - 1)} aria-label={`Move ${title} up`} data-tip="Move up">
          <ChevronUp size={14} aria-hidden="true" />
        </button>
        <button type="button" className="param-arrow" disabled={index === count - 1} onClick={() => draft.moveParameter(index, index + 1)} aria-label={`Move ${title} down`} data-tip="Move down">
          <ChevronDown size={14} aria-hidden="true" />
        </button>
      </div>
    </div>
  );

  if (compact) {
    return (
      <div ref={setNodeRef} style={style} className={`data-config-card param-compact${isDragging ? " dragging" : ""}`}>
        {rail}
        <div className="param-compact-main">
          <strong>{p.label || <span className="muted">(no label)</span>}</strong>
          <span className="mono muted">{p.name || "—"}</span>
        </div>
        <span className="param-compact-kind">{p.kind === "choices" ? "Choice list" : TEXT_TYPES.find((t) => t.value === p.textType)?.label ?? "Free text"}</span>
      </div>
    );
  }

  return (
    <div ref={setNodeRef} style={style} className={`data-config-card param-sortable${isDragging ? " dragging" : ""}`}>
      <div className="data-config-row param-head">
        {rail}
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
              ...(supportsMonthDay(p.textType) ? ([["firstDay", "firstDayOfMonth()"], ["lastDay", "lastDayOfMonth()"]] as const) : []),
            ] as const
          ).map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              className={`segmented-btn${p.defaultMode === mode ? " active" : ""}${mode in MODE_LABELS ? " mono" : ""}`}
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
      {(p.defaultMode === "firstDay" || p.defaultMode === "lastDay") && (
        <span className="run-field-note">
          Starts as the {p.defaultMode === "firstDay" ? "first" : "last"} day of the current month
          {kind === "datetime" ? (p.defaultMode === "firstDay" ? " at 00:00" : " at 23:59") : ""}, taken from the browser when the report is opened.
        </span>
      )}
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
