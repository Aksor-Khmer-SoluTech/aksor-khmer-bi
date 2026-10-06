import { useEffect, useMemo, useState, type FormEvent } from "react";
import { CheckCircle2, ExternalLink, Lock, PlugZap, XCircle } from "lucide-react";
import { api, ApiError } from "../../api";
import CredentialPicker, { defaultCredentialValue, type CredentialValue } from "../../components/CredentialPicker";
import DbEngineIcon from "../../components/DbEngineIcon";
import DbEnginePicker from "../../components/DbEnginePicker";
import { useDialogRef } from "../../hooks";
import { buildJdbcUrl, parseJdbcUrl } from "../../jdbcUrl";
import type {
  AuthInfo,
  Connection,
  ConnectionTestResult,
  JdbcConnectionConfig,
  JdbcDriver,
  JdbcEngine,
  Organization,
  SslMode,
} from "../../types";
import { has } from "../sections";
import { slugify } from "./ConnectionDialog";

import ModalClose from "../../components/ModalClose";
const TITLE_MAX = 120;
const NAME_MAX = 64;
const DESCRIPTION_MAX = 500;

const SSL_LABEL: Record<SslMode, string> = {
  disable: "Disabled — no encryption",
  require: "Required — encrypted, certificate not checked",
  "verify-ca": "Verify CA — encrypted, certificate authority checked",
  "verify-full": "Verify full — encrypted, authority and host name checked",
};

/** Create or edit a database connection (kind "jdbc"): which engine, where, how
 * securely, on which driver, and as whom. The password is never typed here -- it
 * is a saved credential (Admin > Secrets: encrypted, write-only), picked or
 * created through CredentialPicker. Mounted fresh per open, like the REST dialog. */
