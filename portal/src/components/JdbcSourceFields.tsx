import { useRef } from "react";
import { ShieldCheck } from "lucide-react";
import type { EditableJdbc } from "../dataConfig";
import type { ConnectionSummary } from "../types";
import DbEngineIcon from "./DbEngineIcon";
import SqlEditor, { bindSnippet, sqlDialectLabel, type SqlEditorHandle, type SqlFilter } from "./SqlEditor";

/** A report's database source: which connection (Admin > Connections), and the one SELECT it runs.
 * A filter's value is *bound* to its `:name` -- never pasted into the SQL -- so what someone types
 * into the run form can't change the statement. */
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
  const editor = useRef<SqlEditorHandle>(null);
  const selected = connections?.find((c) => c.name === value.connection) ?? null;

  function insertFilter(filter: SqlFilter) {
    editor.current?.insertAtCursor(bindSnippet(filter, selected?.engine, value.typedBinding));
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

      <div className="sql-field">
        <span className="sql-field-label">SQL query</span>
        <SqlEditor
          ref={editor}
          value={value.query}
          onChange={(query) => onChange({ query })}
          engine={selected?.engine}
          filters={filters}
          typedBinding={value.typedBinding}
          rows={10}
          placeholder={
            filters.length > 0
              ? `SELECT branch, SUM(amount) AS total\nFROM sales\nWHERE sale_date >= ${bindSnippet(filters[0], selected?.engine, value.typedBinding)}\nGROUP BY branch`
              : "SELECT branch, SUM(amount) AS total\nFROM sales\nGROUP BY branch"
          }
        />
        <p className="field-hint sql-field-hint">
          Coloured as {sqlDialectLabel(selected?.engine)}{selected ? "" : " (choose a connection to match its database)"}. Type <code>:</code> to pick a filter -- a date or number filter is offered with its conversion written for this database, because values reach the query as text. <kbd>Tab</kbd> indents.
        </p>
      </div>
      {filters.length > 0 && (
        <div className="req-chips">
          <span className="req-chips-label">Bind filter</span>
          {filters.map((filter) => (
            <button
              key={filter.name}
              type="button"
              className="chip-btn chip-bind"
              onClick={() => insertFilter(filter)}
              title={`Insert ${bindSnippet(filter, selected?.engine, value.typedBinding)} at the cursor`}
            >
              {filter.name}
            </button>
          ))}
        </div>
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

      <label className="jdbc-root-key">
        <span>Name the rows in the template</span>
        <input
          type="text"
          className="mono-input"
          placeholder="rows"
          maxLength={64}
          pattern="[A-Za-z_][A-Za-z0-9_]*"
          title="Letters, digits and underscores, starting with a letter"
          value={value.rootKey}
          onChange={(e) => onChange({ rootKey: e.target.value })}
        />
      </label>
      <p className="field-hint">
        The template loops over them with <span className="mono">{`{% for r in ${value.rootKey.trim() || "rows"} %}`}</span> and reads columns as{" "}
        <span className="mono">{"{{ r.column_name }}"}</span>. Dates and times arrive as ISO text, decimals as numbers.
      </p>

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
