import { useEffect, useId, useState, type KeyboardEvent } from "react";
import { api, ApiError } from "../api";
import { PASSWORD_HINT, passwordProblem } from "../passwords";
import type { SecretSummary } from "../types";

export type CredentialSource = "secret" | "env";

/** The one piece of a DataSourceAuth this component edits: either half of a
 * bearer token or a basic password. `env`/`secret` hold whichever the source
 * currently is (only one is ever non-empty), same shape the API stores. */
export interface CredentialValue {
  source: CredentialSource;
  env: string;
  secret: string;
}

export function defaultCredentialValue(env?: string | null, secret?: string | null): CredentialValue {
  return { source: env ? "env" : "secret", env: env ?? "", secret: secret ?? "" };
}

/** Where a bearer token's or a basic password's value comes from -- a named
 * Secret (Admin > Secrets: created, rotated and revoked in the portal) or an
 * environment variable on the API server -- shared by the connection form
 * and a report's own data source/choice list form, since both credentials
 * are the exact same shape (api/app/models/reports.py's DataSourceAuth).
 *
 * Fetches the secret list itself (once per mount) rather than making every
 * caller thread it through -- this is the only place that needs it, and a
 * dialog mounts fresh per open already (see ConnectionDialog's own key). */
export default function CredentialPicker({
  label,
  value,
  onChange,
  canManageSecrets,
  orgId,
}: {
  /** "Token" or "Password" -- capitalized, used in field labels and hints. */
  label: string;
  value: CredentialValue;
  onChange: (next: CredentialValue) => void;
  /** Whether the signed-in user holds secret:manage -- gates "+ New credential". Someone without it may still pick an existing one. */
  canManageSecrets: boolean;
  orgId: string;
}) {
  const [secretList, setSecretList] = useState<SecretSummary[] | null>(null);
  const [creating, setCreating] = useState(false);

  function loadSecrets() {
    api.secrets.list(orgId).then(setSecretList).catch(() => setSecretList([]));
  }

  useEffect(loadSecrets, [orgId]);

  const envLabel = label === "Token" ? "Token environment variable" : "Password environment variable";
  const envPlaceholder = label === "Token" ? "ERP_TOKEN" : "ERP_PASSWORD";

  return (
    <>
      <div className="conn-auth-row">
        <label>
          <span>Where the {label.toLowerCase()} is kept</span>
          <select
            value={value.source}
            onChange={(e) => onChange({ ...value, source: e.target.value as CredentialSource })}
          >
            <option value="secret">A saved credential (Admin → Secrets)</option>
            <option value="env">Environment variable on the server</option>
          </select>
        </label>
        {value.source === "secret" ? (
          <label>
            <span>Credential</span>
            <select
              value={secretList?.some((s) => s.name === value.secret) ? value.secret : ""}
              onChange={(e) => {
                if (e.target.value === "__new__") setCreating(true);
                else onChange({ ...value, secret: e.target.value });
              }}
            >
              <option value="" disabled>
                {secretList === null ? "Loading…" : "Choose one…"}
              </option>
              {/* The current value stays selectable even if it's since been revoked, or isn't in the
                  list this org can see (e.g. a superuser editing another org's connection) -- picking
                  it again is a no-op, but the field shouldn't silently blank out what was saved. */}
              {value.secret && !secretList?.some((s) => s.name === value.secret) && (
                <option value={value.secret}>{value.secret} (not in this list)</option>
              )}
              {secretList?.map((s) => (
                <option key={s.id} value={s.name}>
                  {s.name}
                  {!s.is_active ? " (revoked)" : ""}
                </option>
              ))}
              {canManageSecrets && <option value="__new__">+ New credential…</option>}
            </select>
          </label>
        ) : (
          <label>
            <span>{envLabel}</span>
            <input
              type="text"
              className="mono-input"
              required
              placeholder={envPlaceholder}
              value={value.env}
              onChange={(e) => onChange({ ...value, env: e.target.value })}
            />
          </label>
        )}
      </div>
      {value.source === "secret" ? (
        !canManageSecrets && !secretList?.length ? (
          <p className="field-hint">No credentials exist yet — ask someone who manages secrets to create one.</p>
        ) : (
          <p className="field-hint">
            Rotating or revoking it (Admin → Secrets) applies to every report or connection that names it, on their
            next run — no restart.
          </p>
        )
      ) : (
        <p className="field-hint">
          Read from an environment variable on the API server — changing it means editing the server's environment
          and restarting.
        </p>
      )}

      {creating && (
        <NewSecretInline
          orgId={orgId}
          onCreated={(secret) => {
            setCreating(false);
            onChange({ ...value, secret: secret.name });
            loadSecrets();
          }}
          onCancel={() => setCreating(false)}
        />
      )}
    </>
  );
}

/** The "+ New credential" flow, inline rather than a separate dialog-over-a-dialog:
 * a name and a value, created immediately (POST /secrets) so the picker above can
 * select it right away. */
function NewSecretInline({
  orgId,
  onCreated,
  onCancel,
}: {
  orgId: string;
  onCreated: (secret: { name: string }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [showValue, setShowValue] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const valueId = useId();

  async function create() {
    setError(null);
    const problem = passwordProblem(value);
    if (problem) return setError(problem);
    setPending(true);
    try {
      const secret = await api.secrets.create({ org_id: orgId, name, value });
      onCreated(secret);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the credential");
    } finally {
      setPending(false);
    }
  }

  // A <div>, not a <form>: this always sits inside the caller's own <form>
  // (ConnectionDialog's or RequestFields'), and nested forms are invalid --
  // Enter still submits, via onKeyDown below, same as a real form would.
  function submitOnEnter(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      create();
    }
  }

  return (
    <div className="conn-new-secret" onKeyDown={submitOnEnter}>
      <div className="conn-auth-row">
        <label>
          <span>Credential name</span>
          <input
            type="text"
            className="mono-input"
            required
            minLength={2}
            maxLength={64}
            pattern="[a-z0-9]+([\-_][a-z0-9]+)*"
            title="Lowercase letters and digits, with single hyphens or underscores between them"
            placeholder="erp-api-token"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <div className="field-block">
          <label className="field-label" htmlFor={valueId}>
            Value
          </label>
          <div className="password-field">
            <input
              id={valueId}
              type={showValue ? "text" : "password"}
              className="mono-input"
              required
              autoComplete="new-password"
              spellCheck={false}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <button type="button" className="link-btn" onClick={() => setShowValue((v) => !v)}>
              {showValue ? "Hide" : "Show"}
            </button>
          </div>
        </div>
      </div>
      <p className="field-hint">{PASSWORD_HINT}</p>
      {error && <p className="alert alert-error">{error}</p>}
      <div className="conn-new-secret-actions">
        <button type="button" className="btn btn-sm" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn btn-sm btn-primary" onClick={create} disabled={pending}>
          {pending && <span className="spinner" />}
          Create credential
        </button>
      </div>
    </div>
  );
}
