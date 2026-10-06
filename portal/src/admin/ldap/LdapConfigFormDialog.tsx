import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import { useDialogRef } from "../../hooks";
import type { LdapBindMethod, LdapConfig, Organization } from "../../types";

import ModalClose from "../../components/ModalClose";
export default function LdapConfigFormDialog({
  open,
  onClose,
  onCreated,
  organizations,
  defaultOrgId,
  isSuperuser,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (config: LdapConfig) => void;
  organizations: Organization[];
  defaultOrgId: string;
  isSuperuser: boolean;
}) {
  const [orgId, setOrgId] = useState<string>(defaultOrgId);
  const [serverUri, setServerUri] = useState("ldap://localhost:389");
  const [bindMethod, setBindMethod] = useState<LdapBindMethod>("direct_bind");
  const [baseDn, setBaseDn] = useState("");
  const [directBindDnTemplate, setDirectBindDnTemplate] = useState("uid={username},ou=people,dc=example,dc=com");
  const [serviceBindDn, setServiceBindDn] = useState("");
  const [serviceBindPasswordEnv, setServiceBindPasswordEnv] = useState("LDAP_SERVICE_BIND_PASSWORD");
  const [userSearchFilter, setUserSearchFilter] = useState("(sAMAccountName={username})");
  const [upnDomain, setUpnDomain] = useState("");
  const [groupSearchBase, setGroupSearchBase] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const ref = useDialogRef(open, () => {
    setOrgId(defaultOrgId);
    setServerUri("ldap://localhost:389");
    setBindMethod("direct_bind");
    setBaseDn("");
    setDirectBindDnTemplate("uid={username},ou=people,dc=example,dc=com");
    setServiceBindDn("");
    setServiceBindPasswordEnv("LDAP_SERVICE_BIND_PASSWORD");
    setUserSearchFilter("(sAMAccountName={username})");
    setUpnDomain("");
    setGroupSearchBase("");
    setIsEnabled(true);
    setError(null);
  });

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const config = await api.ldap.create(isSuperuser && orgId === "" ? null : orgId, {
        server_uri: serverUri,
        bind_method: bindMethod,
        base_dn: baseDn,
        direct_bind_dn_template: bindMethod === "direct_bind" ? directBindDnTemplate : null,
        service_bind_dn: bindMethod === "search_bind" ? serviceBindDn : null,
        service_bind_password_env: bindMethod === "search_bind" ? serviceBindPasswordEnv : null,
        user_search_filter: bindMethod === "search_bind" ? userSearchFilter : null,
        upn_domain: bindMethod === "upn_bind" ? upnDomain : null,
        group_search_base: groupSearchBase || null,
        is_enabled: isEnabled,
      });
      onCreated(config);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the LDAP configuration");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">New AD / LDAP configuration</h2>
      <p className="panel-subtitle">Group→role mappings and a connection test are available after creation.</p>
      <form onSubmit={handleSubmit}>
        <label>
          <span>Server URI</span>
          <input type="text" required value={serverUri} onChange={(e) => setServerUri(e.target.value)} />
        </label>
        <div className="row">
          <label>
            <span>Bind method</span>
            <select value={bindMethod} onChange={(e) => setBindMethod(e.target.value as LdapBindMethod)}>
              <option value="direct_bind">Direct bind</option>
              <option value="search_bind">Search + bind (service account)</option>
              <option value="upn_bind">UPN bind (user@domain)</option>
            </select>
          </label>
          <label>
            <span>Base DN</span>
            <input type="text" required value={baseDn} onChange={(e) => setBaseDn(e.target.value)} placeholder="dc=example,dc=com" />
          </label>
        </div>

        {isSuperuser && (
          <label>
            <span>Organization</span>
            <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              <option value="">System-wide default</option>
              {organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {bindMethod === "direct_bind" && (
          <label>
            <span>Direct bind DN template</span>
            <input
              type="text"
              required
              value={directBindDnTemplate}
              onChange={(e) => setDirectBindDnTemplate(e.target.value)}
            />
            <p className="field-hint">{"{username}"} is substituted with the login name.</p>
          </label>
        )}

        {bindMethod === "search_bind" && (
          <>
            <div className="row">
              <label>
                <span>Service bind DN</span>
                <input
                  type="text"
                  required
                  value={serviceBindDn}
                  onChange={(e) => setServiceBindDn(e.target.value)}
                  placeholder="cn=service-account,dc=example,dc=com"
                />
              </label>
              <label>
                <span>Service bind password env var</span>
                <input
                  type="text"
                  required
                  value={serviceBindPasswordEnv}
                  onChange={(e) => setServiceBindPasswordEnv(e.target.value)}
                />
              </label>
            </div>
            <label>
              <span>User search filter</span>
              <input type="text" required value={userSearchFilter} onChange={(e) => setUserSearchFilter(e.target.value)} />
              <p className="field-hint">The secret itself lives only in the named environment variable, never in this config.</p>
            </label>
          </>
        )}

        {bindMethod === "upn_bind" && (
          <label>
            <span>UPN domain</span>
            <input type="text" required value={upnDomain} onChange={(e) => setUpnDomain(e.target.value)} placeholder="example.com" />
          </label>
        )}

        <label>
          <span>Group search base (optional)</span>
          <input
            type="text"
            value={groupSearchBase}
            onChange={(e) => setGroupSearchBase(e.target.value)}
            placeholder="ou=groups,dc=example,dc=com"
          />
          <p className="field-hint">Used to resolve group membership for group→role sync on login.</p>
        </label>

        <label className="checkbox-label">
          <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} /> Enabled
        </label>

        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            Create
          </button>
        </div>
      </form>
    </dialog>
  );
}
