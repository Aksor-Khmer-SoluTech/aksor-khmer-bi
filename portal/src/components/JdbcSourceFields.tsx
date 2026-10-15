import { useEffect, useRef, type CSSProperties } from "react";
import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Braces, Brackets, ChevronDown, ChevronUp, GripVertical, Hash, Plus, ShieldCheck, Trash2, X, type LucideIcon } from "lucide-react";
import { isCall, MAX_QUERIES, newMoreResult, newQuery, type EditableJdbc, type EditableQuery } from "../dataConfig";
import type { ApprovedRoutine, ConnectionSummary } from "../types";
import DbEngineIcon from "./DbEngineIcon";
import SqlEditor, { bindSnippet, sqlDialectLabel, type SqlEditorHandle, type SqlFilter } from "./SqlEditor";

// Each icon is what the template receives: [ ] a list of rows, { } one row as an object, # a single value.
const SHAPES: { value: EditableQuery["shape"]; label: string; title: string; icon: LucideIcon }[] = [
  { value: "list", label: "List", title: "Every row, as a list to loop over ([] when there are none)", icon: Brackets },
  { value: "object", label: "Object", title: "The one row it returns, as an object (null when there is none; more than one fails the run)", icon: Braces },
  { value: "value", label: "Single value", title: "The first column of the one row it returns (null when there is none)", icon: Hash },
];

// Written out whole, never glued to a ${...}: Tailwind's scanner reads class names from the source text, and one
// fused to an interpolation (`p-3.5${x}`) is never generated -- which is how this card once lost its padding.
const CARD = "query-sortable mb-4 flex gap-2 rounded-sm border border-border-soft bg-bg-raised py-3.5 pr-3.5 pl-2";
// One height for everything on a card's top row -- the name, the database and the shape switch (the standard 42px
// .segmented) -- so their boxes share a top and a bottom edge, not just a bottom one. (The name's mono font alone
// would make it 2px shorter than the select beside it.)
const ROW_FIELD = "h-[42px]";

