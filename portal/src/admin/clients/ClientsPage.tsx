import { Fragment, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import { TableSkeleton } from "../../components/Skeletons";
import type { ApiClient, ApiClientWithSecret, AuthInfo, Organization, ReportMeta } from "../../types";
import ClientFormDialog from "./ClientFormDialog";
import ClientReportsPanel from "./ClientReportsPanel";
import ClientSecretDialog from "./ClientSecretDialog";

export default function ClientsPage({ auth }: { auth: AuthInfo }) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [reports, setReports] = useState<ReportMeta[]>([]);
  const [orgFilter, setOrgFilter] = useState("");
  const [clients, setClients] = useState<ApiClient[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [rotateTarget, setRotateTarget] = useState<ApiClient | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ApiClient | null>(null);
  const [revealed, setRevealed] = useState<{ result: ApiClientWithSecret; heading: string } | null>(null);

  useEffect(() => {
    api.organizations.list().then(setOrganizations).catch(() => {});
    api.listReports().then(setReports).catch(() => {});
  }, []);

  function load() {
    api.clients
      .list(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then(setClients)
      .catch(() => setError("Couldn't load API clients — is the API reachable?"));
  }

  useEffect(load, [orgFilter]);

  const filtered = useMemo(() => {
    if (!clients) return [];
    const q = query.trim().toLowerCase();
    if (!q) return clients;
    return clients.filter((c) => c.name.toLowerCase().includes(q) || c.client_id.includes(q));
  }, [clients, query]);

  function replace(updated: ApiClient) {
    setClients((prev) => prev?.map((c) => (c.id === updated.id ? updated : c)) ?? null);
  }

  async function run(action: () => Promise<void>, fallback: string) {
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : fallback);
    }
  }

  const toggleActive = (c: ApiClient) =>
    run(async () => replace(await api.clients.update(c.id, { is_active: !c.is_active })), "Couldn't change the client");

  const confirmRotate = () =>
    run(async () => {
      if (!rotateTarget) return;
      const result = await api.clients.rotateSecret(rotateTarget.id);
      replace(result.client);
      setRotateTarget(null);
      setRevealed({ result, heading: "New client secret" });
    }, "Couldn't rotate the secret");

  const confirmDelete = () =>
    run(async () => {
      if (!deleteTarget) return;
      await api.clients.delete(deleteTarget.id);
      setClients((prev) => prev?.filter((c) => c.id !== deleteTarget.id) ?? null);
      setDeleteTarget(null);
    }, "Couldn't delete the client");

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">API Clients</h1>
          <p className="page-subtitle">
            Let an app run reports with a client ID and secret instead of a user login — beside roles and per-user
            grants. Each client can run only the reports you tick for it.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setCreateOpen(true)}>
          + New client
        </button>
      </div>

      <div className="gallery-toolbar">
        <div className="search">
          <input type="text" placeholder="Search clients…" value={query} onChange={(e) => setQuery(e.target.value)} />
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
      {clients === null && !error && <TableSkeleton columns={["Client", "Client ID", "Secret", "Reports", "Status", "Last used", ""]} />}

      {clients !== null && filtered.length === 0 && (
        <div className="empty-state">
          <p>{clients.length === 0 ? "No API clients yet." : "No clients match that search."}</p>
        </div>
      )}

      {filtered.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Client</th>
              <th>Client ID</th>
              <th>Secret</th>
              <th>Reports</th>
              <th>Status</th>
              <th>Last used</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <Fragment key={c.id}>
                <tr className={expandedId === c.id ? "active-row" : ""} onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}>
                  <td>
                    {c.name}
                    {c.description && <div className="muted" style={{ fontSize: "0.78rem" }}>{c.description}</div>}
                  </td>
                  <td className="mono">{c.client_id}</td>
                  <td className="mono muted">{c.secret_prefix}…</td>
                  <td className="mono">{c.reports.length}</td>
                  <td>
                    <span className={`badge badge-${c.is_active ? "active" : "inactive"}`}>{c.is_active ? "active" : "disabled"}</span>
                  </td>
                  <td className="muted">{c.last_used_at ? new Date(c.last_used_at).toLocaleString() : "never"}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="row-actions">
                      <button type="button" className="btn btn-sm" onClick={() => setRotateTarget(c)}>
                        Rotate secret
                      </button>
                      <button type="button" className="btn btn-sm" onClick={() => toggleActive(c)}>
                        {c.is_active ? "Disable" : "Enable"}
                      </button>
                      <button type="button" className="btn-danger btn btn-sm" onClick={() => setDeleteTarget(c)}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
                {expandedId === c.id && (
                  <tr className="detail-row">
                    <td colSpan={7} onClick={(e) => e.stopPropagation()}>
                      <div className="admin-detail">
                        <ClientReportsPanel client={c} reports={reports} onSaved={replace} />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}

      <ClientFormDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(result) => {
          setClients((prev) => [...(prev ?? []), result.client]);
          setRevealed({ result, heading: "Client created" });
        }}
        organizations={organizations.length > 0 ? organizations : [{ id: auth.orgId ?? "root", name: auth.orgId ?? "root", parent_org_id: null, is_active: true, created_at: "" }]}
        defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || "root"}
        reports={reports}
      />

      <ClientSecretDialog result={revealed?.result ?? null} heading={revealed?.heading ?? ""} onClose={() => setRevealed(null)} />

      <ConfirmDialog
        open={rotateTarget !== null}
        title="Rotate secret"
        body={rotateTarget ? `"${rotateTarget.name}" stops working with its current secret immediately. Anything using it fails until it is given the new one.` : ""}
        confirmLabel="Rotate"
        onConfirm={confirmRotate}
        onCancel={() => setRotateTarget(null)}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete client"
        body={deleteTarget ? `Delete "${deleteTarget.name}" and its report grants? Anything using it stops working. This can't be undone.` : ""}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
