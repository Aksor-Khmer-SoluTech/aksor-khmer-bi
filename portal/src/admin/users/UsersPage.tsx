import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import DetailModal from "../../components/DetailModal";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuthInfo, Organization, User } from "../../types";
import { has } from "../sections";
import UserDetailPanel, { type UserTab } from "./UserDetailPanel";
import UserFormDialog from "./UserFormDialog";
import { reportLoadError } from "../../notify";

function StatusBadges({ user }: { user: User }) {
  return (
    <>
      <span className={`badge badge-${user.is_active ? "active" : "inactive"}`}>
        {user.is_active ? "active" : "inactive"}
      </span>
      {user.is_locked && <span className="badge badge-locked">locked</span>}
      {user.must_change_password && <span className="badge badge-pending">password change pending</span>}
    </>
  );
}

/** The open user lives in the address (#/admin/users?user=<id>), so it survives a reload and can be linked. Written
 * with replaceState: opening users one after another shouldn't fill the Back button's history. */
function userInHash(): string | null {
  return new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("user");
}

function setUserInHash(id: string | null) {
  const base = window.location.hash.split("?")[0] || "#/admin/users";
  window.history.replaceState(null, "", id ? `${base}?user=${encodeURIComponent(id)}` : base);
}

function initials(user: User): string {
  const words = (user.display_name || user.username).trim().split(/\s+/);
  return ((words[0]?.[0] ?? "") + (words.length > 1 ? words[words.length - 1][0] : (words[0]?.[1] ?? ""))).toUpperCase();
}

export default function UsersPage({ auth }: { auth: AuthInfo }) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [orgFilter, setOrgFilter] = useState<string>("");
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(userInHash);
  // Kept between users, so opening the next one shows the same tab.
  const [detailTab, setDetailTab] = useState<UserTab>("profile");

  useEffect(() => {
    const onHash = () => setSelectedId(userInHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const select = useCallback((id: string | null) => {
    setSelectedId(id);
    setUserInHash(id);
  }, []);

  useEffect(() => {
    api.organizations.list().then(setOrganizations).catch(reportLoadError);
  }, []);

  function load() {
    api
      .users.list(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then(setUsers)
      .catch(() => setError("Couldn't load users — is the API reachable?"));
  }

  useEffect(load, [orgFilter]);

  const filtered = useMemo(() => {
    if (!users) return [];
    const q = query.trim().toLowerCase();
    if (!q) return users;
    return users.filter(
      (u) =>
        u.username.toLowerCase().includes(q) ||
        (u.email ?? "").toLowerCase().includes(q) ||
        (u.display_name ?? "").toLowerCase().includes(q)
    );
  }, [users, query]);

  const orgName = (id: string) => organizations.find((o) => o.id === id)?.name ?? id;

  const selected = users?.find((u) => u.id === selectedId) ?? null;
  const close = useCallback(() => select(null), [select]);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Users</h1>
          <p className="page-subtitle">Create accounts and manage their roles, direct permission grants, and status.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setCreateOpen(true)}>
          + New user
        </button>
      </div>

      <div className="gallery-toolbar">
        <div className="search">
          <input
            type="text"
            placeholder="Search by username, email, or display name…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
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
      {users === null && !error && (
        <TableSkeleton
          columns={["Username", "Contact", ...(auth.isSuperuser ? ["Organization"] : []), "Auth", "Status", "Last login"]}
        />
      )}

      {users !== null && filtered.length === 0 && (
        <div className="empty-state">
          <p>{users.length === 0 ? "No users yet." : "No users match that search."}</p>
        </div>
      )}

      {filtered.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Contact</th>
              {auth.isSuperuser && <th>Organization</th>}
              <th>Auth</th>
              <th>Status</th>
              <th>Last login</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => (
              <tr
                key={u.id}
                className={selectedId === u.id ? "active-row" : ""}
                onClick={() => select(u.id)}
              >
                <td className="mono">{u.username}</td>
                <td>
                  {u.display_name && <div>{u.display_name}</div>}
                  <span className="muted">{u.email ?? "—"}</span>
                </td>
                {auth.isSuperuser && <td>{orgName(u.org_id)}</td>}
                <td>
                  <span className={`badge badge-${u.auth_source}`}>{u.auth_source}</span>
                </td>
                <td>
                  <StatusBadges user={u} />
                </td>
                <td className="muted">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <DetailModal
          label={`User ${selected.username}`}
          title={selected.display_name || selected.username}
          subtitle={
            <>
              <span className="font-mono">{selected.username}</span>
              {selected.email && <> · {selected.email}</>}
              {auth.isSuperuser && <> · {orgName(selected.org_id)}</>}
              {" · "}
              {selected.last_login_at ? `last signed in ${new Date(selected.last_login_at).toLocaleString()}` : "never signed in"}
            </>
          }
          leading={
            <span
              className="grid size-11 shrink-0 place-items-center rounded-full bg-accent-soft font-display text-[0.95rem] font-semibold text-accent-strong ring-1 ring-accent-border"
              aria-hidden="true"
            >
              {initials(selected)}
            </span>
          }
          badges={
            <>
              <span className={`badge badge-${selected.auth_source}`}>{selected.auth_source}</span>
              <StatusBadges user={selected} />
            </>
          }
          onClose={close}
        >
          <UserDetailPanel
            key={selected.id}
            user={selected}
            tab={detailTab}
            onTabChange={setDetailTab}
            canViewAudit={has(auth, "audit:view")}
            isSuperuser={auth.isSuperuser}
            canGrantTemplates={has(auth, "report:manage")}
            onUpdated={(updated) => setUsers((prev) => prev?.map((x) => (x.id === updated.id ? updated : x)) ?? null)}
          />
        </DetailModal>
      )}

      <UserFormDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(user) => setUsers((prev) => [...(prev ?? []), user])}
        organizations={organizations.length > 0 ? organizations : [{ id: auth.orgId ?? "root", name: auth.orgId ?? "root", parent_org_id: null, is_active: true, created_at: "" }]}
        defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || "root"}
      />
    </div>
  );
}
