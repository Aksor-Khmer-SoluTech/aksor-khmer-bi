import { useId, useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import CopyButton from "../../components/CopyButton";
import { useDialogRef } from "../../hooks";
import { generatePassword, PASSWORD_HINT, passwordProblem } from "../../passwords";
import type { AuthSource, Organization, User } from "../../types";

import ModalClose from "../../components/ModalClose";
export default function UserFormDialog({
  open,
  onClose,
  onCreated,
  organizations,
  defaultOrgId,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (user: User) => void;
  organizations: Organization[];
  defaultOrgId: string;
}) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [orgId, setOrgId] = useState(defaultOrgId);
  const [authSource, setAuthSource] = useState<AuthSource>("local");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const passwordId = useId();
  // On by default: a password an admin picked is a temporary one, so the new
  // user chooses their own at first sign-in. Off for an account nobody signs
  // in to interactively.
  const [mustChange, setMustChange] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const ref = useDialogRef(open, () => {
    setUsername("");
    setEmail("");
    setDisplayName("");
    setOrgId(defaultOrgId);
    setAuthSource("local");
    setPassword("");
    setShowPassword(false);
    setMustChange(true);
    setError(null);
  });

  function fillGeneratedPassword() {
    setPassword(generatePassword());
    // Nobody can copy what they can't see, and this is the admin's only chance.
    setShowPassword(true);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const problem = authSource === "local" ? passwordProblem(password) : null;
    if (problem) {
      setError(problem);
      return;
    }
    setPending(true);
    try {
      const user = await api.users.create(orgId, {
        username,
        email: email || null,
        display_name: displayName || null,
        auth_source: authSource,
        password: authSource === "local" ? password : null,
        must_change_password: authSource === "local" ? mustChange : false,
      });
      onCreated(user);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the user");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">New user</h2>
      <p className="panel-subtitle">Roles and permissions are granted after creation.</p>
      <form onSubmit={handleSubmit}>
        <label>
          <span>Username</span>
          <input type="text" required value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
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
        {organizations.length > 1 && (
          <label>
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
          <span>Auth source</span>
          <select value={authSource} onChange={(e) => setAuthSource(e.target.value as AuthSource)}>
            <option value="local">Local (password)</option>
            <option value="ldap">LDAP / Active Directory</option>
          </select>
        </label>
        {authSource === "local" ? (
          <>
            {/* Not a wrapping <label>: Generate / Show / copy would become part of the input's accessible name. */}
            <div className="field-block">
              <label className="field-label" htmlFor={passwordId}>
                Temporary password
              </label>
              <div className="password-field">
                <input
                  id={passwordId}
                  type={showPassword ? "text" : "password"}
                  required
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button type="button" className="btn btn-sm" onClick={fillGeneratedPassword}>
                  Generate
                </button>
                <button type="button" className="link-btn" onClick={() => setShowPassword((v) => !v)}>
                  {showPassword ? "Hide" : "Show"}
                </button>
                {password && <CopyButton text={password} />}
              </div>
            </div>
            <p className="field-hint">{PASSWORD_HINT}</p>
            <label className="checkbox-label">
              <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
              Require a password change at first sign-in
            </label>
          </>
        ) : (
          <p className="field-hint" style={{ marginTop: 0 }}>
            They sign in with their directory credentials; the password stays in your directory.
          </p>
        )}
        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            Create user
          </button>
        </div>
      </form>
    </dialog>
  );
}
