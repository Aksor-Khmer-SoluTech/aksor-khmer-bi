import { useEffect, useMemo, useState } from "react";
import { Cable, Pencil, Trash2 } from "lucide-react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuthInfo, Connection, ConnectionSummary, Organization } from "../../types";
import DbEngineIcon from "../../components/DbEngineIcon";
import ConnectionDialog from "./ConnectionDialog";
import JdbcConnectionDialog from "./JdbcConnectionDialog";

const AUTH_LABEL: Record<ConnectionSummary["auth_type"], string> = { none: "None", bearer: "Bearer token", basic: "Basic" };
const CREDENTIAL_LABEL: Record<ConnectionSummary["credential"], (c: ConnectionSummary) => string | null> = {
  none: () => null,
  secret: (c) => `saved credential: ${c.secret_name}`,
  env: () => "from a server environment variable",
};

export default function ConnectionsPage({ auth }: { auth: AuthInfo }) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [orgFilter, setOrgFilter] = useState("");
  const [connections, setConnections] = useState<ConnectionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  // The dialog is mounted fresh for each open (see its docstring); `dialog.key` is that.
  const [dialog, setDialog] = useState<{ key: number; kind: "rest" | "jdbc"; connection: Connection | null } | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ConnectionSummary | null>(null);

  useEffect(() => {
    api.organizations.list().then(setOrganizations).catch(() => {});
  }, []);

  function load() {
    api.connections
      .list(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then((list) => {
        setError(null);
        setConnections(list);
      })
      .catch(() => setError("Couldn't load connections — is the API reachable?"));
  }

  useEffect(load, [orgFilter]);

  const filtered = useMemo(() => {
    if (!connections) return [];
    const q = query.trim().toLowerCase();
    if (!q) return connections;
    return connections.filter((c) => c.name.includes(q) || c.base_url.toLowerCase().includes(q) || (c.description ?? "").toLowerCase().includes(q));
  }, [connections, query]);

  async function edit(c: ConnectionSummary) {
    setActionError(null);
    setOpening(c.id);
    try {
      // The list has no header values (report authors see it too); the editor needs them.
      const full = await api.connections.get(c.id);
      setDialog({ key: Date.now(), kind: full.kind === "jdbc" ? "jdbc" : "rest", connection: full });
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Couldn't open the connection");
    } finally {
      setOpening(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setActionError(null);
    try {
      await api.connections.delete(deleteTarget.id);
      setConnections((prev) => prev?.filter((c) => c.id !== deleteTarget.id) ?? null);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Couldn't delete the connection");
    }
    setDeleteTarget(null);
  }

  const orgList = organizations.length > 0 ? organizations : [{ id: auth.orgId ?? "root", name: auth.orgId ?? "root", parent_org_id: null, is_active: true, created_at: "" }];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Connections</h1>
          <p className="page-subtitle">
            Where reports get their data: a REST API's base URL with the headers and authentication every call needs, or a database with its
            login. A report picks a connection and adds only a path or a SQL query — so when a system moves, or you go from test to
            production, you change it here once.
          </p>
        </div>
        <div className="page-header-actions">
          <button type="button" className="btn" onClick={() => setDialog({ key: Date.now(), kind: "jdbc", connection: null })}>
            + Database
          </button>
          <button type="button" className="btn btn-primary" onClick={() => setDialog({ key: Date.now(), kind: "rest", connection: null })}>
            + REST API
          </button>
        </div>
      </div>

      <div className="gallery-toolbar">
        <div className="search">
          <input type="text" placeholder="Search connections…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {auth.isSuperuser && (
          <select value={orgFilter} onChange={(e) => setOrgFilter(e.target.value)} style={{ maxWidth: 220 }}>
            <option value="">All organizations</option>
            {organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {actionError && <p className="alert alert-error">{actionError}</p>}
      {connections === null && !error && <TableSkeleton columns={["Connection", "Location", "Authentication", "Used by", "Updated", ""]} />}

      {connections !== null && filtered.length === 0 && (
        <div className="empty-state conn-empty">
          <Cable size={30} strokeWidth={1.4} aria-hidden="true" />
          {connections.length === 0 ? (
            <>
              <p>No connections yet.</p>
              <p className="muted">
                Create one for each system your reports read from — a REST API like <span className="mono">erp-api</span> at{" "}
                <span className="mono">https://erp.example.com</span>, or a database (Oracle, PostgreSQL, MySQL, SQL Server, MariaDB, Db2) — then
                choose it on a report's Data source tab. Tokens and passwords are saved encrypted; no environment variable to set.
              </p>
            </>
          ) : (
            <p>No connections match that search.</p>
          )}
        </div>
      )}

      {filtered.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Connection</th>
              <th>Location</th>
              <th>Authentication</th>
              <th>Used by</th>
              <th>Updated</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr key={c.id} onClick={() => edit(c)}>
                <td>
                  <span className="conn-name-row">
                    {c.kind === "jdbc" && c.engine && <DbEngineIcon engine={c.engine} size={22} />}
                    <span className="mono conn-name">{c.name}</span>
                  </span>
                  {c.description && <div className="muted" style={{ fontSize: "0.78rem" }}>{c.description}</div>}
                </td>
                <td className="mono conn-url" title={c.base_url}>
                  {c.base_url}
                </td>
                <td>
                  {AUTH_LABEL[c.auth_type]}
                  {CREDENTIAL_LABEL[c.credential](c) && (
                    <div className={c.credential === "secret" ? "conn-credential-saved" : "muted"} style={{ fontSize: "0.78rem" }}>
                      {CREDENTIAL_LABEL[c.credential](c)}
                    </div>
                  )}
                  {c.header_names.length > 0 && (
                    <div className="muted" style={{ fontSize: "0.78rem" }}>
                      + {c.header_names.length} header{c.header_names.length === 1 ? "" : "s"}
                    </div>
                  )}
                </td>
                <td className="mono">{c.report_count === 0 ? <span className="muted">none</span> : `${c.report_count} report${c.report_count === 1 ? "" : "s"}`}</td>
                <td className="muted">{new Date(c.updated_at).toLocaleDateString()}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  <div className="row-actions">
                    <button type="button" className="btn btn-sm" onClick={() => edit(c)} disabled={opening === c.id}>
                      {opening === c.id ? <span className="spinner" /> : <Pencil size={13} aria-hidden="true" />}
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn-danger btn btn-sm"
                      onClick={() => setDeleteTarget(c)}
                      disabled={c.report_count > 0}
                      title={c.report_count > 0 ? `Used by ${c.report_count} report${c.report_count === 1 ? "" : "s"} — point them elsewhere first` : undefined}
                    >
                      <Trash2 size={13} aria-hidden="true" />
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {dialog && dialog.kind === "jdbc" && (
        <JdbcConnectionDialog
          key={dialog.key}
          open
          onClose={() => setDialog(null)}
          connection={dialog.connection}
          organizations={orgList}
          defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || "root"}
          auth={auth}
          onSaved={load}
        />
      )}
      {dialog && dialog.kind === "rest" && (
        <ConnectionDialog
          key={dialog.key}
          open
          onClose={() => setDialog(null)}
          connection={dialog.connection}
          organizations={orgList}
          defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || "root"}
          auth={auth}
          onSaved={load}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete connection"
        body={deleteTarget ? `Delete “${deleteTarget.name}”? No report uses it. This can't be undone.` : ""}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
