import { useEffect, useState } from "react";
import { api } from "../../api";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuthInfo, Organization } from "../../types";
import OrgFormDialog from "./OrgFormDialog";

export default function OrganizationsPage({ auth }: { auth: AuthInfo }) {
  const [organizations, setOrganizations] = useState<Organization[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  function load() {
    api.organizations.list().then(setOrganizations).catch(() => setError("Couldn't load organizations — is the API reachable?"));
  }

  useEffect(load, []);

  const canCreate = auth.isSuperuser || auth.permissions.includes("org:manage");
  const orgName = (id: string | null) => (id ? organizations?.find((o) => o.id === id)?.name ?? id : "—");

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Organizations</h1>
          <p className="page-subtitle">Tenants — each gets its own users, roles, and (optionally) an LDAP config.</p>
        </div>
        {canCreate && (
          <button type="button" className="btn btn-primary" onClick={() => setCreateOpen(true)}>
            + New organization
          </button>
        )}
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {organizations === null && !error && <TableSkeleton columns={["Id", "Name", "Parent", "Status", "Created"]} />}

      {organizations !== null && organizations.length === 0 && (
        <div className="empty-state">
          <p>No organizations yet.</p>
        </div>
      )}

      {organizations !== null && organizations.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Id</th>
              <th>Name</th>
              <th>Parent</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {organizations.map((o) => (
              <tr key={o.id}>
                <td className="mono">{o.id}</td>
                <td>{o.name}</td>
                <td className="muted">{orgName(o.parent_org_id)}</td>
                <td>
                  <span className={`badge badge-${o.is_active ? "active" : "inactive"}`}>
                    {o.is_active ? "active" : "inactive"}
                  </span>
                </td>
                <td className="muted">{o.created_at ? new Date(o.created_at).toLocaleDateString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <OrgFormDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(org) => setOrganizations((prev) => [...(prev ?? []), org])}
        organizations={organizations ?? []}
      />
    </div>
  );
}
