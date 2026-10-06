import { useEffect, useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import AuditFeed from "../../components/AuditFeed";
import { PillsSkeleton } from "../../components/Skeletons";
import type { EffectivePermissions, Grant, Role, User } from "../../types";
import ResetPasswordDialog from "./ResetPasswordDialog";

type Tab = "profile" | "access" | "activity";

/** <input type="date"> gives a bare "2026-01-01" — as a plain string that
 * sorts *before* any same-day timestamp (rbac.py's expiry check is a
 * lexicographic string compare against an ISO instant), so a bare date
 * would read as already-expired the moment it's granted. Pin it to the
 * end of that day instead. */
function toExpiresAt(dateInput: string): string | null {
  return dateInput ? `${dateInput}T23:59:59Z` : null;
}

export default function UserDetailPanel({
  user,
  onUpdated,
  canViewAudit = false,
}: {
  user: User;
  onUpdated: (u: User) => void;
  // Reading the audit trail is its own permission (audit:view), narrower than
  // user:manage -- so the Activity tab only shows for someone who holds it.
  canViewAudit?: boolean;
}) {
  const [tab, setTab] = useState<Tab>("profile");

  const [email, setEmail] = useState(user.email ?? "");
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [isActive, setIsActive] = useState(user.is_active);
  const [isLocked, setIsLocked] = useState(user.is_locked);
  const [mustChangePassword, setMustChangePassword] = useState(user.must_change_password);
  const [resetPasswordOpen, setResetPasswordOpen] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSaved, setProfileSaved] = useState(false);

  const [effective, setEffective] = useState<EffectivePermissions | null>(null);
  const [roleGrants, setRoleGrants] = useState<Grant[] | null>(null);
  const [permGrants, setPermGrants] = useState<Grant[] | null>(null);
  const [orgRoles, setOrgRoles] = useState<Role[] | null>(null);
  const [catalog, setCatalog] = useState<string[] | null>(null);
  const [grantRoleId, setGrantRoleId] = useState("");
  const [grantPermCode, setGrantPermCode] = useState("");
  const [grantExpiry, setGrantExpiry] = useState("");
  const [accessError, setAccessError] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<{ kind: "role" | "permission"; id: string } | null>(null);
  const [confirmResetTotp, setConfirmResetTotp] = useState(false);

  // A reset (or the user changing their own password) flips this on the server;
  // follow it rather than keep showing what was true when the panel opened.
  useEffect(() => setMustChangePassword(user.must_change_password), [user.must_change_password]);

  function loadAccess() {
    api.users.permissions(user.id).then(setEffective).catch(() => {});
    api.grants.roles.list(user.id).then(setRoleGrants).catch(() => {});
    api.grants.permissions.list(user.id).then(setPermGrants).catch(() => {});
    api.roles.list(user.org_id).then(setOrgRoles).catch(() => {});
    api.permissions
      .list()
      .then((list) => setCatalog(list.map((p) => p.code)))
      .catch(() => {});
  }

  useEffect(() => {
    if (tab === "access") loadAccess();
    // loadAccess is re-created each render but only depends on user.id
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, user.id]);

  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    setSavingProfile(true);
    setProfileError(null);
    setProfileSaved(false);
    try {
      const updated = await api.users.update(user.id, {
        email: email || null,
        display_name: displayName || null,
        is_active: isActive,
        is_locked: isLocked,
        // Only local accounts have a password to expire; the server rejects it for ldap.
        ...(user.auth_source === "local" ? { must_change_password: mustChangePassword } : {}),
      });
      onUpdated(updated);
      setProfileSaved(true);
    } catch (err) {
      setProfileError(err instanceof ApiError ? err.message : "Couldn't save");
    } finally {
      setSavingProfile(false);
    }
  }

  async function grantRole() {
    if (!grantRoleId) return;
    setAccessError(null);
    try {
      await api.grants.roles.grant(user.id, grantRoleId, toExpiresAt(grantExpiry));
      setGrantRoleId("");
      setGrantExpiry("");
      loadAccess();
    } catch (err) {
      setAccessError(err instanceof ApiError ? err.message : "Couldn't grant role");
    }
  }

  async function grantPermission() {
    if (!grantPermCode) return;
    setAccessError(null);
    try {
      await api.grants.permissions.grant(user.id, grantPermCode, toExpiresAt(grantExpiry));
      setGrantPermCode("");
      setGrantExpiry("");
      loadAccess();
    } catch (err) {
      setAccessError(err instanceof ApiError ? err.message : "Couldn't grant permission");
    }
  }

  async function resetTotp() {
    try {
      onUpdated(await api.users.update(user.id, { reset_totp: true }));
    } catch (err) {
      setProfileError(err instanceof ApiError ? err.message : "Couldn't reset two-factor authentication");
    } finally {
      setConfirmResetTotp(false);
    }
  }

  async function confirmRevoke() {
    if (!revokeTarget) return;
    try {
      if (revokeTarget.kind === "role") await api.grants.roles.revoke(revokeTarget.id);
      else await api.grants.permissions.revoke(revokeTarget.id);
      loadAccess();
    } catch (err) {
      setAccessError(err instanceof ApiError ? err.message : "Couldn't revoke");
    } finally {
      setRevokeTarget(null);
    }
  }

  return (
    <div className="admin-detail" onClick={(e) => e.stopPropagation()}>
      <div className="tabs">
        <button type="button" className={`tab ${tab === "profile" ? "active" : ""}`} onClick={() => setTab("profile")}>
          Profile
        </button>
        <button type="button" className={`tab ${tab === "access" ? "active" : ""}`} onClick={() => setTab("access")}>
          Roles &amp; permissions
        </button>
        {canViewAudit && (
          <button type="button" className={`tab ${tab === "activity" ? "active" : ""}`} onClick={() => setTab("activity")}>
            Activity
          </button>
        )}
      </div>

      {tab === "activity" && canViewAudit && (
        <div>
          <p className="muted" style={{ fontSize: "0.8rem", margin: "0 0 10px" }}>
            Changes made to this account — role and permission grants, password and 2FA resets, status changes.
          </p>
          <AuditFeed query={{ entityType: "user", entityId: user.id }} limit={30} emptyText="No changes recorded for this account." />
        </div>
      )}

      {tab === "profile" && (
        <form onSubmit={saveProfile} className="stack">
          <div className="row">
            <label>
              <span>Email</span>
              <input type="text" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label>
              <span>Display name</span>
              <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </label>
          </div>
          <div className="row">
            <label className="checkbox-label">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} /> Active
            </label>
            <label className="checkbox-label">
              <input type="checkbox" checked={isLocked} onChange={(e) => setIsLocked(e.target.checked)} /> Locked
            </label>
          </div>
          {user.totp_enabled && (
            <div className="row" style={{ alignItems: "center" }}>
              <span className="badge badge-enabled">2FA enabled</span>
              <button type="button" className="link-btn" onClick={() => setConfirmResetTotp(true)}>
                Reset 2FA
              </button>
              <span className="muted" style={{ fontSize: "0.78rem" }}>
                Lost-authenticator recovery — clears their enrollment so they can set up a new device.
              </span>
            </div>
          )}
          {user.auth_source === "local" ? (
            <>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={mustChangePassword}
                  onChange={(e) => setMustChangePassword(e.target.checked)}
                />
                Require a password change at next sign-in
              </label>
              <div className="password-status">
                <span className="field-label">Password</span>
                {user.must_change_password && <span className="badge badge-pending">change required</span>}
                <button type="button" className="link-btn" onClick={() => setResetPasswordOpen(true)}>
                  Reset password…
                </button>
                <span className="muted" style={{ fontSize: "0.78rem" }}>
                  Forgotten, or a new hire's first — generate a temporary one or set it yourself.
                </span>
              </div>
            </>
          ) : (
            <p className="muted" style={{ fontSize: "0.78rem", margin: 0 }}>
              This account signs in with LDAP / Active Directory, so its password is managed in the directory.
            </p>
          )}
          {profileError && <p className="alert alert-error">{profileError}</p>}
          {profileSaved && <p className="alert alert-success">Saved.</p>}
          <div>
            <button type="submit" className="btn btn-primary btn-sm" disabled={savingProfile}>
              {savingProfile && <span className="spinner" />}
              Save
            </button>
          </div>
        </form>
      )}

      {tab === "access" && (
        <div className="stack">
          <div>
            <span className="field-label">Effective permissions</span>
            <div className="field-pills">
              {effective && effective.permissions.length === 0 && <span className="muted">None</span>}
              {effective?.permissions.map((p) => (
                <span key={p} className="field-pill">
                  {p}
                </span>
              ))}
              {!effective && <PillsSkeleton />}
            </div>
          </div>

          {accessError && <p className="alert alert-error">{accessError}</p>}

          <div className="grant-block">
            <span className="field-label">Role grants</span>
            {roleGrants
              ?.filter((g) => g.is_active)
              .map((g) => (
                <div key={g.id} className="grant-row">
                  <span className="mono">{orgRoles?.find((r) => r.id === g.role_id)?.name ?? g.role_id}</span>
                  <span className="muted">
                    {g.expires_at ? `expires ${new Date(g.expires_at).toLocaleDateString()}` : "no expiry"}
                  </span>
                  <button type="button" className="link-btn" onClick={() => setRevokeTarget({ kind: "role", id: g.id })}>
                    revoke
                  </button>
                </div>
              ))}
            {roleGrants && roleGrants.filter((g) => g.is_active).length === 0 && (
              <p className="muted">No roles granted.</p>
            )}
            <div className="row grant-form">
              <select value={grantRoleId} onChange={(e) => setGrantRoleId(e.target.value)}>
                <option value="">Grant a role…</option>
                {orgRoles?.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
              <input type="date" value={grantExpiry} onChange={(e) => setGrantExpiry(e.target.value)} title="Optional expiry date" />
              <button type="button" className="btn btn-primary" onClick={grantRole} disabled={!grantRoleId}>
                <Plus size={14} /> Grant
              </button>
            </div>
          </div>

          <div className="grant-block">
            <span className="field-label">Direct permission grants</span>
            {permGrants
              ?.filter((g) => g.is_active)
              .map((g) => (
                <div key={g.id} className="grant-row">
                  <span className="mono">{g.permission_code}</span>
                  <span className="muted">
                    {g.expires_at ? `expires ${new Date(g.expires_at).toLocaleDateString()}` : "no expiry"}
                  </span>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => setRevokeTarget({ kind: "permission", id: g.id })}
                  >
                    revoke
                  </button>
                </div>
              ))}
            {permGrants && permGrants.filter((g) => g.is_active).length === 0 && (
              <p className="muted">No direct grants.</p>
            )}
            <div className="row grant-form">
              <select value={grantPermCode} onChange={(e) => setGrantPermCode(e.target.value)}>
                <option value="">Grant a permission…</option>
                {catalog?.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
              <input type="date" value={grantExpiry} onChange={(e) => setGrantExpiry(e.target.value)} title="Optional expiry date" />
              <button type="button" className="btn btn-primary" onClick={grantPermission} disabled={!grantPermCode}>
                <Plus size={14} /> Grant
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke grant"
        body="This takes effect immediately."
        confirmLabel="Revoke"
        onConfirm={confirmRevoke}
        onCancel={() => setRevokeTarget(null)}
      />

      <ResetPasswordDialog
        user={resetPasswordOpen ? user : null}
        onClose={() => setResetPasswordOpen(false)}
        onReset={onUpdated}
      />

      <ConfirmDialog
        open={confirmResetTotp}
        title="Reset two-factor authentication"
        body={`${user.username} will need to re-enroll a new authenticator from Settings > Access before signing back in with 2FA.`}
        confirmLabel="Reset 2FA"
        onConfirm={resetTotp}
        onCancel={() => setConfirmResetTotp(false)}
      />
    </div>
  );
}
