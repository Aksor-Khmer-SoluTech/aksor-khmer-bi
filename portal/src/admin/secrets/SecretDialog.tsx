import { useId, useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import { PASSWORD_HINT, passwordProblem } from "../../passwords";
import { useDialogRef } from "../../hooks";
import type { Organization, Secret } from "../../types";

import ModalClose from "../../components/ModalClose";
/** Create a credential, or manage one (mounted with a fresh `key` per open,
 * like the other admin dialogs). Rotating (a new value, same name) is folded
 * in here rather than a separate dialog -- it's the one field on an existing
 * secret that isn't just description/status, and doing it beside "Used by"
 * makes the blast radius of a rotation visible at the moment you'd want it. */
export default function SecretDialog({
  open,
  onClose,
  secret,
  organizations,
  defaultOrgId,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  /** null = creating a new secret */
  secret: Secret | null;
  organizations: Organization[];
  defaultOrgId: string;
  onSaved: (saved: Secret, created: boolean) => void;
}) {
  const [name, setName] = useState(secret?.name ?? "");
  const [description, setDescription] = useState(secret?.description ?? "");
  const [orgId, setOrgId] = useState(secret?.org_id ?? defaultOrgId);
  const [value, setValue] = useState("");
  const [showValue, setShowValue] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [isActive, setIsActive] = useState(secret?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const valueId = useId();

  const ref = useDialogRef(open);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!secret || rotating) {
      const problem = passwordProblem(value);
      if (problem) return setError(problem);
    }
    setPending(true);
    try {
      let saved: Secret;
      if (!secret) {
        saved = await api.secrets.create({ org_id: orgId, name, description: description.trim() || null, value });
      } else {
        saved = secret;
        if (rotating) saved = await api.secrets.rotate(secret.id, value);
        if (description !== (secret.description ?? "") || isActive !== secret.is_active) {
          saved = await api.secrets.update(secret.id, { description: description.trim() || null, is_active: isActive });
        }
      }
      onSaved(saved, secret === null);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the credential");
    } finally {
      setPending(false);
    }
  }

  const usedBy = secret?.used_by ?? [];

  return (
    <dialog ref={ref} className="modal conn-dialog" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">{secret ? "Manage credential" : "New credential"}</h2>
      <p className="panel-subtitle">
        {secret
          ? "Rotating replaces the value everything below keeps using — no change needed to whatever refers to it."
          : "A token or password a connection or a report's data source can refer to by name, instead of an environment variable."}
      </p>
      <form onSubmit={handleSubmit}>
        {secret ? (
          <label>
            <span>Name</span>
            <input type="text" className="mono-input" value={secret.name} readOnly aria-readonly="true" />
            <span className="field-hint conn-name-hint">Fixed — whatever refers to it does so by this name.</span>
          </label>
        ) : (
          <label>
            <span>Name</span>
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
        )}
        <label>
          <span>Description</span>
          <input
            type="text"
            maxLength={500}
            placeholder="What it's for, and who owns it"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>

        <label>
          <span>Organization</span>
          {secret ? (
            // Fixed once created, same as the name -- shown so it's never ambiguous which
            // organization's reports and connections can refer to this credential.
            <input
              type="text"
              value={organizations.find((o) => o.id === secret.org_id)?.name ?? secret.org_id}
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
            // to choose, but still shown so it's clear where this credential is being created.
            <input type="text" value={organizations[0]?.name ?? orgId} readOnly aria-readonly="true" />
          )}
        </label>

        {!secret || rotating ? (
          <>
            {/* Not a wrapping <label>: the Show button would become part of the input's accessible name. */}
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
                  autoFocus={rotating}
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
            <p className="field-hint">{PASSWORD_HINT}</p>
          </>
        ) : (
          <div className="row" style={{ alignItems: "center", marginBottom: 14 }}>
            <span className="field-label" style={{ margin: 0, flex: "0 0 auto" }}>
              Value
            </span>
            <span className="badge badge-enabled">saved</span>
            <button type="button" className="link-btn" onClick={() => setRotating(true)}>
              Rotate…
            </button>
          </div>
        )}

        {secret && (
          <label className="checkbox-label" style={{ marginBottom: 14 }}>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Active
            {!isActive && usedBy.length > 0 && (
              <span className="muted" style={{ fontSize: "0.78rem" }}>
                — revoked; {usedBy.length} report{usedBy.length === 1 ? "" : "s"}/connection{usedBy.length === 1 ? "" : "s"} using it will fail until reactivated or repointed
              </span>
            )}
          </label>
        )}

        {secret && (
          <div className="conn-used-by">
            <span className="field-label">Used by</span>
            {usedBy.length === 0 ? (
              <p className="muted">Nothing refers to this credential yet.</p>
            ) : (
              <ul>
                {usedBy.map((r) =>
                  r.kind === "report" ? (
                    <li key={`report-${r.report_id}`}>
                      <a href={`#/reports/${encodeURIComponent(r.code ?? r.report_id ?? "")}/data-source`}>{r.name}</a>
                    </li>
                  ) : (
                    <li key={`connection-${r.connection_id}`}>
                      <a href="#/admin/connections">{r.name}</a> (connection)
                    </li>
                  )
                )}
              </ul>
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
            {secret ? "Save changes" : "Create credential"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
