import { useState, type FormEvent } from "react";
import { CheckCircle2, Lock, Send, XCircle } from "lucide-react";
import { api, ApiError } from "../../api";
import CredentialPicker, { defaultCredentialValue, type CredentialValue } from "../../components/CredentialPicker";
import ModalClose from "../../components/ModalClose";
import { useDialogRef } from "../../hooks";
import type { AuthInfo, Connection, ConnectionTestResult, Organization, SmtpConnectionConfig } from "../../types";
import { has } from "../sections";
import { slugify } from "./ConnectionDialog";

const NAME_MAX = 64;
const TITLE_MAX = 120;
const DESCRIPTION_MAX = 500;

type Security = SmtpConnectionConfig["security"];

/** Presets fill the host, port and security; each says what that provider needs that people trip over. */
const PROVIDERS: { id: string; label: string; host: string; port: number; security: Security; tip: string }[] = [
  {
    id: "google",
    label: "Google Workspace",
    host: "smtp.gmail.com",
    port: 587,
    security: "starttls",
    tip: "Google needs an app password (Google Account → Security → App passwords), not the account's own password.",
  },
  {
    id: "microsoft",
    label: "Microsoft 365",
    host: "smtp.office365.com",
    port: 587,
    security: "starttls",
    tip: "Turn on SMTP sign-in for this mailbox first (Microsoft 365 admin → the user → Mail → Authenticated SMTP).",
  },
  { id: "other", label: "Other SMTP", host: "", port: 587, security: "starttls", tip: "Ask whoever runs your mail server for its host, port and security mode." },
];

const SECURITY_LABEL: Record<Security, string> = {
  starttls: "STARTTLS (usually port 587)",
  tls: "TLS (usually port 465)",
  none: "None — an internal relay, no sign-in",
};

/** Create or edit a mail server (connection kind "smtp") that report jobs email their files through. As with a
 * database, the password is never typed here: it's a saved credential (Admin > Secrets) picked or created through
 * CredentialPicker. "Send a test email" tries the settings on the form, saved or not. Mounted fresh per open. */
