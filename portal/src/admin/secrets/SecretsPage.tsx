import { useEffect, useMemo, useState } from "react";
import { KeySquare, Pencil, Trash2 } from "lucide-react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuthInfo, Organization, Secret, SecretSummary } from "../../types";
import { has } from "../sections";
import SecretDialog from "./SecretDialog";

/** Admin > Secrets: named credentials -- a bearer token, a basic-auth password
 * -- created, rotated and revoked here instead of as an environment variable
 * on the server. A connection's own authentication and a report's own data
 * source (or choice list) refer to one by name (Admin > Connections' and a
 * template's Data source tab's own "Where the token is kept" picker). See
 * api/app/secrets.py.
 *
 * `secret:manage` is what creates/rotates/revokes/deletes; `connection:manage`
 * or `report:manage` alone still gets the list (never a value) -- picking a
 * credential to use is a narrower act than owning it. */
export default function SecretsPage({ auth }: { auth: AuthInfo }) {
  const canManage = has(auth, "secret:manage");
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [orgFilter, setOrgFilter] = useState("");
  const [secrets, setSecrets] = useState<SecretSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  // The dialog is mounted fresh for each open (see its docstring); `dialog.key` is that.
  const [dialog, setDialog] = useState<{ key: number; secret: Secret | null } | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SecretSummary | null>(null);

  useEffect(() => {
    api.organizations.list().then(setOrganizations).catch(() => {});
  }, []);

  function load() {
    api.secrets
      .list(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then((list) => {
        setError(null);
        setSecrets(list);
      })
      .catch(() => setError("Couldn't load secrets — is the API reachable?"));
  }

  useEffect(load, [orgFilter]);

  const filtered = useMemo(() => {
    if (!secrets) return [];
    const q = query.trim().toLowerCase();
    if (!q) return secrets;
    return secrets.filter((s) => s.name.includes(q) || (s.description ?? "").toLowerCase().includes(q));
  }, [secrets, query]);

  async function manage(s: SecretSummary) {
    setActionError(null);
    setOpening(s.id);
    try {
      setDialog({ key: Date.now(), secret: await api.secrets.get(s.id) });
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Couldn't open the credential");
    } finally {
      setOpening(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setActionError(null);
    try {
      await api.secrets.delete(deleteTarget.id);
      setSecrets((prev) => prev?.filter((s) => s.id !== deleteTarget.id) ?? null);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Couldn't delete the credential");
    }
    setDeleteTarget(null);
  }

  function saved(secret: Secret, created: boolean) {
    setSecrets((prev) => {
      if (!prev) return null;
      const summary: SecretSummary = secret;
      return created ? [...prev, summary] : prev.map((s) => (s.id === summary.id ? summary : s));
    });
  }

  const orgList = organizations.length > 0 ? organizations : [{ id: auth.orgId ?? "root", name: auth.orgId ?? "root", parent_org_id: null, is_active: true, created_at: "" }];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Secrets</h1>
          <p className="page-subtitle">
            Credentials a connection's authentication or a report's own data source can refer to by name, managed here instead of an
            environment variable on the server — create, rotate and revoke them in one place.
          </p>
        </div>
        {canManage && (
          <button type="button" className="btn btn-primary" onClick={() => setDialog({ key: Date.now(), secret: null })}>
            + New credential
          </button>
        )}
      </div>

      <div className="gallery-toolbar">
        <div className="search">
          <input type="text" placeholder="Search credentials…" value={query} onChange={(e) => setQuery(e.target.value)} />
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
      {secrets === null && !error && <TableSkeleton columns={["Credential", "Status", "Used by", "Updated", ""]} />}

      {secrets !== null && filtered.length === 0 && (
        <div className="empty-state conn-empty">
          <KeySquare size={30} strokeWidth={1.4} aria-hidden="true" />
          {secrets.length === 0 ? (
            <>
              <p>No credentials yet.</p>
              <p className="muted">
                {canManage
                  ? "Create one to hold a bearer token or a basic-auth password — then pick it from a connection's or a report's own authentication."
                  : "Ask someone who manages secrets to create one."}
              </p>
            </>
          ) : (
            <p>No credentials match that search.</p>
          )}
        </div>
      )}

      {filtered.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Credential</th>
              <th>Status</th>
              <th>Used by</th>
              <th>Updated</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr key={s.id} onClick={canManage ? () => manage(s) : undefined}>
                <td>
                  <span className="mono conn-name">{s.name}</span>
                  {s.description && <div className="muted" style={{ fontSize: "0.78rem" }}>{s.description}</div>}
                </td>
                <td>
                  <span className={`badge badge-${s.is_active ? "enabled" : "disabled"}`}>{s.is_active ? "active" : "revoked"}</span>
                </td>
                <td className="mono">
                  {s.used_by_count === 0 ? <span className="muted">none</span> : `${s.used_by_count} reference${s.used_by_count === 1 ? "" : "s"}`}
                </td>
                <td className="muted">{new Date(s.updated_at).toLocaleDateString()}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  {canManage && (
                    <div className="row-actions">
                      <button type="button" className="btn btn-sm" onClick={() => manage(s)} disabled={opening === s.id}>
                        {opening === s.id ? <span className="spinner" /> : <Pencil size={13} aria-hidden="true" />}
                        Manage
                      </button>
                      <button
                        type="button"
                        className="btn-danger btn btn-sm"
                        onClick={() => setDeleteTarget(s)}
                        disabled={s.used_by_count > 0}
                        title={s.used_by_count > 0 ? `Used by ${s.used_by_count} reference${s.used_by_count === 1 ? "" : "s"} — point them elsewhere first` : undefined}
                      >
                        <Trash2 size={13} aria-hidden="true" />
                        Delete
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {dialog && (
        <SecretDialog
          key={dialog.key}
          open
          onClose={() => setDialog(null)}
          secret={dialog.secret}
          organizations={orgList}
          defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || "root"}
          onSaved={saved}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete credential"
        body={deleteTarget ? `Delete “${deleteTarget.name}”? Nothing refers to it. This can't be undone.` : ""}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
