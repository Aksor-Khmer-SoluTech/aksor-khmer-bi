import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import CredentialPicker, { defaultCredentialValue, type CredentialValue } from "../../components/CredentialPicker";
import { headersToText, parseHeaders } from "../../dataConfig";
import { useDialogRef } from "../../hooks";
import type { AuthInfo, Connection, ConnectionConfig, DataSourceAuth, Organization } from "../../types";
import { has } from "../sections";

import ModalClose from "../../components/ModalClose";
// Title has no server-side limit of its own (it only ever produces the slug
// below; the server validates that, not this) -- 120 is a generous, purely
// client-side cap. Name/Description/Base URL mirror the server's own limits
// (api/app/connections.py's MAX_NAME_LENGTH/MAX_BASE_URL_LENGTH,
// api/app/models/connections.py's RestConnectionConfig), so a visible
// counter here is never wrong about how much room is actually left.
const TITLE_MAX = 120;
const NAME_MAX = 64;
const DESCRIPTION_MAX = 500;
const BASE_URL_MAX = 500;

/** "ERP API" -> "erp-api": the shape a connection name takes (lowercase letters, digits, single hyphens/underscores). */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

function credentialToAuth(type: "bearer" | "basic", username: string, credential: CredentialValue): DataSourceAuth {
  const fromEnv = credential.source === "env";
  if (type === "bearer") {
    return fromEnv ? { type: "bearer", token_env: credential.env.trim() } : { type: "bearer", token_secret: credential.secret };
  }
  return fromEnv
    ? { type: "basic", username: username.trim(), password_env: credential.env.trim() }
    : { type: "basic", username: username.trim(), password_secret: credential.secret };
}

/** Create a connection, or edit one (mounted with a fresh `key` per open, like
 * the other admin dialogs, so its fields start right). The name is fixed once
 * created: reports refer to a connection by it, so renaming would break them
 * -- which is also why it's what carries a report from dev to production (the
 * same name, a different base URL in each). */