export default function MailServerDialog({
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
  const saved = connection?.config as SmtpConnectionConfig | undefined;
  const initialProvider = PROVIDERS.find((p) => p.host && p.host === saved?.host)?.id ?? (saved ? "other" : "google");

  const [provider, setProvider] = useState(initialProvider);
  const [title, setTitle] = useState(connection?.name ?? "");
  const [name, setName] = useState(connection?.name ?? "");
  const [nameEdited, setNameEdited] = useState(false);
  const [description, setDescription] = useState(connection?.description ?? "");
  const [orgId, setOrgId] = useState(connection?.org_id ?? defaultOrgId);
  const [host, setHost] = useState(saved?.host ?? "smtp.gmail.com");
  const [port, setPort] = useState(String(saved?.port ?? 587));
  const [security, setSecurity] = useState<Security>(saved?.security ?? "starttls");
  const [fromAddress, setFromAddress] = useState(saved?.from_address ?? "");
  const [fromName, setFromName] = useState(saved?.from_name ?? "");
  const [signIn, setSignIn] = useState(saved ? saved.auth !== null : true);
  const [username, setUsername] = useState(saved?.auth?.username ?? "");
  const [credential, setCredential] = useState<CredentialValue>(defaultCredentialValue(saved?.auth?.password_env, saved?.auth?.password_secret));
  const [testTo, setTestTo] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const ref = useDialogRef(open);

  const tip = PROVIDERS.find((p) => p.id === provider)?.tip;

  function chooseProvider(id: string) {
    const next = PROVIDERS.find((p) => p.id === id)!;
    setProvider(id);
    if (next.host) setHost(next.host);
    setPort(String(next.port));
    setSecurity(next.security);
    setSignIn(true);
    setTestResult(null);
  }

  function buildConfig(): SmtpConnectionConfig | string {
    const portNumber = Number(port);
    if (!host.trim()) return "Enter the mail server's host";
    if (!Number.isInteger(portNumber) || portNumber < 1 || portNumber > 65535) return "The port must be a number between 1 and 65535";
    if (!fromAddress.trim()) return "Enter the address reports are sent from";
    const useSignIn = signIn && security !== "none";
    if (useSignIn && !username.trim()) return "Enter the username to sign in with";
    if (useSignIn && credential.source === "secret" && !credential.secret) return "Choose the saved credential that holds the password";
    if (useSignIn && credential.source === "env" && !credential.env.trim()) return "Enter the environment variable that holds the password";
    return {
      host: host.trim(),
      port: portNumber,
      security,
      from_address: fromAddress.trim(),
      from_name: fromName.trim() || null,
      auth: !useSignIn
        ? null
        : credential.source === "env"
          ? { type: "basic", username: username.trim(), password_env: credential.env.trim() }
          : { type: "basic", username: username.trim(), password_secret: credential.secret },
    };
  }

  async function sendTest() {
    const config = buildConfig();
    if (typeof config === "string") return setTestResult({ ok: false, message: config, elapsed_ms: null });
    if (!testTo.trim()) return setTestResult({ ok: false, message: "Enter where to send the test email", elapsed_ms: null });
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await api.connections.testMail(config, testTo.trim(), orgId));
    } catch (err) {
      setTestResult({ ok: false, message: err instanceof ApiError ? err.message : "Couldn't send the test", elapsed_ms: null });
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
        : await api.connections.create({ org_id: orgId, name, kind: "smtp", description: description_, config });
      onSaved(result, connection === null);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the mail server");
    } finally {
      setPending(false);
    }
  }

  const changed = (apply: () => void) => {
    apply();
    setTestResult(null);
  };

  return (
    <dialog ref={ref} className="modal conn-dialog conn-dialog-wide jdbc-dialog" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">{connection ? "Edit mail server" : "New mail server"}</h2>
      <p className="panel-subtitle">Report jobs send their files through it. The password is a saved credential, so it never shows again.</p>
      <form onSubmit={handleSubmit}>
        <section className="jdbc-section">
          <h3 className="jdbc-heading">Provider</h3>
          <div className="segmented" role="radiogroup" aria-label="Provider">
            {PROVIDERS.map((p) => (
              <button
                key={p.id}
                type="button"
                role="radio"
                aria-checked={provider === p.id}
                className={provider === p.id ? "segmented-btn active" : "segmented-btn"}
                onClick={() => chooseProvider(p.id)}
              >
                {p.label}
              </button>
            ))}
          </div>
          {tip && <p className="field-hint mt-2">{tip}</p>}
        </section>

        <section className="jdbc-section">
          <h3 className="jdbc-heading">Mail server</h3>
          <div className="jdbc-grid">
            {connection ? (
              <label className="jdbc-span-2">
                <span>Name</span>
                <input type="text" className="mono-input" value={connection.name} readOnly aria-readonly="true" />
                <span className="field-hint conn-name-hint">Fixed — jobs refer to the mail server by this name.</span>
              </label>
            ) : (
              <>
                <label>
                  <span className="field-label-row">
                    <span>Title</span>
                    <span className={title.length >= TITLE_MAX ? "char-counter char-counter-limit" : "char-counter"}>
                      {title.length}/{TITLE_MAX}
                    </span>
                  </span>
                  <input
                    type="text"
                    required
                    maxLength={TITLE_MAX}
                    placeholder="e.g. Company mail"
                    value={title}
                    onChange={(e) => {
                      setTitle(e.target.value);
                      if (!nameEdited) setName(slugify(e.target.value));
                    }}
                  />
                </label>
                <label>
                  <span className="field-label-row">
                    <span>Name (used in jobs)</span>
                    <span className={name.length >= NAME_MAX ? "char-counter char-counter-limit" : "char-counter"}>
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
                    placeholder="company-mail"
                    value={name}
                    onChange={(e) => {
                      setNameEdited(true);
                      setName(e.target.value);
                    }}
                  />
                </label>
              </>
            )}
            {!connection && organizations.length > 1 && (
              <label className="jdbc-span-2">
                <span>Organization</span>
                <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  {organizations.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              <span>Host</span>
              <input type="text" className="mono-input" required spellCheck={false} value={host} onChange={(e) => changed(() => setHost(e.target.value))} placeholder="smtp.example.com" />
            </label>
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-3">
              <label>
                <span>Port</span>
                <input type="number" required min={1} max={65535} value={port} onChange={(e) => changed(() => setPort(e.target.value))} />
              </label>
              <label>
                <span>Security</span>
                <select value={security} onChange={(e) => changed(() => setSecurity(e.target.value as Security))}>
                  {(Object.keys(SECURITY_LABEL) as Security[]).map((s) => (
                    <option key={s} value={s}>
                      {SECURITY_LABEL[s]}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              <span>From address</span>
              <input type="email" required value={fromAddress} onChange={(e) => changed(() => setFromAddress(e.target.value))} placeholder="reports@example.com" />
            </label>
            <label>
              <span>
                From name <span className="muted">(optional)</span>
              </span>
              <input type="text" maxLength={100} value={fromName} onChange={(e) => setFromName(e.target.value)} placeholder="Aksor Khmer BI · Reports" />
            </label>
            <label className="jdbc-span-2">
              <span className="field-label-row">
                <span>
                  Description <span className="muted">(optional)</span>
                </span>
                <span className={description.length >= DESCRIPTION_MAX ? "char-counter char-counter-limit" : "char-counter"}>
                  {description.length}/{DESCRIPTION_MAX}
                </span>
              </span>
              <input type="text" maxLength={DESCRIPTION_MAX} value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
          </div>
        </section>

        {security !== "none" && (
          <section className="jdbc-section">
            <h3 className="jdbc-heading">Sign-in</h3>
            <label className="checkbox-label">
              <input type="checkbox" checked={signIn} onChange={(e) => changed(() => setSignIn(e.target.checked))} />
              The mail server needs a username and password
            </label>
            {signIn && (
              <div className="jdbc-login">
                <div className="jdbc-login-fields">
                  <label>
                    <span>Username</span>
                    <input type="text" required autoComplete="off" spellCheck={false} value={username} onChange={(e) => changed(() => setUsername(e.target.value))} placeholder="reports@example.com" />
                  </label>
                  <CredentialPicker
                    label="Password"
                    value={credential}
                    onChange={(next) => changed(() => setCredential(next))}
                    canManageSecrets={has(auth, "secret:manage")}
                    orgId={orgId}
                  />
                </div>
                <aside className="jdbc-secret-note" aria-label="How the password is stored">
                  <Lock size={16} aria-hidden="true" />
                  <div>
                    <strong>The password is never kept on this form.</strong>
                    <p>
                      It lives in <a href="#/admin/secrets">Secrets</a>, encrypted, and is decrypted only while a job sends. For Google and
                      Microsoft, use an app password made for this, so it can be revoked on its own.
                    </p>
                  </div>
                </aside>
              </div>
            )}
          </section>
        )}

        <div className="jdbc-test flex-wrap">
          <input
            type="email"
            className="max-w-[16rem]"
            aria-label="Send the test email to"
            placeholder="Send the test to…"
            value={testTo}
            onChange={(e) => setTestTo(e.target.value)}
          />
          <button type="button" className="btn" onClick={sendTest} disabled={testing}>
            {testing ? <span className="spinner" /> : <Send size={14} aria-hidden="true" />}
            Send a test email
          </button>
          {testResult && (
            <span className={`jdbc-test-result ${testResult.ok ? "ok" : "bad"}`} role="status">
              {testResult.ok ? <CheckCircle2 size={15} aria-hidden="true" /> : <XCircle size={15} aria-hidden="true" />}
              {testResult.message}
            </span>
          )}
        </div>

        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            {connection ? "Save changes" : "Create mail server"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
