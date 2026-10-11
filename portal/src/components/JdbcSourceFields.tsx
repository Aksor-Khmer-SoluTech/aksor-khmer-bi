import { useRef, type CSSProperties } from "react";
import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { MAX_QUERIES, newQuery, type EditableJdbc, type EditableQuery } from "../dataConfig";
import type { ConnectionSummary } from "../types";
import DbEngineIcon from "./DbEngineIcon";
import SqlEditor, { bindSnippet, sqlDialectLabel, type SqlEditorHandle, type SqlFilter } from "./SqlEditor";

const SHAPES: { value: EditableQuery["shape"]; label: string; title: string }[] = [
  { value: "list", label: "List", title: "Every row, as a list to loop over ([] when there are none)" },
  { value: "object", label: "Object", title: "The one row it returns, as an object (null when there is none; more than one fails the run)" },
  { value: "value", label: "One value", title: "The first column of the one row it returns (null when there is none)" },
];

/** One SELECT: its editor, the filters to bind into it, and -- once a source has several -- its result name,
 * shape and a handle to drag it into place. Each card keeps its own editor, so "Bind filter" inserts where *that*
 * query's cursor is. */
function QueryCard({
  query,
  index,
  count,
  several,
  onChange,
  onRemove,
  engine,
  filters,
  typedBinding,
}: {
  query: EditableQuery;
  index: number;
  count: number;
  several: boolean;
  onChange: (patch: Partial<EditableQuery>) => void;
  onRemove: () => void;
  engine: string | null | undefined;
  filters: SqlFilter[];
  typedBinding: boolean;
}) {
  const editor = useRef<SqlEditorHandle>(null);
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: query.key });
  // Slide vertically only: a card never drifts sideways while it is dragged.
  const style: CSSProperties = { transform: CSS.Translate.toString(transform ? { ...transform, x: 0 } : null), transition };
  const name = query.name.trim() || "rows";
  const usage =
    query.shape === "list" ? `{% for r in ${name} %} … {{ r.column_name }}` : query.shape === "object" ? `{{ ${name}.column_name }}` : `{{ ${name} }}`;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={several ? `query-sortable mb-4 rounded-sm border border-border-soft bg-bg-raised p-3.5${isDragging ? " dragging" : ""}` : ""}
    >
      {several && (
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <button
            type="button"
            ref={setActivatorNodeRef}
            className="param-grip mb-1.5"
            aria-label={`Move query ${name}: position ${index + 1} of ${count}. Press space, then the arrow keys.`}
            data-tip="Drag to reorder"
            {...attributes}
            {...listeners}
          >
            <GripVertical size={16} aria-hidden="true" />
          </button>
          <label className="mb-0 min-w-[10rem] flex-1">
            <span>Result name</span>
            <input
              type="text"
              className="mono-input"
              required
              maxLength={64}
              pattern="[A-Za-z_][A-Za-z0-9_]*"
              title="Letters, digits and underscores, starting with a letter"
              placeholder="info"
              value={query.name}
              onChange={(e) => onChange({ name: e.target.value })}
            />
          </label>
          <div className="flex items-center gap-3">
            <div className="segmented segmented-sm" role="radiogroup" aria-label="What this query gives">
              {SHAPES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  role="radio"
                  aria-checked={query.shape === s.value}
                  title={s.title}
                  className={`segmented-btn${query.shape === s.value ? " active" : ""}`}
                  onClick={() => onChange({ shape: s.value })}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <button type="button" className="btn btn-ghost btn-sm icon-only" title="Remove this query" aria-label={`Remove query ${name}`} onClick={onRemove}>
              <Trash2 size={15} />
            </button>
          </div>
        </div>
      )}
      <div className="sql-field">
        <span className="sql-field-label">SQL query</span>
        <SqlEditor
          ref={editor}
          value={query.query}
          onChange={(text) => onChange({ query: text })}
          engine={engine}
          filters={filters}
          typedBinding={typedBinding}
          rows={several ? 6 : 10}
          placeholder={
            query.shape !== "list"
              ? "SELECT receipt_code, ref\nFROM receipts\nWHERE id = :id"
              : filters.length > 0
                ? `SELECT branch, SUM(amount) AS total\nFROM sales\nWHERE sale_date >= ${bindSnippet(filters[0], engine, typedBinding)}\nGROUP BY branch`
                : "SELECT branch, SUM(amount) AS total\nFROM sales\nGROUP BY branch"
          }
        />
      </div>
      {filters.length > 0 && (
        <div className="req-chips">
          <span className="req-chips-label">Bind filter</span>
          {filters.map((filter) => (
            <button
              key={filter.name}
              type="button"
              className="chip-btn chip-bind"
              onClick={() => editor.current?.insertAtCursor(bindSnippet(filter, engine, typedBinding))}
              title={`Insert ${bindSnippet(filter, engine, typedBinding)} at the cursor`}
            >
              {filter.name}
            </button>
          ))}
        </div>
      )}
      {several && (
        <p className="field-hint mb-0">
          In the template: <span className="mono">{usage}</span>
        </p>
      )}
    </div>
  );
}