export default function ConnectionDialog({
  open,
  onClose,
  connection,
  organizations,
  defaultOrgId,
  auth,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  /** null = creating a new connection */
  connection: Connection | null;
  organizations: Organization[];
  defaultOrgId: string;
  auth: AuthInfo;
  onSaved: (saved: Connection, created: boolean) => void;
}) {
  const config = connection?.config as ConnectionConfig | undefined;
  const [name, setName] = useState(connection?.name ?? "");
  const [nameEdited, setNameEdited] = useState(false);
  const [title, setTitle] = useState(connection?.name ?? "");
  const [description, setDescription] = useState(connection?.description ?? "");
  const [baseUrl, setBaseUrl] = useState(config?.base_url ?? "");
  const [headersText, setHeadersText] = useState(headersToText(config?.headers));
  const [authType, setAuthType] = useState<"none" | "bearer" | "basic">(config?.auth?.type ?? "none");
  const [credential, setCredential] = useState<CredentialValue>(
    defaultCredentialValue(
      config?.auth?.token_env ?? config?.auth?.password_env,
      config?.auth?.token_secret ?? config?.auth?.password_secret
    )
  );
  const [username, setUsername] = useState(config?.auth?.username ?? "");
  const [orgId, setOrgId] = useState(connection?.org_id ?? defaultOrgId);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const ref = useDialogRef(open);

  function changeTitle(value: string) {
    setTitle(value);
    if (!connection && !nameEdited) setName(slugify(value));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    const body = {
      description: description.trim() || null,
      config: {
        base_url: baseUrl.trim(),
        headers: parseHeaders(headersText),
        auth: authType === "none" ? null : credentialToAuth(authType, username, credential),
      },
    };
    try {
      const saved = connection
        ? await api.connections.update(connection.id, body)
        : await api.connections.create({ org_id: orgId, name, ...body });
      onSaved(saved, connection === null);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the connection");
    } finally {
      setPending(false);
    }
  }

  const usedBy = connection?.reports ?? [];

  return (
    <dialog ref={ref} className="modal conn-dialog conn-dialog-wide" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">{connection ? "Edit connection" : "New connection"}</h2>
      <p className="panel-subtitle">
        A base URL with the headers and authentication every call to it needs. Reports pick a connection and add only a path.
      </p>
      <form onSubmit={handleSubmit}>
        <div className="conn-dialog-grid">
          {/* Left: what the connection points at. Right: how it authenticates --
              its own column so the credential picker has real room, rather than
              being squeezed under five stacked fields (see .conn-dialog-grid). */}
          <div className="conn-dialog-fields">
            {connection ? (
              <label>
                <span>Name</span>
                <input type="text" className="mono-input" value={connection.name} readOnly aria-readonly="true" />
                <span className="field-hint conn-name-hint">Fixed — reports refer to the connection by this name.</span>
              </label>
            ) : (
              <>
                <label>
                  <span className="field-label-row">
                    <span>Title</span>
                    <span className={`char-counter${title.length >= TITLE_MAX ? " char-counter-limit" : ""}`}>
                      {title.length}/{TITLE_MAX}
                    </span>
                  </span>
                  <input type="text" required maxLength={TITLE_MAX} placeholder="e.g. ERP API" value={title} onChange={(e) => changeTitle(e.target.value)} />
                </label>
                <label>
                  <span className="field-label-row">
                    <span>Name (used in reports)</span>
                    <span className={`char-counter${name.length >= NAME_MAX ? " char-counter-limit" : ""}`}>
                      {name.length}/{NAME_MAX}
                    </span>
                  </span>
                  <input
                    type="text"
                    className="mono-input"
                    required
                    minLength={2}
                    maxLength={NAME_MAX}
                    pattern="[a-z0-9]+([\-_][a-z0-9]+)*"
                    title="Lowercase letters and digits, with single hyphens or underscores between them"
                    placeholder="erp-api"
                    value={name}
                    onChange={(e) => {
                      setNameEdited(true);
                      setName(e.target.value);
                    }}
                  />
                </label>
              </>
            )}
            <label>
              <span className="field-label-row">
                <span>Description</span>
                <span className={`char-counter${description.length >= DESCRIPTION_MAX ? " char-counter-limit" : ""}`}>
                  {description.length}/{DESCRIPTION_MAX}
                </span>
              </span>
              <textarea
                rows={3}
                maxLength={DESCRIPTION_MAX}
                placeholder="What it is, and who owns it"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label>
              <span className="field-label-row">
                <span>Base URL</span>
                <span className={`char-counter${baseUrl.length >= BASE_URL_MAX ? " char-counter-limit" : ""}`}>
                  {baseUrl.length}/{BASE_URL_MAX}
                </span>
              </span>
              <input
                type="text"
                className="mono-input"
                required
                maxLength={BASE_URL_MAX}
                placeholder="https://erp.example.com/api"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </label>
            <p className="field-hint">Scheme, host and — if every call shares one — a path prefix. No query string; each report adds its own path.</p>

            <label>
              <span>Organization</span>
              {connection ? (
                // Fixed once created, same as the name -- shown so it's never ambiguous which
                // organization's data this connection can be picked for.
                <input
                  type="text"
                  value={organizations.find((o) => o.id === connection.org_id)?.name ?? connection.org_id}
                  readOnly
                  aria-readonly="true"
                />
              ) : organizations.length > 1 ? (
                <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  {organizations.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              ) : (
                // Only one organization exists (or this account can only see its own) -- nothing
                // to choose, but still shown so it's clear where this connection is being created.
                <input type="text" value={organizations[0]?.name ?? orgId} readOnly aria-readonly="true" />
              )}
            </label>

            <label>
              <span>Headers — one “Name: value” per line</span>
              <textarea
                className="mono-input"
                rows={3}
                placeholder="X-Client-Id: aksor-khmer-bi"
                value={headersText}
                onChange={(e) => setHeadersText(e.target.value)}
              />
            </label>
          </div>

          <div className="conn-dialog-auth">
            <span className="field-label">Authentication</span>
            <label>
              <span>Type</span>
              <select value={authType} onChange={(e) => setAuthType(e.target.value as typeof authType)}>
                <option value="none">None</option>
                <option value="bearer">Bearer token</option>
                <option value="basic">Basic (username + password)</option>
              </select>
            </label>
            {authType === "basic" && (
              <label>
                <span>Username</span>
                <input type="text" required value={username} onChange={(e) => setUsername(e.target.value)} />
              </label>
            )}
            {authType !== "none" ? (
              <CredentialPicker
                label={authType === "bearer" ? "Token" : "Password"}
                value={credential}
                onChange={setCredential}
                canManageSecrets={has(auth, "secret:manage")}
                orgId={orgId}
              />
            ) : (
              <p className="field-hint">Every call to this base URL goes out unauthenticated.</p>
            )}
          </div>
        </div>

        {connection && (
          <div className="conn-used-by">
            <span className="field-label">Used by</span>
            {usedBy.length === 0 ? (
              <p className="muted">No report uses this connection yet.</p>
            ) : (
              <>
                <ul>
                  {usedBy.map((r) => (
                    <li key={r.report_id}>
                      <a href={`#/reports/${encodeURIComponent(r.code ?? r.report_id)}/data-source`}>{r.name}</a>
                    </li>
                  ))}
                </ul>
                <p className="field-hint">Changes here apply to {usedBy.length === 1 ? "it" : "all of them"} on their next run.</p>
              </>
            )}
          </div>
        )}

        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            {connection ? "Save changes" : "Create connection"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
