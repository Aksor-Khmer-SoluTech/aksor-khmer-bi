import { Fragment, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuthInfo, Organization, Role } from "../../types";
import PermissionMatrix from "./PermissionMatrix";
import RoleFormDialog from "./RoleFormDialog";

export default function RolesPage({ auth }: { auth: AuthInfo }) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [orgFilter, setOrgFilter] = useState("");
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    api.organizations.list().then(setOrganizations).catch(() => {});
  }, []);

  function load() {
    api
      .roles.list(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then(setRoles)
      .catch(() => setError("Couldn't load roles — is the API reachable?"));
  }

  useEffect(load, [orgFilter]);

  const filtered = useMemo(() => {
    if (!roles) return [];
    const q = query.trim().toLowerCase();
    if (!q) return roles;
    return roles.filter((r) => r.name.toLowerCase().includes(q) || (r.description ?? "").toLowerCase().includes(q));
  }, [roles, query]);

  // null org_id is the one cross-org role (ROLE_ADMINISTRATOR, see api/app/rbac.py's
  // SYSTEM_ADMIN_ROLE_NAME) -- every other role belongs to exactly one organization.
  const orgLabel = (orgId: string | null) =>
    orgId === null ? "Every organization" : organizations.find((o) => o.id === orgId)?.name ?? orgId;

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await api.roles.delete(deleteTarget.id);
      setRoles((prev) => prev?.filter((r) => r.id !== deleteTarget.id) ?? null);
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "Couldn't delete the role");
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Roles</h1>
          <p className="page-subtitle">Edit each role's permission set, or create a custom role for one organization.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setCreateOpen(true)}>
          + New role
        </button>
      </div>

      <div className="gallery-toolbar">
        <div className="search">
          <input type="text" placeholder="Search roles…" value={query} onChange={(e) => setQuery(e.target.value)} />
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
      {deleteError && <p className="alert alert-error">{deleteError}</p>}
      {roles === null && !error && (
    <TableSkeleton columns={["Name", "Scope", ...(auth.isSuperuser ? ["Organization"] : []), "Description", "Permissions", ""]} />
  )}

      {roles !== null && filtered.length === 0 && (
        <div className="empty-state">
          <p>{roles.length === 0 ? "No roles in this organization yet." : "No roles match that search."}</p>
        </div>
      )}

      {filtered.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Scope</th>
              {auth.isSuperuser && <th>Organization</th>}
              <th>Description</th>
              <th>Permissions</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <Fragment key={r.id}>
                <tr className={expandedId === r.id ? "active-row" : ""} onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}>
                  <td className="mono">{r.name}</td>
                  <td>
                    <span className={`badge badge-${r.is_system ? "system" : "custom"}`}>
                      {r.is_system ? "system" : "custom"}
                    </span>
                  </td>
                  {auth.isSuperuser && <td className="muted">{orgLabel(r.org_id)}</td>}
                  <td className="muted">{r.description ?? "—"}</td>
                  <td className="mono">{r.permissions.length}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {!r.is_system && (
                      <button type="button" className="btn-danger btn btn-sm" onClick={() => setDeleteTarget(r)}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
                {expandedId === r.id && (
                  <tr className="detail-row">
                    {/* +1 when the superuser-only Organization column above is present. */}
                    <td colSpan={auth.isSuperuser ? 6 : 5} onClick={(e) => e.stopPropagation()}>
                      {/* Same padded wrapper the Users/Jobs/LDAP panels use --
                          without it the grid sat flush against the panel's edge. */}
                      <div className="admin-detail">
                        <PermissionMatrix
                          role={r}
                          onSaved={(updated) => setRoles((prev) => prev?.map((x) => (x.id === updated.id ? updated : x)) ?? null)}
                        />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}

      <RoleFormDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(role) => setRoles((prev) => [...(prev ?? []), role])}
        organizations={organizations.length > 0 ? organizations : [{ id: auth.orgId ?? "root", name: auth.orgId ?? "root", parent_org_id: null, is_active: true, created_at: "" }]}
        defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || "root"}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete role"
        body={deleteTarget ? `Delete "${deleteTarget.name}"? This can't be undone.` : ""}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