/** The name an EXEC calls (schema defaults to dbo, as on the server). */
function execTarget(sql: string): string | null {
  const m = /exec(?:ute)?\s+(\[[^\]]+\]|[\w#@$]+)(?:\s*\.\s*(\[[^\]]+\]|[\w#@$]+))?/i.exec(sql);
  if (!m) return null;
  const parts = [m[1], m[2]].filter(Boolean).map((p) => p.replace(/^\[|\]$/g, ""));
  return parts.length === 2 ? parts.join(".") : `dbo.${parts[0]}`;
}

/** A card saved by the earlier picker that called a *function* opens as `EXEC dbo.fn @p = …` (all the saved card
 * says); a function is called with SELECT, so rewrite it as one, its arguments in the function's parameter order. */
function functionCallFromExec(sql: string, r: ApprovedRoutine): string {
  const given = new Map<string, string>();
  for (const m of sql.matchAll(/(@[\w#@$]+)\s*=\s*(:\w+|N?'(?:[^']|'')*'|-?\d+(?:\.\d+)?|NULL)/gi)) given.set(m[1].toLowerCase(), m[2]);
  const args = r.parameters.map((p) => given.get(p.name.toLowerCase()) ?? "NULL").join(", ");
  return r.kind === "table_function" ? `SELECT *\nFROM ${r.name}(${args})` : `SELECT ${r.name}(${args}) AS value`;
}

/** A stored procedure's further result sets, each named for the template (the 1st is the card's own name). */
function MoreResults({ query, onChange }: { query: EditableQuery; onChange: (patch: Partial<EditableQuery>) => void }) {
  return (
    <div className="mt-3 grid gap-2">
      <span className="text-[0.82rem] font-medium text-text-dim">
        Its results — the 1st is <span className="mono">{query.name.trim() || "rows"}</span>
      </span>
      {query.moreResults.map((m, i) => (
        <div key={m.key} className="flex flex-wrap items-center gap-2">
          <span className="mono w-10 text-[0.78rem] text-text-faint">#{i + 2}</span>
          <input
            type="text"
            className="mono-input h-[38px] max-w-[14rem] flex-1 py-1.5"
            aria-label={`Name of result ${i + 2}`}
            placeholder={i === 0 ? "lines" : `result${i + 2}`}
            maxLength={64}
            pattern="[A-Za-z_][A-Za-z0-9_]*"
            value={m.name}
            onChange={(e) => onChange({ moreResults: query.moreResults.map((x) => (x.key === m.key ? { ...x, name: e.target.value } : x)) })}
          />
          <select
            className="h-[38px] w-auto py-1.5"
            aria-label={`Shape of result ${i + 2}`}
            value={m.shape}
            onChange={(e) =>
              onChange({ moreResults: query.moreResults.map((x) => (x.key === m.key ? { ...x, shape: e.target.value as EditableQuery["shape"] } : x)) })
            }
          >
            {SHAPES.map((sh) => (
              <option key={sh.value} value={sh.value}>
                {sh.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-ghost btn-sm icon-only"
            aria-label={`Remove result ${i + 2}`}
            onClick={() => onChange({ moreResults: query.moreResults.filter((x) => x.key !== m.key) })}
          >
            <X size={14} />
          </button>
        </div>
      ))}
      {query.moreResults.length < 9 && (
        <button type="button" className="btn btn-sm justify-self-start" onClick={() => onChange({ moreResults: [...query.moreResults, newMoreResult()] })}>
          <Plus size={14} aria-hidden="true" /> Name another result set
        </button>
      )}
      <p className="field-hint m-0">A procedure that returns a header and then its lines: name the second one too. Each reaches the template under its name.</p>
    </div>
  );
}

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
  onMove,
  engine,
  filters,
  typedBinding,
  connections,
  defaultConnection,
  target,
}: {
  query: EditableQuery;
  index: number;
  count: number;
  several: boolean;
  onChange: (patch: Partial<EditableQuery>) => void;
  onRemove: () => void;
  /** Move it one place: -1 up, +1 down -- for when dragging past many cards is a chore (or not an option). */
  onMove: (delta: -1 | 1) => void;
  engine: string | null | undefined;
  filters: SqlFilter[];
  typedBinding: boolean;
  /** Database connections to choose this query's own from; null while loading. */
  connections: ConnectionSummary[] | null;
  /** The source's connection, which a query uses unless it names its own. */
  defaultConnection: string;
  /** The connection this card runs on (its own or the default) -- for the procedures and functions it may call. */
  target: ConnectionSummary | null;
}) {
  const editor = useRef<SqlEditorHandle>(null);
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: query.key });
  // Slide vertically only: a card never drifts sideways while it is dragged.
  const style: CSSProperties = { transform: CSS.Translate.toString(transform ? { ...transform, x: 0 } : null), transition };
  const name = query.name.trim() || "rows";
  const usage =
    query.shape === "list" ? `{% for r in ${name} %} … {{ r.column_name }}` : query.shape === "object" ? `{{ ${name}.column_name }}` : `{{ ${name} }}`;

  // The SQL may be one procedure call -- EXEC (SQL Server) or CALL (any database), api/app/routines.py.
  const exec = isCall(query.query);
  // Only a driver run by the JDBC service (SQL Server, Oracle, Db2) reads a procedure's 2nd, 3rd... result sets.
  const manyResults = engine === "sqlserver" || engine === "oracle" || engine === "db2";
  const header = several || (exec && query.moreResults.length > 0);

  // A card from the earlier picker that called a *function* (its connection's old approved list says so): show it as
  // the SELECT it really is.
  const calls = exec ? execTarget(query.query) : null;
  const called = calls ? (target?.routines ?? []).find((r) => r.name.toLowerCase() === calls.toLowerCase()) : undefined;
  useEffect(() => {
    if (called && called.kind !== "procedure") onChange({ query: functionCallFromExec(query.query, called), moreResults: [] });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when what it calls is known (connections loaded)
  }, [called?.name, called?.kind]);

  const body = (
    <>
      {header && (
        <div className="mb-3.5 flex flex-wrap items-end gap-3">
          <label className="mb-0 min-w-[10rem] flex-1">
            <span>Result name</span>
            <input
              type="text"
              className={`mono-input ${ROW_FIELD}`}
              required
              maxLength={64}
              pattern="[A-Za-z_][A-Za-z0-9_]*"
              title="Letters, digits and underscores, starting with a letter"
              placeholder="info"
              value={query.name}
              onChange={(e) => onChange({ name: e.target.value })}
            />
          </label>
          {/* Which database this query reads: the source's, or its own -- for data spread over services. (A lone card
              runs on the connection above; there's nothing to choose.) */}
          {several && (
          <label className="mb-0 min-w-[11rem] flex-1">
            <span>Database</span>
            {/* A div, not a span: `label > span` is the caption style (block + 6px gap), which would make this field
                taller than the Result name beside it and lift it off the row's line. */}
            <div className="relative">
              {engine && (
                <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2" aria-hidden="true">
                  <DbEngineIcon engine={engine} size={16} />
                </span>
              )}
              <select
                className={engine ? `${ROW_FIELD} pl-8` : ROW_FIELD}
                value={query.connection === defaultConnection ? "" : query.connection}
                onChange={(e) => onChange({ connection: e.target.value })}
                aria-label={`Database for query ${name}`}
              >
                <option value="">{defaultConnection ? `Default (${defaultConnection})` : "Default connection"}</option>
                {query.connection && query.connection !== defaultConnection && !connections?.some((c) => c.name === query.connection) && (
                  <option value={query.connection}>{query.connection} (not found)</option>
                )}
                {connections
                  ?.filter((c) => c.name !== defaultConnection)
                  .map((c) => (
                    <option key={c.id} value={c.name}>
                      {c.name}
                    </option>
                  ))}
              </select>
            </div>
          </label>
          )}
          <div className="flex items-center gap-2">
            <div className="segmented" role="radiogroup" aria-label="What this query gives">
              {SHAPES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  role="radio"
                  aria-checked={query.shape === s.value}
                  title={s.title}
                  className={query.shape === s.value ? "segmented-btn active gap-1.5" : "segmented-btn gap-1.5"}
                  onClick={() => onChange({ shape: s.value })}
                >
                  <s.icon size={14} aria-hidden="true" />
                  {s.label}
                </button>
              ))}
            </div>
            {count > 1 && (
              <button type="button" className="btn btn-ghost btn-sm icon-only" title="Remove this query" aria-label={`Remove query ${name}`} onClick={onRemove}>
                <Trash2 size={15} />
              </button>
            )}
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
          {filters.map((filter) => {
            // An EXEC's arguments are plain :names -- no CAST around them.
            const snippet = exec ? `:${filter.name}` : bindSnippet(filter, engine, typedBinding);
            return (
              <button
                key={filter.name}
                type="button"
                className="chip-btn chip-bind"
                onClick={() => editor.current?.insertAtCursor(snippet)}
                title={`Insert ${snippet} at the cursor`}
              >
                {filter.name}
              </button>
            );
          })}
        </div>
      )}
      {exec && /^\s*(?:(?:--[^\n]*\n|\/\*[\s\S]*?\*\/)\s*)*exec/i.test(query.query) && engine && engine !== "sqlserver" && (
        <p className="alert alert-warning m-0 mt-2">
          <span className="mono">EXEC</span> is SQL Server's — on this database write <span className="mono">CALL schema.procedure(:filter, …)</span>.
        </p>
      )}
      {exec && manyResults && <MoreResults query={query} onChange={onChange} />}
      {several && (
        <p className="field-hint mb-0 mt-1">
          In the template: <code className="mono">{usage}</code>
        </p>
      )}
    </>
  );

  if (!several) return <div ref={setNodeRef}>{body}</div>;
  return (
    <div ref={setNodeRef} style={style} className={isDragging ? `${CARD} dragging` : CARD}>
      {/* Its own gutter -- the Parameters tab's rail: drag it, or step it with the arrows when there are many -- so the
          name, the SQL, the filters and the hint all share one left edge. */}
      <div className="param-rail shrink-0 self-start">
        <button
          type="button"
          ref={setActivatorNodeRef}
          className="param-grip"
          aria-label={`Move query ${name}: position ${index + 1} of ${count}. Press space, then the arrow keys.`}
          data-tip="Drag to reorder"
          {...attributes}
          {...listeners}
        >
          <GripVertical size={16} aria-hidden="true" />
        </button>
        <span className="param-position" aria-hidden="true">
          {index + 1}
        </span>
        <div className="param-arrows">
          <button type="button" className="param-arrow" disabled={index === 0} onClick={() => onMove(-1)} aria-label={`Move query ${name} up`} data-tip="Move up">
            <ChevronUp size={14} aria-hidden="true" />
          </button>
          <button type="button" className="param-arrow" disabled={index === count - 1} onClick={() => onMove(1)} aria-label={`Move query ${name} down`} data-tip="Move down">
            <ChevronDown size={14} aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="min-w-0 flex-1">{body}</div>
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
  // Every card is SQL now (an EXEC included), so the editor's hints always apply.
  const anySql = queries.length > 0;

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

  function moveQuery(index: number, delta: -1 | 1) {
    const to = index + delta;
    if (to < 0 || to >= queries.length) return;
    onChange({ queries: arrayMove(queries, index, to) });
    // The arrow keeps focus and travels with its card; keep that card on screen, as a long list scrolls past it.
    requestAnimationFrame(() => (document.activeElement as HTMLElement | null)?.closest(".query-sortable")?.scrollIntoView({ block: "nearest" }));
  }

  const setQuery = (key: string, patch: Partial<EditableQuery>) =>
    onChange({ queries: queries.map((q) => (q.key === key ? { ...q, ...patch } : q)) });

  function addQuery() {
    // Going from one to two: the first keeps its rows under a name ("rows" if it had none), so both are named.
    const named = queries.map((q, i) => (i === 0 && !q.name.trim() ? { ...q, name: "rows" } : q));
    const taken = new Set(named.map((q) => q.name.trim()));
    const suggestion = ["info", "summary", "totals", "details"].find((n) => !taken.has(n)) ?? `query${queries.length + 1}`;
    // On the same database as the card above it: cards tend to come in runs on one service.
    const last = named[named.length - 1];
    onChange({ queries: [...named, newQuery({ name: suggestion, shape: "object", connection: last?.connection ?? "" })] });
  }

  return (
    <div className="jdbc-source">
      <label>
        <span>{several ? "Default connection" : "Database connection"}</span>
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
              onMove={(delta) => moveQuery(index, delta)}
              engine={(q.connection && several ? connections?.find((c) => c.name === q.connection)?.engine : null) ?? selected?.engine}
              filters={filters}
              typedBinding={value.typedBinding}
              connections={connections}
              defaultConnection={value.connection}
              target={connections?.find((c) => c.name === ((several && q.connection) || value.connection)) ?? null}
            />
          ))}
        </SortableContext>
      </DndContext>
      {anySql && (
      <p className="field-hint sql-field-hint">
        {several && queries.some((q) => q.connection && q.connection !== value.connection)
          ? "Each query is coloured for its own database's SQL"
          : `Coloured as ${sqlDialectLabel(selected?.engine)}${selected ? "" : " (choose a connection to match its database)"}`}
        . Type <code>:</code> to pick a filter -- a date or number filter is offered with its conversion written for this database, because values reach the query as text. <kbd>Tab</kbd> indents.
      </p>
      )}
      {queries.length < MAX_QUERIES && (
        <button type="button" className="btn btn-sm mb-3 self-start" onClick={addQuery}>
          <Plus size={14} /> Add query
        </button>
      )}
      {several && (
        <p className="field-hint">
          The queries run at the same time and come to the template as one object — each under its name, always there. Each
          runs on the default connection unless you pick another <em>Database</em> for it — for data spread over several
          services. A query only sees its own database, so it can't join across them. A
          query with no row gives <span className="mono">null</span> (a list gives <span className="mono">[]</span>), so{" "}
          <span className="mono">{"{% if info %}"}</span> covers a missing header. If one fails, the run fails and says which.
        </p>
      )}
      {anySql && (
        <>
      <p className="field-hint">
        One <span className="mono">SELECT</span> (or <span className="mono">WITH … SELECT</span>), or one procedure call:{" "}
        {selected?.engine === "sqlserver" ? (
          <span className="mono">EXEC dbo.procedure @param = :filter</span>
        ) : (
          <span className="mono">CALL schema.procedure(:filter, …)</span>
        )}{" "}
        — its arguments filters, numbers, <span className="mono">'text'</span> or <span className="mono">NULL</span>. Write a filter as <span className="mono">:name</span> — its value is bound as a parameter, never pasted into the SQL. A filter left
        empty arrives as an empty string.
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
        </>
      )}

      {/* A lone card's result name, unless the card shows it itself (a procedure naming more result sets). */}
      {!several && !(isCall(first.query) && first.moreResults.length > 0) && (
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
          One statement per query — a SELECT or a procedure call — and every filter's value is bound, never pasted into the SQL. The session
          is opened read-only with a time limit, and a result over the row limit is an error rather than a silent cut-off. A procedure runs
          with the rights its database gives it, so the connection's account should only read and run what reports need.
        </p>
      </aside>
    </div>
  );
}
