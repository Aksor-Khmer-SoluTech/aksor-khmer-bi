import { useEffect, useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import type { LdapBindMethod, LdapConfig, LdapGroupMapping, LdapTestResult, Role } from "../../types";

type Tab = "settings" | "groups" | "test";

export default function LdapConfigDetailPanel({
  config,
  onUpdated,
  onDeleted,
}: {
  config: LdapConfig;
  onUpdated: (c: LdapConfig) => void;
  onDeleted: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("settings");

  const [serverUri, setServerUri] = useState(config.server_uri);
  const [bindMethod, setBindMethod] = useState<LdapBindMethod>(config.bind_method);
  const [baseDn, setBaseDn] = useState(config.base_dn);
  const [directBindDnTemplate, setDirectBindDnTemplate] = useState(config.direct_bind_dn_template ?? "");
  const [serviceBindDn, setServiceBindDn] = useState(config.service_bind_dn ?? "");
  const [serviceBindPasswordEnv, setServiceBindPasswordEnv] = useState(config.service_bind_password_env ?? "");
  const [userSearchFilter, setUserSearchFilter] = useState(config.user_search_filter ?? "");
  const [upnDomain, setUpnDomain] = useState(config.upn_domain ?? "");
  const [groupSearchBase, setGroupSearchBase] = useState(config.group_search_base ?? "");
  const [isEnabled, setIsEnabled] = useState(config.is_enabled);
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const [mappings, setMappings] = useState<LdapGroupMapping[] | null>(null);
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [newGroupDn, setNewGroupDn] = useState("");
  const [newRoleId, setNewRoleId] = useState("");
  const [groupsError, setGroupsError] = useState<string | null>(null);

  const [testUsername, setTestUsername] = useState("");
  const [testPassword, setTestPassword] = useState("");
  const [testPending, setTestPending] = useState(false);
  const [testResult, setTestResult] = useState<LdapTestResult | null>(null);

  function loadGroups() {
    api.ldap.groupMappings.list(config.id).then(setMappings).catch(() => {});
    api.roles
      .list(config.org_id ?? undefined)
      .then((all) => setRoles(all.filter((r) => r.org_id === config.org_id)))
      .catch(() => {});
  }

  useEffect(() => {
    if (tab === "groups") loadGroups();
    // loadGroups is re-created each render but only depends on config.id/org_id
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, config.id]);

  async function saveSettings(e: FormEvent) {
    e.preventDefault();
    setSavingSettings(true);
    setSettingsError(null);
    setSettingsSaved(false);
    try {
      const updated = await api.ldap.update(config.id, {
        server_uri: serverUri,
        bind_method: bindMethod,
        base_dn: baseDn,
        direct_bind_dn_template: bindMethod === "direct_bind" ? directBindDnTemplate || null : null,
        service_bind_dn: bindMethod === "search_bind" ? serviceBindDn || null : null,
        service_bind_password_env: bindMethod === "search_bind" ? serviceBindPasswordEnv || null : null,
        user_search_filter: bindMethod === "search_bind" ? userSearchFilter || null : null,
        upn_domain: bindMethod === "upn_bind" ? upnDomain || null : null,
        group_search_base: groupSearchBase || null,
        is_enabled: isEnabled,
      });
      onUpdated(updated);
      setSettingsSaved(true);
    } catch (err) {
      setSettingsError(err instanceof ApiError ? err.message : "Couldn't save");
    } finally {
      setSavingSettings(false);
    }
  }

  async function confirmDelete() {
    try {
      await api.ldap.delete(config.id);
      onDeleted(config.id);
    } catch (err) {
      setSettingsError(err instanceof ApiError ? err.message : "Couldn't delete");
    } finally {
      setDeleteOpen(false);
    }
  }

  async function addMapping() {
    if (!newGroupDn || !newRoleId) return;
    setGroupsError(null);
    try {
      await api.ldap.groupMappings.create(config.id, newGroupDn, newRoleId);
      setNewGroupDn("");
      setNewRoleId("");
      loadGroups();
    } catch (err) {
      setGroupsError(err instanceof ApiError ? err.message : "Couldn't add mapping");
    }
  }

  async function removeMapping(id: string) {
    setGroupsError(null);
    try {
      await api.ldap.groupMappings.delete(config.id, id);
      loadGroups();
    } catch (err) {
      setGroupsError(err instanceof ApiError ? err.message : "Couldn't remove mapping");
    }
  }

  async function runTest(e: FormEvent) {
    e.preventDefault();
    setTestPending(true);
    setTestResult(null);
    try {
      const result = await api.ldap.test(config.id, testUsername, testPassword);
      setTestResult(result);
    } catch (err) {
      setTestResult({ success: false, dn: null, groups: [], detail: err instanceof ApiError ? err.message : "Test failed" });
    } finally {
      setTestPending(false);
    }
  }

  return (
    <div className="admin-detail" onClick={(e) => e.stopPropagation()}>
      <div className="tabs">
        <button type="button" className={`tab ${tab === "settings" ? "active" : ""}`} onClick={() => setTab("settings")}>
          Settings
        </button>
        <button type="button" className={`tab ${tab === "groups" ? "active" : ""}`} onClick={() => setTab("groups")}>
          Group → role mapping
        </button>
        <button type="button" className={`tab ${tab === "test" ? "active" : ""}`} onClick={() => setTab("test")}>
          Test connection
        </button>
      </div>

      {tab === "settings" && (
        <form onSubmit={saveSettings} className="stack">
          <label>
            <span>Server URI</span>
            <input type="text" required value={serverUri} onChange={(e) => setServerUri(e.target.value)} />
          </label>
          <div className="row">
            <label>
              <span>Bind method</span>
              <select value={bindMethod} onChange={(e) => setBindMethod(e.target.value as LdapBindMethod)}>
                <option value="direct_bind">Direct bind</option>
                <option value="search_bind">Search + bind</option>
                <option value="upn_bind">UPN bind</option>
              </select>
            </label>
            <label>
              <span>Base DN</span>
              <input type="text" required value={baseDn} onChange={(e) => setBaseDn(e.target.value)} />
            </label>
          </div>

          {bindMethod === "direct_bind" && (
            <label>
              <span>Direct bind DN template</span>
              <input type="text" value={directBindDnTemplate} onChange={(e) => setDirectBindDnTemplate(e.target.value)} />
            </label>
          )}

          {bindMethod === "search_bind" && (
            <>
              <div className="row">
                <label>
                  <span>Service bind DN</span>
                  <input type="text" value={serviceBindDn} onChange={(e) => setServiceBindDn(e.target.value)} />
                </label>
                <label>
                  <span>Service bind password env var</span>
                  <input type="text" value={serviceBindPasswordEnv} onChange={(e) => setServiceBindPasswordEnv(e.target.value)} />
                </label>
              </div>
              <label>
                <span>User search filter</span>
                <input type="text" value={userSearchFilter} onChange={(e) => setUserSearchFilter(e.target.value)} />
              </label>
            </>
          )}

          {bindMethod === "upn_bind" && (
            <label>
              <span>UPN domain</span>
              <input type="text" value={upnDomain} onChange={(e) => setUpnDomain(e.target.value)} />
            </label>
          )}

          <label>
            <span>Group search base</span>
            <input type="text" value={groupSearchBase} onChange={(e) => setGroupSearchBase(e.target.value)} />
          </label>

          <label className="checkbox-label">
            <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} /> Enabled
          </label>

          {settingsError && <p className="alert alert-error">{settingsError}</p>}
          {settingsSaved && <p className="alert alert-success">Saved.</p>}
          <div className="row" style={{ justifyContent: "space-between" }}>
            <button type="button" className="btn btn-danger btn-sm" onClick={() => setDeleteOpen(true)}>
              Delete configuration
            </button>
            <button type="submit" className="btn btn-primary btn-sm" disabled={savingSettings}>
              {savingSettings && <span className="spinner" />}
              Save
            </button>
          </div>
        </form>
      )}

      {tab === "groups" && (
        <div className="stack">
          {groupsError && <p className="alert alert-error">{groupsError}</p>}
          <div className="grant-block">
            {mappings?.map((m) => (
              <div key={m.id} className="grant-row">
                <span className="mono">{m.group_dn}</span>
                <span className="muted">→ {roles?.find((r) => r.id === m.role_id)?.name ?? m.role_id}</span>
                <button type="button" className="link-btn" onClick={() => removeMapping(m.id)}>
                  remove
                </button>
              </div>
            ))}
            {mappings && mappings.length === 0 && <p className="muted">No group mappings yet.</p>}
            <div className="row grant-form">
              <input
                type="text"
                placeholder="cn=report-admins,ou=groups,dc=example,dc=com"
                value={newGroupDn}
                onChange={(e) => setNewGroupDn(e.target.value)}
              />
              <select value={newRoleId} onChange={(e) => setNewRoleId(e.target.value)}>
                <option value="">Map to role…</option>
                {roles?.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
              <button type="button" className="btn btn-primary" onClick={addMapping} disabled={!newGroupDn || !newRoleId}>
                <Plus size={14} /> Add
              </button>
            </div>
          </div>
        </div>
      )}

      {tab === "test" && (
        <form onSubmit={runTest} className="stack">
          <p className="muted">Attempts a real bind against this directory without creating or modifying a user.</p>
          <div className="row">
            <label>
              <span>Username</span>
              <input type="text" required value={testUsername} onChange={(e) => setTestUsername(e.target.value)} />
            </label>
            <label>
              <span>Password</span>
              <input type="password" required value={testPassword} onChange={(e) => setTestPassword(e.target.value)} />
            </label>
          </div>
          <div>
            <button type="submit" className="btn btn-primary btn-sm" disabled={testPending}>
              {testPending && <span className="spinner" />}
              Test bind
            </button>
          </div>
          {testResult && (
            <p className={`alert ${testResult.success ? "alert-success" : "alert-error"}`}>
              {testResult.success
                ? `Bind succeeded as ${testResult.dn}${testResult.groups.length ? ` — groups: ${testResult.groups.join(", ")}` : ""}`
                : testResult.detail || "Bind failed"}
            </p>
          )}
        </form>
      )}

      <ConfirmDialog
        open={deleteOpen}
        title="Delete LDAP configuration"
        body="Users who already authenticated via this directory keep their accounts; new logins against it will stop working."
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}
