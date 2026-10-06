import { useState } from "react";
import { Cable, Database, FlaskConical } from "lucide-react";
import { sourceConfigured, type DataConfigDraft, type EditableSource } from "../dataConfig";
import type { DataSourceType } from "../types";
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
];

const nameOf = (type: DataSourceType) => TYPES.find((t) => t.id === type)?.name ?? type;

/** What would be lost, in a few words -- shown in the warning before a source is switched away from. */
function describeLoss(source: EditableSource): string {
  if (source.type === "jdbc") {
    const query = source.jdbc.query.trim().replace(/\s+/g, " ");
    return [source.jdbc.connection && `connection “${source.jdbc.connection}”`, query && `the query “${query.length > 48 ? `${query.slice(0, 48)}…` : query}”`]
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
export default function DataSourceTab({
  draft,
  canManageConnections,
  canManageSecrets,
  orgId,
}: {
  draft: DataConfigDraft;
  canManageConnections: boolean;
  canManageSecrets: boolean;
  orgId: string;
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
      <h2 className="panel-title">Data source</h2>
      <p className="panel-subtitle">
        Where the server gets this report's data when it's run. It's only called after the person's access to the values they picked has been
        checked.
      </p>

      {draft.loadError && <p className="alert alert-error">{draft.loadError}</p>}

      <section className="data-config-section">
        <label className="checkbox-label data-config-toggle">
          <input type="checkbox" checked={draft.useSource} onChange={(e) => requestOff(e.target.checked)} />
          <span>Get this report's data from a source when it's run</span>
        </label>
        {!draft.useSource && (
          <p className="field-hint">
            Without one, the report is rendered from the filter values alone (the API's public render route is unaffected either way).
          </p>
        )}

        {draft.useSource && (
          <>
            <div className="source-types" role="radiogroup" aria-label="Kind of data source">
              {TYPES.map(({ id, label, blurb, icon: Icon }) => (
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