/** A report's database source: which connection (Admin > Connections), and the SELECT it runs -- or several, run at
 * the same time and merged into one object, each under its own name ({rows: [...], info: {...}}). A filter's value
 * is *bound* to its `:name` -- never pasted into the SQL -- so what someone types into the run form can't change the
 * statement. */
export default function JdbcSourceFields({
  value,
  onChange,
  connections,
  connectionsAvailable,
  canManageConnections,
  filters,
}: {
  value: EditableJdbc;
  onChange: (patch: Partial<EditableJdbc>) => void;
  /** Database connections only; null while loading. */
  connections: ConnectionSummary[] | null;
  connectionsAvailable: boolean;
  canManageConnections: boolean;
  /** Filters that can be bound as :name, with their input type. */
  filters: SqlFilter[];
}) {
  const selected = connections?.find((c) => c.name === value.connection) ?? null;
  const queries = value.queries;
  const several = queries.length > 1;
  const [first] = queries;

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const keys = queries.map((q) => q.key);
  // Spoken by screen readers while a card is moved with the keyboard -- by result name and position.
  const nameOf = (id: string | number) => queries.find((q) => q.key === id)?.name.trim() || "this query";
  const positionOf = (id: string | number) => keys.indexOf(String(id)) + 1;
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
    onChange({ queries: arrayMove(queries, keys.indexOf(String(active.id)), keys.indexOf(String(over.id))) });
  };

  const setQuery = (key: string, patch: Partial<EditableQuery>) =>
    onChange({ queries: queries.map((q) => (q.key === key ? { ...q, ...patch } : q)) });

  function addQuery() {
    // Going from one to two: the first keeps its rows under a name ("rows" if it had none), so both are named.
    const named = queries.map((q, i) => (i === 0 && !q.name.trim() ? { ...q, name: "rows" } : q));
    const taken = new Set(named.map((q) => q.name.trim()));
    const suggestion = ["info", "summary", "totals", "details"].find((n) => !taken.has(n)) ?? `query${queries.length + 1}`;
    onChange({ queries: [...named, newQuery({ name: suggestion, shape: "object" })] });
  }

  return (
    <div className="jdbc-source">
      <label>
        <span>Database connection</span>
        <select value={value.connection} required onChange={(e) => onChange({ connection: e.target.value })}>
          <option value="" disabled>
            {connections === null ? "Loading…" : "Choose a database…"}
          </option>
          {value.connection && !selected && (
            <option value={value.connection}>{connectionsAvailable ? `${value.connection} (not found)` : value.connection}</option>
          )}
          {connections?.map((c) => (
            <option key={c.id} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <p className="jdbc-source-conn">
          {selected.engine && <DbEngineIcon engine={selected.engine} size={20} />}
          <span className="mono">{selected.base_url}</span>
        </p>
      )}
      {connections !== null && connections.length === 0 && connectionsAvailable && (
        <p className="field-hint">
          No database connection exists yet.{" "}
          {canManageConnections ? <a href="#/admin/connections">Create one under Manage → Connections</a> : "Ask someone who manages connections to create one"}.
        </p>
      )}
      {!connectionsAvailable && <p className="field-hint">You can't list connections here — type the name of an existing database connection.</p>}

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd} accessibility={{ announcements }}>
        <SortableContext items={keys} strategy={verticalListSortingStrategy}>
          {queries.map((q, index) => (
            <QueryCard
              key={q.key}
              query={q}
              index={index}
              count={queries.length}
              several={several}
              onChange={(patch) => setQuery(q.key, patch)}
              onRemove={() => onChange({ queries: queries.filter((x) => x.key !== q.key) })}
              engine={selected?.engine}
              filters={filters}
              typedBinding={value.typedBinding}
            />
          ))}
        </SortableContext>
      </DndContext>
      <p className="field-hint sql-field-hint">
        Coloured as {sqlDialectLabel(selected?.engine)}{selected ? "" : " (choose a connection to match its database)"}. Type <code>:</code> to pick a filter -- a date or number filter is offered with its conversion written for this database, because values reach the query as text. <kbd>Tab</kbd> indents.
      </p>
      {queries.length < MAX_QUERIES && (
        <button type="button" className="btn btn-sm mb-3 self-start" onClick={addQuery}>
          <Plus size={14} /> Add query
        </button>
      )}
      {several && (
        <p className="field-hint">
          The queries run at the same time and come to the template as one object — each under its name, always there. A
          query with no row gives <span className="mono">null</span> (a list gives <span className="mono">[]</span>), so{" "}
          <span className="mono">{"{% if info %}"}</span> covers a missing header. If one fails, the run fails and says which.
        </p>
      )}
      <p className="field-hint">
        One <span className="mono">SELECT</span> (or <span className="mono">WITH … SELECT</span>). Write a filter as{" "}
        <span className="mono">:name</span> — its value is bound as a parameter, never pasted into the SQL. A filter left empty arrives as an
        empty string.
      </p>
      <label className="checkbox-label">
        <input type="checkbox" checked={value.typedBinding} onChange={(e) => onChange({ typedBinding: e.target.checked })} />
        <span>Bind filters by their type</span>
      </label>
      <p className="field-hint">
        {value.typedBinding ? (
          <>
            A date filter reaches the database as a real date and a number as a number, so <span className="mono">WHERE d &gt;= :fromDate</span> needs no
            CAST. (A connection that uses an uploaded driver still receives text — cast there.)
          </>
        ) : (
          <>
            Every filter reaches the database as text, so cast a date or number in the SQL, e.g.{" "}
            <span className="mono">CAST(:fromDate AS DATE)</span>. Turn this on to skip that — but an existing{" "}
            <span className="mono">CAST</span> or <span className="mono">TO_DATE</span> on a filter may then need removing.
          </>
        )}
      </p>

      {!several && (
        <>
      <label className="jdbc-root-key">
        <span>Name the rows in the template</span>
        <input
          type="text"
          className="mono-input"
          placeholder="rows"
          maxLength={64}
          pattern="[A-Za-z_][A-Za-z0-9_]*"
          title="Letters, digits and underscores, starting with a letter"
          value={first.name}
          onChange={(e) => setQuery(first.key, { name: e.target.value })}
        />
      </label>
      <p className="field-hint">
        The template loops over them with <span className="mono">{`{% for r in ${first.name.trim() || "rows"} %}`}</span> and reads columns as{" "}
        <span className="mono">{"{{ r.column_name }}"}</span>. Dates and times arrive as ISO text, decimals as numbers.
      </p>
        </>
      )}

      <aside className="jdbc-safety">
        <ShieldCheck size={16} aria-hidden="true" />
        <p>
          Read-only by design: anything but a single SELECT is refused, the session is opened read-only with a time limit, and a result over
          the row limit is an error rather than a silent cut-off. The connection's database account should be read-only too.
        </p>
      </aside>
    </div>
  );
}
