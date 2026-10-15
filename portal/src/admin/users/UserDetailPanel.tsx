import { useEffect, useState, type FormEvent } from "react";
import FieldLabel, { DISPLAY_NAME_MAX, EMAIL_MAX } from "../../components/FieldLabel";
import { Plus } from "lucide-react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import AuditFeed from "../../components/AuditFeed";
import type { Grant, Role, User, UserOverview } from "../../types";
import ResetPasswordDialog from "./ResetPasswordDialog";
import { GrantAccessDialog, type GrantKind } from "./UserGrants";
import { OverviewStrip, PermissionMap, roleLabel, TemplatesTab, WhereTheyHaveAccess, type StripTarget } from "./UserOverview";

export type UserTab = "profile" | "templates" | "access" | "activity";
type Tab = UserTab;

export default function UserDetailPanel({
  user,
  onUpdated,
  canViewAudit = false,
  isSuperuser = false,
  canGrantTemplates = false,
  tab: tabProp,
  onTabChange,
}: {
  user: User;
  /** Controlled tab, when the page keeps it across users; otherwise the panel keeps its own. */
  tab?: UserTab;
  onTabChange?: (tab: UserTab) => void;
  onUpdated: (u: User) => void;
  // Reading the audit trail is its own permission (audit:view), narrower than
  // user:manage -- so the Activity tab only shows for someone who holds it.
  canViewAudit?: boolean;
  /** The signed-in person is a superuser: only they may grant the system-wide ROLE_ADMINISTRATOR (the API refuses
   * anyone else), so only they are offered it. */
  isSuperuser?: boolean;
  /** report:manage -- granting (and revoking) access to one template needs it. */
  canGrantTemplates?: boolean;
}) {
  const [ownTab, setOwnTab] = useState<Tab>("profile");
  const tab = tabProp === "activity" && !canViewAudit ? "profile" : (tabProp ?? ownTab);
  const setTab = (next: Tab) => (onTabChange ? onTabChange(next) : setOwnTab(next));

  // A card in the strip opens its tab and brings its section into view -- also when that tab is already open.
  const [jump, setJump] = useState<{ target: StripTarget; at: number } | null>(null); // `at`: a repeat click is a new jump
  function openFromStrip(target: StripTarget) {
    setTab(target === "templates" ? "templates" : "access");
    setJump({ target, at: Date.now() });
  }


  const [email, setEmail] = useState(user.email ?? "");
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [isActive, setIsActive] = useState(user.is_active);
  const [isLocked, setIsLocked] = useState(user.is_locked);
  const [mustChangePassword, setMustChangePassword] = useState(user.must_change_password);
  const [resetPasswordOpen, setResetPasswordOpen] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSaved, setProfileSaved] = useState(false);

  const [overview, setOverview] = useState<UserOverview | null>(null);
  const [roleGrants, setRoleGrants] = useState<Grant[] | null>(null);
  const [permGrants, setPermGrants] = useState<Grant[] | null>(null);
  const [orgRoles, setOrgRoles] = useState<Role[] | null>(null);
  // Roles with no organization -- ROLE_ADMINISTRATOR: every permission, in every organization.
  const [systemRoles, setSystemRoles] = useState<Role[]>([]);
  // Granting ROLE_ADMINISTRATOR waits for a confirmation.
  const [pendingSystem, setPendingSystem] = useState<{ role: Role; expiresAt: string | null } | null>(null);
  const [catalog, setCatalog] = useState<{ code: string; description: string }[] | null>(null);
  // The "Grant access" dialog, and which kind it opens on.
  const [granting, setGranting] = useState<GrantKind | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<{ kind: "role" | "permission" | "report"; id: string } | null>(null);
  const [confirmResetTotp, setConfirmResetTotp] = useState(false);

  // A reset (or the user changing their own password) flips this on the server;
  // follow it rather than keep showing what was true when the panel opened.
  useEffect(() => setMustChangePassword(user.must_change_password), [user.must_change_password]);

  // Waits for the section to be there (the tab just switched, or the overview is still loading), then forgets the
  // jump -- so a later reload of the overview never scrolls on its own.
  useEffect(() => {
    if (!jump) return;
    // The access tab's layout settles once the permission catalog is in; jumping earlier lands short.
    if (jump.target !== "templates" && (!overview || !catalog)) return;
    const frame = requestAnimationFrame(() => {
      const el = document.getElementById(`user-section-${jump.target}`);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      el.classList.remove("section-flash");
      void el.offsetWidth; // restart the glow on a second click
      el.classList.add("section-flash");
      setJump(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [jump, overview, catalog, tab]);

  function loadOverview() {
    api.users.overview(user.id).then(setOverview).catch(() => {});
  }

  // The strip above the tabs needs it whichever tab is open.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(loadOverview, [user.id]);

  function loadAccess() {
    api.grants.roles.list(user.id).then(setRoleGrants).catch(() => {});
    api.grants.permissions.list(user.id).then(setPermGrants).catch(() => {});
    api.roles.list(user.org_id).then(setOrgRoles).catch(() => {});
    if (isSuperuser) {
      api.roles
        .list()
        .then((all) => setSystemRoles(all.filter((r) => r.org_id === null)))
        .catch(() => {});
    }
    api.permissions
      .list()
      .then((list) => setCatalog(list.map((p) => ({ code: p.code, description: p.description }))))
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
        // "" clears a field; null would leave it unchanged.
        email: email.trim(),
        display_name: displayName.trim(),
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

  const allRoles = [...(orgRoles ?? []), ...systemRoles];

  /** From the role picker: ROLE_ADMINISTRATOR asks first; anything else is granted now (errors go back to it). */
  async function grantRole(role: Role, expiresAt: string | null) {
    if (role.org_id === null) {
      setPendingSystem({ role, expiresAt });
      return;
    }
    await api.grants.roles.grant(user.id, role.id, expiresAt);
    loadAccess();
    loadOverview();
  }

  async function grantSystemRole() {
    if (!pendingSystem) return;
    const { role, expiresAt } = pendingSystem;
    setPendingSystem(null);
    setAccessError(null);
    try {
      await api.grants.roles.grant(user.id, role.id, expiresAt);
      loadAccess();
      loadOverview();
    } catch (err) {
      setAccessError(err instanceof ApiError ? err.message : "Couldn't grant the role");
    }
  }

  async function grantPermission(code: string, expiresAt: string | null) {
    await api.grants.permissions.grant(user.id, code, expiresAt);
    loadAccess();
    loadOverview();
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
      else if (revokeTarget.kind === "report") await api.grants.reports.revoke(revokeTarget.id);
      else await api.grants.permissions.revoke(revokeTarget.id);
      loadAccess();
      loadOverview();
    } catch (err) {
      setAccessError(err instanceof ApiError ? err.message : "Couldn't revoke");
    } finally {
      setRevokeTarget(null);
    }
  }

  return (
    <div className="admin-detail" onClick={(e) => e.stopPropagation()}>
      <OverviewStrip overview={overview} onOpen={openFromStrip} />
      <div className="tabs">
        <button type="button" className={`tab ${tab === "profile" ? "active" : ""}`} onClick={() => setTab("profile")}>
          Profile
        </button>
        <button type="button" className={`tab ${tab === "templates" ? "active" : ""}`} onClick={() => setTab("templates")}>
          Templates{overview && overview.templates.contributed > 0 ? ` (${overview.templates.contributed})` : ""}
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

      {tab === "templates" && (
        <div id="user-section-templates" className="scroll-mt-4">
          <TemplatesTab overview={overview} />
        </div>
      )}

      {tab === "profile" && (
        <form onSubmit={saveProfile} className="stack">
          <div className="row">
            <label>
              <FieldLabel length={email.length} max={EMAIL_MAX}>
                Email
              </FieldLabel>
              <input type="email" maxLength={EMAIL_MAX} value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label>
              <FieldLabel length={displayName.length} max={DISPLAY_NAME_MAX}>
                Display name
              </FieldLabel>
              <input type="text" maxLength={DISPLAY_NAME_MAX} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
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
          <PermissionMap overview={overview} catalog={catalog} />
          <WhereTheyHaveAccess
            overview={overview}
            onRevokeReport={canGrantTemplates ? (grantId) => setRevokeTarget({ kind: "report", id: grantId }) : undefined}
            onGrantTemplate={canGrantTemplates ? () => setGranting("template") : undefined}
          />

          {accessError && <p className="alert alert-error">{accessError}</p>}

          <section className="flex flex-col gap-2">
            <div className="flex items-center gap-3">
              <span className="field-label m-0">Granted to them</span>
              <span className="text-[0.74rem] text-text-faint">roles and permissions given to this account itself</span>
              <button type="button" className="btn btn-primary btn-sm ml-auto" onClick={() => setGranting("role")}>
                <Plus size={14} /> Grant access…
              </button>
            </div>
            <div className="grant-block">
              <span className="text-[0.74rem] font-semibold tracking-[0.04em] text-text-dim uppercase">Roles</span>
              {roleGrants
                ?.filter((g) => g.is_active)
                .map((g) => (
                  <div key={g.id} className="grant-row">
                    <span className="mono" title={allRoles.find((r) => r.id === g.role_id)?.name}>
                      {roleLabel(allRoles.find((r) => r.id === g.role_id)?.name ?? g.role_id ?? "")}
                      {systemRoles.some((r) => r.id === g.role_id) && <span className="badge badge-pending ml-1.5">all organizations</span>}
                    </span>
                    <span className="muted">{g.expires_at ? `expires ${new Date(g.expires_at).toLocaleDateString()}` : "no expiry"}</span>
                    <button type="button" className="link-btn" onClick={() => setRevokeTarget({ kind: "role", id: g.id })}>
                      revoke
                    </button>
                  </div>
                ))}
              {roleGrants && roleGrants.filter((g) => g.is_active).length === 0 && (
                <p className="muted m-0 py-1.5 text-[0.82rem]">
                  No roles.{" "}
                  <button type="button" className="link-btn" onClick={() => setGranting("role")}>
                    Grant one
                  </button>
                </p>
              )}
            </div>
            <div className="grant-block">
              <span className="text-[0.74rem] font-semibold tracking-[0.04em] text-text-dim uppercase">Direct permissions</span>
              {permGrants
                ?.filter((g) => g.is_active)
                .map((g) => (
                  <div key={g.id} className="grant-row">
                    <span className="mono">{g.permission_code}</span>
                    <span className="muted">{g.expires_at ? `expires ${new Date(g.expires_at).toLocaleDateString()}` : "no expiry"}</span>
                    <button type="button" className="link-btn" onClick={() => setRevokeTarget({ kind: "permission", id: g.id })}>
                      revoke
                    </button>
                  </div>
                ))}
              {permGrants && permGrants.filter((g) => g.is_active).length === 0 && (
                <p className="muted m-0 py-1.5 text-[0.82rem]">None — their permissions all come from roles.</p>
              )}
            </div>
          </section>
        </div>
      )}

      <GrantAccessDialog
        open={granting !== null}
        initialKind={granting ?? "role"}
        user={user}
        orgRoles={orgRoles}
        systemRoles={systemRoles}
        heldRoleIds={new Set((roleGrants ?? []).filter((g) => g.is_active && g.role_id).map((g) => g.role_id!))}
        heldPermissions={new Set((overview?.permissions ?? []).map((p) => p.code))}
        catalog={catalog}
        templateGrants={new Map((overview?.report_grants ?? []).filter((g) => !g.via_role).map((g) => [g.report_id, g.level] as const))}
        canGrantTemplates={canGrantTemplates}
        onGrantRole={grantRole}
        onGrantPermission={grantPermission}
        onGrantedTemplate={() => {
          loadAccess();
          loadOverview();
        }}
        onClose={() => setGranting(null)}
      />

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke grant"
        body="This takes effect immediately."
        confirmLabel="Revoke"
        onConfirm={confirmRevoke}
        onCancel={() => setRevokeTarget(null)}
      />

      <ConfirmDialog
        open={pendingSystem !== null}
        title="Make them a system administrator?"
        body={`${user.username} gets every permission in every organization: users, roles, settings and templates everywhere, and permissions added in later versions too. ${
          pendingSystem?.expiresAt
            ? `It ends on ${new Date(pendingSystem.expiresAt).toLocaleDateString()}.`
            : "It has no end date; you can set one first, or revoke it later."
        }`}
        confirmLabel="Grant administrator"
        onConfirm={() => void grantSystemRole()}
        onCancel={() => setPendingSystem(null)}
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
