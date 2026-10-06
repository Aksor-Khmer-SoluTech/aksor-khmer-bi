import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import { TableSkeleton } from "../../components/Skeletons";
import type { AccessReviewGrant, AuthInfo, Organization } from "../../types";

type TypeFilter = "all" | "report" | "folder";

function isExpired(expiresAt: string | null): boolean {
  return expiresAt !== null && new Date(expiresAt).getTime() < Date.now();
}

/** Admin's "every grant, in one place" screen -- until this existed, an
 * admin reviewing access had to open each report's own Access Privilege tab or each
 * folder's own grants dialog one at a time (see GET /grants/reports and
 * GET /grants/folders, both of which require a scoping id). This backs
 * GET /grants/access-review instead, which aggregates both grant tables
 * with names already resolved server-side. */
export default function AccessReviewPage({ auth }: { auth: AuthInfo }) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [orgFilter, setOrgFilter] = useState("");
  const [grants, setGrants] = useState<AccessReviewGrant[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [revokeTarget, setRevokeTarget] = useState<AccessReviewGrant | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  useEffect(() => {
    api.organizations.list().then(setOrganizations).catch(() => {});
  }, []);

  function load() {
    api.grants
      .accessReview(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then(setGrants)
      .catch(() => setError("Couldn't load access grants — is the API reachable?"));
  }

  useEffect(load, [orgFilter]);

  const filtered = useMemo(() => {
    if (!grants) return [];
    const q = query.trim().toLowerCase();
    return grants
      .filter((g) => typeFilter === "all" || g.grant_type === typeFilter)
      .filter((g) => !q || g.subject_name.toLowerCase().includes(q) || g.resource_name.toLowerCase().includes(q));
  }, [grants, query, typeFilter]);

  async function confirmRevoke() {
    if (!revokeTarget) return;
    setRevokeError(null);
    try {
      if (revokeTarget.grant_type === "report") await api.grants.reports.revoke(revokeTarget.id);
      else await api.grants.folders.revoke(revokeTarget.id);
      setGrants((prev) => prev?.filter((g) => g.id !== revokeTarget.id) ?? null);
      setRevokeTarget(null);
    } catch (err) {
      setRevokeError(err instanceof ApiError ? err.message : "Couldn't revoke");
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Access Review</h1>
          <p className="page-subtitle">Every active report and folder grant, in one place — no more opening each one individually.</p>
        </div>
      </div>

      <div className="gallery-toolbar">
        <div className="search">
          <input
            type="text"
            placeholder="Search by subject or resource name…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as TypeFilter)} style={{ maxWidth: 180 }}>
          <option value="all">All grant types</option>
          <option value="report">Report grants</option>
          <option value="folder">Folder grants</option>
        </select>
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
      {revokeError && <p className="alert alert-error">{revokeError}</p>}
      {grants === null && !error && <TableSkeleton columns={["Subject", "Resource", "Level", "Granted by", "Expires", ""]} />}

      {grants !== null && filtered.length === 0 && (
        <div className="empty-state">
          <p>{grants.length === 0 ? "No grants to review yet." : "No grants match that search."}</p>
        </div>
      )}

      {filtered.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Subject</th>
              <th>Resource</th>
              <th>Level</th>
              <th>Granted by</th>
              <th>Expires</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((g) => (
              <tr key={g.id}>
                <td>
                  <span className={`badge badge-${g.subject_type === "role" ? "system" : "local"}`}>{g.subject_type}</span>{" "}
                  <span className="mono">{g.subject_name}</span>
                </td>
                <td>
                  <span className={`badge badge-${g.grant_type}`}>{g.grant_type}</span> {g.resource_name}
                </td>
                <td>
                  {g.permission_level}
                  {g.parameter_limits && Object.keys(g.parameter_limits).length > 0 && (
                    <span className="grant-row-limits">
                      {Object.entries(g.parameter_limits).map(([name, values]) => (
                        <span key={name} className="limit-chip">
                          <strong>{name}</strong>: {values.join(", ")}
                        </span>
                      ))}
                    </span>
                  )}
                </td>
                <td className="muted">{g.granted_by_name ?? "—"}</td>
                <td className={isExpired(g.expires_at) ? "text-danger" : "muted"}>
                  {g.expires_at ? new Date(g.expires_at).toLocaleDateString() : "no expiry"}
                  {isExpired(g.expires_at) && " (expired)"}
                </td>
                <td>
                  <button type="button" className="btn-danger btn btn-sm" onClick={() => setRevokeTarget(g)}>
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke grant"
        body={revokeTarget ? `Revoke ${revokeTarget.subject_name}'s ${revokeTarget.permission_level} access to "${revokeTarget.resource_name}"? This takes effect immediately.` : ""}
        confirmLabel="Revoke"
        onConfirm={confirmRevoke}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}
