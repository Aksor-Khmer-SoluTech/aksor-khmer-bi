import { Fragment, useEffect, useState } from "react";
import { api } from "../../api";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuthInfo, LdapConfig, Organization } from "../../types";
import LdapConfigDetailPanel from "./LdapConfigDetailPanel";
import LdapConfigFormDialog from "./LdapConfigFormDialog";

export default function LdapConfigsPage({ auth }: { auth: AuthInfo }) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [configs, setConfigs] = useState<LdapConfig[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [orgFilter, setOrgFilter] = useState<string>("");
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    api.organizations.list().then(setOrganizations).catch(() => {});
  }, []);

  function load() {
    api.ldap
      .list(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then(setConfigs)
      .catch(() => setError("Couldn't load LDAP configurations — is the API reachable?"));
  }

  useEffect(load, [orgFilter]);

  const orgName = (id: string | null) => (id === null ? "System-wide default" : organizations.find((o) => o.id === id)?.name ?? id);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">AD / LDAP</h1>
          <p className="page-subtitle">
            Directory configurations for logging in against Active Directory or an LDAP server, with group→role sync.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setCreateOpen(true)}>
          + New configuration
        </button>
      </div>

      {auth.isSuperuser && (
        <div className="gallery-toolbar">
          <select value={orgFilter} onChange={(e) => setOrgFilter(e.target.value)} style={{ maxWidth: 220 }}>
            <option value="">All organizations</option>
            {organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {error && <p className="alert alert-error">{error}</p>}
      {configs === null && !error && (
        <TableSkeleton columns={["Server", "Bind method", "Base DN", ...(auth.isSuperuser ? ["Organization"] : []), "Status"]} />
      )}

      {configs !== null && configs.length === 0 && (
        <div className="empty-state">
          <p>No LDAP configurations yet.</p>
        </div>
      )}

      {configs !== null && configs.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Server</th>
              <th>Bind method</th>
              <th>Base DN</th>
              {auth.isSuperuser && <th>Organization</th>}
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {configs.map((c) => (
              <Fragment key={c.id}>
                <tr
                  className={expandedId === c.id ? "active-row" : ""}
                  onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
                >
                  <td className="mono">{c.server_uri}</td>
                  <td>{c.bind_method}</td>
                  <td className="mono">{c.base_dn}</td>
                  {auth.isSuperuser && <td>{orgName(c.org_id)}</td>}
                  <td>
                    <span className={`badge badge-${c.is_enabled ? "enabled" : "disabled"}`}>
                      {c.is_enabled ? "enabled" : "disabled"}
                    </span>
                  </td>
                </tr>
                {expandedId === c.id && (
                  <tr className="detail-row">
                    <td colSpan={auth.isSuperuser ? 5 : 4}>
                      <LdapConfigDetailPanel
                        config={c}
                        onUpdated={(updated) => setConfigs((prev) => prev?.map((x) => (x.id === updated.id ? updated : x)) ?? null)}
                        onDeleted={(id) => {
                          setConfigs((prev) => prev?.filter((x) => x.id !== id) ?? null);
                          setExpandedId(null);
                        }}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}

      <LdapConfigFormDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(config) => setConfigs((prev) => [...(prev ?? []), config])}
        organizations={organizations}
        defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || ""}
        isSuperuser={auth.isSuperuser}
      />
    </div>
  );
}
