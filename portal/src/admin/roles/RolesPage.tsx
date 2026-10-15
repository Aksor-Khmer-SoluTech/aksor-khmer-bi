import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import DetailModal from "../../components/DetailModal";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuthInfo, Organization, Role } from "../../types";
import { roleHint } from "../users/UserGrants";
import { roleLabel } from "../users/UserOverview";
import PermissionMatrix from "./PermissionMatrix";
import RoleFormDialog from "./RoleFormDialog";

/** The open role lives in the address (#/admin/roles?role=<id>) -- linkable, and kept on reload. */
function roleInHash(): string | null {
  return new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("role");
}

function setRoleInHash(id: string | null) {
  const base = window.location.hash.split("?")[0] || "#/admin/roles";
  window.history.replaceState(null, "", id ? `${base}?role=${encodeURIComponent(id)}` : base);
}

export default function RolesPage({ auth }: { auth: AuthInfo }) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [orgFilter, setOrgFilter] = useState("");
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(roleInHash);
  // The open role has edits not saved yet: closing asks first.
  const [dirty, setDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  useEffect(() => {
    const onHash = () => setOpenId(roleInHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function open(id: string | null) {
    setOpenId(id);
    setRoleInHash(id);
    setDirty(false);
  }

  const requestClose = useCallback(() => {
    if (dirty) setConfirmDiscard(true);
    else open(null);
  }, [dirty]);
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

const openRole = roles?.find((r) => r.id === openId) ?? null;

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
                <tr key={r.id} className={openId === r.id ? "active-row" : ""} onClick={() => open(r.id)}>
                  <td>
                    <div className="font-medium">{roleLabel(r.name)}</div>
                    {roleLabel(r.name) !== r.name && <span className="mono muted text-[0.72rem]">{r.name}</span>}
                  </td>
                  <td>
                    <span className={`badge badge-${r.is_system ? "system" : "custom"}`}>
                      {r.is_system ? "system" : "custom"}
                    </span>
                  </td>
                  {auth.isSuperuser && <td className="muted">{orgLabel(r.org_id)}</td>}
                  <td className="muted">{roleHint(r)}</td>
                  <td className="mono">{r.permissions.length}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {!r.is_system && (
                      <button type="button" className="btn-danger btn btn-sm" onClick={() => setDeleteTarget(r)}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
            ))}
          </tbody>
        </table>
      )}

      {openRole && (
        <DetailModal
          label={`Role ${openRole.name}`}
          title={roleLabel(openRole.name)}
          subtitle={
            <>
              <span className="font-mono">{openRole.name}</span> · {orgLabel(openRole.org_id)} · {roleHint(openRole)}
            </>
          }
          leading={
            <span
              className={`grid size-11 shrink-0 place-items-center rounded-xl font-display text-[0.95rem] font-semibold ring-1 ${
                openRole.org_id === null
                  ? "bg-danger-soft text-danger-strong ring-danger/40"
                  : "bg-accent-soft text-accent-strong ring-accent-border"
              }`}
              aria-hidden="true"
            >
              {roleLabel(openRole.name)
                .split(/\s+/)
                .map((w) => w[0])
                .join("")
                .slice(0, 2)
                .toUpperCase()}
            </span>
          }
          badges={
            <>
              <span className={`badge badge-${openRole.is_system ? "system" : "custom"}`}>{openRole.is_system ? "system" : "custom"}</span>
              <span className="badge">{openRole.permissions.length} permissions</span>
            </>
          }
          onClose={requestClose}
        >
          <div className="admin-detail">
            <PermissionMatrix
              key={openRole.id}
              role={openRole}
              onDirtyChange={setDirty}
              onSaved={(updated) => setRoles((prev) => prev?.map((x) => (x.id === updated.id ? updated : x)) ?? null)}
            />
          </div>
        </DetailModal>
      )}

      <ConfirmDialog
        open={confirmDiscard}
        title="Discard your changes?"
        body="The permissions you ticked or unticked in this role haven't been saved."
        confirmLabel="Discard"
        onConfirm={() => {
          setConfirmDiscard(false);
          open(null);
        }}
        onCancel={() => setConfirmDiscard(false)}
      />

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