export default function JdbcConnectionDialog({
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
  connection: Connection | null;
  organizations: Organization[];
  defaultOrgId: string;
  auth: AuthInfo;
  onSaved: (saved: Connection, created: boolean) => void;
}) {
  const saved = connection?.config as JdbcConnectionConfig | undefined;
  const [engines, setEngines] = useState<JdbcEngine[] | null>(null);
  const [drivers, setDrivers] = useState<JdbcDriver[] | null>(null);

  const [title, setTitle] = useState(connection?.name ?? "");
  const [name, setName] = useState(connection?.name ?? "");
  const [nameEdited, setNameEdited] = useState(false);
  const [description, setDescription] = useState(connection?.description ?? "");
  const [orgId, setOrgId] = useState(connection?.org_id ?? defaultOrgId);

  const [engineId, setEngineId] = useState(saved?.engine ?? "postgresql");
  const [host, setHost] = useState(saved?.host ?? "");
  const [port, setPort] = useState(String(saved?.port ?? 5432));
  const [database, setDatabase] = useState(saved?.database ?? "");
  const [serviceType, setServiceType] = useState<"service_name" | "sid">(saved?.service_type ?? "service_name");
  const [sslMode, setSslMode] = useState<SslMode>(saved?.ssl_mode ?? "disable");
  const [driverId, setDriverId] = useState(saved?.driver_id ?? "");
  const [customUrl, setCustomUrl] = useState<string | null>(saved?.jdbc_url ?? null);
  // What's being typed in the URL box right now -- kept apart from the derived URL so a half-typed
  // one isn't rewritten under the cursor.
  const [urlText, setUrlText] = useState<string | null>(null);
  const [username, setUsername] = useState(saved?.auth.username ?? "");
  const [credential, setCredential] = useState<CredentialValue>(
    defaultCredentialValue(saved?.auth.password_env, saved?.auth.password_secret)
  );

  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  const ref = useDialogRef(open);

  useEffect(() => {
    api.jdbc.engines().then(setEngines).catch(() => setError("Couldn't load the list of database engines"));
  }, []);
  useEffect(() => {
    setDrivers(null);
    api.jdbc.drivers.list(orgId).then(setDrivers).catch(() => setDrivers([]));
  }, [orgId]);

  const engine = engines?.find((e) => e.id === engineId);
  const enginesDrivers = useMemo(() => (drivers ?? []).filter((d) => d.engine === engineId), [drivers, engineId]);
  const usesUploadedDriver = driverId !== "";
  const canUploadDrivers = has(auth, "driver:manage");

  const portNumber = Number(port);
  const fields = { engine: engineId, host, port: portNumber, database, serviceType, sslMode };
  const builtUrl = engine && host.trim() && Number.isInteger(portNumber) ? buildJdbcUrl(fields) : "";
  const shownUrl = urlText ?? (usesUploadedDriver ? customUrl : null) ?? builtUrl;

  /** Any edit to the fields regenerates the URL: a custom one only survives while it's the thing being edited. */
  function edit(apply: () => void) {
    apply();
    setCustomUrl(null);
    setTestResult(null);
  }

  function chooseEngine(next: JdbcEngine) {
    edit(() => {
      const previous = engines?.find((e) => e.id === engineId);
      setEngineId(next.id);
      if (!port || Number(port) === previous?.default_port) setPort(String(next.default_port));
      // A driver is for one engine.
      if (drivers?.find((d) => d.id === driverId)?.engine !== next.id) setDriverId("");
      if (next.id !== "oracle") setServiceType("service_name");
    });
  }

  function changeUrl(value: string) {
    setUrlText(value);
    setTestResult(null);
    const parsed = parseJdbcUrl(value);
    if (!parsed) return;
    if (parsed.engine !== engineId) {
      const next = engines?.find((e) => e.id === parsed.engine);
      if (!next) return;
      setEngineId(next.id);
      if (drivers?.find((d) => d.id === driverId)?.engine !== next.id) setDriverId("");
    }
    setHost(parsed.host);
    setPort(String(parsed.port));
    setDatabase(parsed.database);
    if (parsed.serviceType) setServiceType(parsed.serviceType);
    // Options beyond host/port/database only mean something to an uploaded driver; the built-in ones read just those.
    setCustomUrl(usesUploadedDriver ? value : null);
  }

  function changeTitle(value: string) {
    setTitle(value);
    if (!connection && !nameEdited) setName(slugify(value));
  }

  function buildConfig(): JdbcConnectionConfig | string {
    if (!engine) return "Choose a database engine";
    if (!host.trim()) return "Enter the database host";
    if (!Number.isInteger(portNumber) || portNumber < 1 || portNumber > 65535) return "The port must be a number between 1 and 65535";
    if (!username.trim()) return "Enter the database username";
    if (credential.source === "secret" && !credential.secret) return "Choose the saved credential that holds the password";
    if (credential.source === "env" && !credential.env.trim()) return "Enter the environment variable that holds the password";
    if (!engine.built_in && !usesUploadedDriver) return `${engine.label} needs its JDBC driver — choose an uploaded one`;
    return {
      engine: engineId,
      host: host.trim(),
      port: portNumber,
      database: database.trim(),
      service_type: engineId === "oracle" ? serviceType : null,
      ssl_mode: sslMode,
      driver_id: usesUploadedDriver ? driverId : null,
      jdbc_url: usesUploadedDriver ? customUrl : null,
      auth:
        credential.source === "env"
          ? { type: "basic", username: username.trim(), password_env: credential.env.trim() }
          : { type: "basic", username: username.trim(), password_secret: credential.secret },
    };
  }

  async function runTest() {
    const config = buildConfig();
    if (typeof config === "string") return setTestResult({ ok: false, message: config, elapsed_ms: null });
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await api.connections.test(config, orgId));
    } catch (err) {
      setTestResult({ ok: false, message: err instanceof ApiError ? err.message : "Couldn't run the test", elapsed_ms: null });
    } finally {
      setTesting(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const config = buildConfig();
    if (typeof config === "string") return setError(config);
    setPending(true);
    setError(null);
    const description_ = description.trim() || null;
    try {
      const result = connection
        ? await api.connections.update(connection.id, { description: description_, config })
        : await api.connections.create({ org_id: orgId, name, kind: "jdbc", description: description_, config });
      onSaved(result, connection === null);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the connection");
    } finally {
      setPending(false);
    }
  }

  const usedBy = connection?.reports ?? [];

  const orgField = (
    <label>
      <span>Organization</span>
      {connection ? (
        <input type="text" value={organizations.find((o) => o.id === connection.org_id)?.name ?? connection.org_id} readOnly aria-readonly="true" />
      ) : organizations.length > 1 ? (
        <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
          {organizations.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      ) : (
        <input type="text" value={organizations[0]?.name ?? orgId} readOnly aria-readonly="true" />
      )}
    </label>
  );

  return (
    <dialog ref={ref} className="modal conn-dialog conn-dialog-wide jdbc-dialog" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">{connection ? "Edit database connection" : "New database connection"}</h2>
      <p className="panel-subtitle">
        A database a report can run a read-only query against. Reports pick the connection and write only the SQL.
      </p>
      <form onSubmit={handleSubmit}>
        <section className="jdbc-section">
          <h3 className="jdbc-heading">Engine</h3>
          {engines ? (
            <DbEnginePicker engines={engines} value={engineId} onChange={chooseEngine} />
          ) : (
            <p className="muted">Loading…</p>
          )}
        </section>

        <section className="jdbc-section">
          <h3 className="jdbc-heading">Connection</h3>
          <div className="jdbc-grid">
            {connection ? (
              <label className="jdbc-span-2">
                <span className="field-label-row">
                  <span>Name</span>
                  <span className="char-counter">
                    {connection.name.length}/{NAME_MAX}
                  </span>
                </span>
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
                  <input type="text" required maxLength={TITLE_MAX} placeholder="e.g. Sales warehouse" value={title} onChange={(e) => changeTitle(e.target.value)} />
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
                    placeholder="sales-warehouse"
                    value={name}
                    onChange={(e) => {
                      setNameEdited(true);
                      setName(e.target.value);
                    }}
                  />
                </label>
              </>
            )}
            <label className="jdbc-span-2">
              <span className="field-label-row">
                <span>Description</span>
                <span className={`char-counter${description.length >= DESCRIPTION_MAX ? " char-counter-limit" : ""}`}>
                  {description.length}/{DESCRIPTION_MAX}
                </span>
              </span>
              <textarea
                className="jdbc-description"
                rows={3}
                maxLength={DESCRIPTION_MAX}
                placeholder="What it is, and who owns it"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>

            <label>
              <span>Host</span>
              <input
                type="text"
                className="mono-input"
                required
                placeholder="db.example.com"
                value={host}
                onChange={(e) => edit(() => setHost(e.target.value))}
              />
            </label>
            <label>
              <span>Port</span>
              <input
                type="number"
                className="mono-input"
                required
                min={1}
                max={65535}
                value={port}
                onChange={(e) => edit(() => setPort(e.target.value))}
              />
            </label>
            <label>
              <span>{engine?.database_label ?? "Database"}</span>
              <input
                type="text"
                className="mono-input"
                placeholder={engineId === "oracle" ? "ORCLPDB1" : "sales"}
                value={database}
                onChange={(e) => edit(() => setDatabase(e.target.value))}
              />
            </label>
            {engineId === "oracle" ? (
              <label>
                <span>Identify the database by</span>
                <select value={serviceType} onChange={(e) => edit(() => setServiceType(e.target.value as "service_name" | "sid"))}>
                  <option value="service_name">Service name</option>
                  <option value="sid">SID</option>
                </select>
              </label>
            ) : (
              orgField
            )}

            {engineId === "oracle" && orgField}
          </div>
        </section>

        <section className="jdbc-section">
          <h3 className="jdbc-heading">
            <Lock size={14} aria-hidden="true" /> Secure connection
          </h3>
          <label>
            <span>Mode</span>
            <select value={sslMode} onChange={(e) => edit(() => setSslMode(e.target.value as SslMode))}>
              {(engine?.ssl_modes ?? (["disable", "require", "verify-ca", "verify-full"] as SslMode[])).map((m) => (
                <option key={m} value={m}>
                  {SSL_LABEL[m]}
                </option>
              ))}
            </select>
          </label>
          {engine && <p className="field-hint">{engine.ssl_note}</p>}
          {sslMode === "disable" && (
            <p className="field-hint jdbc-warn">Without encryption the login and every row cross the network in clear text. Use it only on a trusted network.</p>
          )}
        </section>

        <section className="jdbc-section">
          <h3 className="jdbc-heading">Driver</h3>
          <div className="jdbc-driver-row">
            <label>
              <span>JDBC driver</span>
              <select
                value={driverId}
                onChange={(e) => {
                  setDriverId(e.target.value);
                  setCustomUrl(null);
                  setTestResult(null);
                }}
              >
                {engine?.built_in && <option value="">Built in — nothing to upload</option>}
                {!engine?.built_in && <option value="">Choose an uploaded driver…</option>}
                {enginesDrivers.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} ({d.driver_class})
                  </option>
                ))}
              </select>
            </label>
            {engine && (
              <a className="btn jdbc-driver-link" href={engine.driver_url} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={13} aria-hidden="true" /> Get the {engine.label} driver
              </a>
            )}
          </div>
          {engine && !engine.built_in && enginesDrivers.length === 0 && drivers !== null && (
            <p className="field-hint jdbc-warn">
              {engine.label} has no built-in driver. Download the vendor's .jar from the link above, then{" "}
              {canUploadDrivers ? (
                <a href="#/admin/jdbc-drivers">upload it under Admin → JDBC drivers</a>
              ) : (
                "ask someone with the driver:manage permission to upload it"
              )}
              .
            </p>
          )}
          {usesUploadedDriver && (
            <p className="field-hint">An uploaded driver runs in the isolated driver service, never inside the API itself.</p>
          )}
        </section>

        <section className="jdbc-section">
          <h3 className="jdbc-heading">JDBC URL</h3>
          <input
            type="text"
            className="mono-input jdbc-url"
            spellCheck={false}
            aria-label="JDBC URL"
            placeholder={engine ? `jdbc:${engine.id === "oracle" ? "oracle:thin:@//" : `${engine.id}://`}host:${engine.default_port}/database` : "jdbc:…"}
            value={shownUrl}
            onChange={(e) => changeUrl(e.target.value)}
            onBlur={() => setUrlText(null)}
          />
          <p className="field-hint">
            Built from the fields above, and the other way round: paste a URL and they fill in.{" "}
            {usesUploadedDriver
              ? "With an uploaded driver, edits you make here — extra options included — are used exactly as written."
              : "The built-in driver uses only the host, port and database from it. Never put a username or password in the URL."}
          </p>
        </section>

        <section className="jdbc-section">
          <h3 className="jdbc-heading">Login</h3>
          <div className="jdbc-login">
            <div className="jdbc-login-fields">
              <label>
                <span>Username</span>
                <input
                  type="text"
                  required
                  autoComplete="off"
                  spellCheck={false}
                  value={username}
                  onChange={(e) => {
                    setUsername(e.target.value);
                    setTestResult(null);
                  }}
                />
              </label>
              <CredentialPicker
                label="Password"
                value={credential}
                onChange={(next) => {
                  setCredential(next);
                  setTestResult(null);
                }}
                canManageSecrets={has(auth, "secret:manage")}
                orgId={orgId}
              />
            </div>
            <aside className="jdbc-secret-note" aria-label="How the password is stored">
              <Lock size={16} aria-hidden="true" />
              <div>
                <strong>The password is never kept on this form.</strong>
                <p>
                  It lives in the <a href="#/admin/secrets">Secrets</a> table, encrypted (AES-128 + HMAC) with a key held outside the
                  database. Nothing can read it back — not this page, an API, the audit log or a backup — it is decrypted only for the
                  moment a query runs. Replace it by rotating the credential.
                </p>
                <p>Use a database account with <strong>read-only</strong> access: it is the real limit on what a report's SQL can do.</p>
              </div>
            </aside>
          </div>
        </section>

        <div className="jdbc-test">
          <button type="button" className="btn" onClick={runTest} disabled={testing}>
            {testing ? <span className="spinner" /> : <PlugZap size={14} aria-hidden="true" />}
            Test connection
          </button>
          {testResult && (
            <span className={`jdbc-test-result ${testResult.ok ? "ok" : "bad"}`} role="status">
              {testResult.ok ? <CheckCircle2 size={15} aria-hidden="true" /> : <XCircle size={15} aria-hidden="true" />}
              {testResult.ok ? `Connected${testResult.elapsed_ms !== null ? ` in ${testResult.elapsed_ms} ms` : ""}` : testResult.message}
            </span>
          )}
          {engine && (
            <span className="jdbc-test-engine muted">
              <DbEngineIcon engine={engine.id} size={18} /> {engine.label}
            </span>
          )}
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
          <button type="submit" className="btn btn-primary" disabled={pending || !engine}>
            {pending && <span className="spinner" />}
            {connection ? "Save changes" : "Create connection"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
