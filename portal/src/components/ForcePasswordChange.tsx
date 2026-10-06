import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { PASSWORD_HINT, passwordProblem } from "../passwords";
import type { AuthInfo } from "../types";
import LoginShell from "./LoginShell";

/** Shown instead of the console while the signed-in account is flagged
 * must-change-password (an admin created it or reset its password, so the
 * one they were handed is temporary). The API refuses everything else until
 * this succeeds -- see api/app/auth.py -- so this screen isn't a courtesy the
 * portal could skip; it's the only way forward besides signing out. */
export default function ForcePasswordChange({ auth, onChanged }: { auth: AuthInfo; onChanged: () => void }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const problem = passwordProblem(newPassword);
    if (problem) return setError(problem);
    if (newPassword === currentPassword) return setError("Choose a password different from the temporary one.");
    if (newPassword !== confirmPassword) return setError("New password and confirmation don't match.");

    setPending(true);
    try {
      await api.users.updateMe({ current_password: currentPassword, new_password: newPassword });
      // This session carries on as it is; the server ended the account's other sessions.
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change the password");
      setPending(false);
    }
  }

  async function signOut() {
    await api.logout();
    window.location.reload();
  }

  return (
    <LoginShell>
      <div className="login-card">
        <h1 className="login-heading">Choose a new password</h1>
        <div className="panel">
          <p className="field-hint" style={{ marginTop: 0 }}>
            Signed in as <strong className="mono">{auth.username}</strong>. Your password was set by an
            administrator — choose your own to continue.
          </p>
          <form onSubmit={handleSubmit}>
            <label>
              <span>Current (temporary) password</span>
              <input
                type="password"
                autoComplete="current-password"
                autoFocus
                required
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
              />
            </label>
            <label>
              <span>New password</span>
              <input
                type="password"
                autoComplete="new-password"
                required
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </label>
            <p className="field-hint">{PASSWORD_HINT}</p>
            <label>
              <span>Confirm new password</span>
              <input
                type="password"
                autoComplete="new-password"
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </label>
            {error && <p className="alert alert-error">{error}</p>}
            <button type="submit" className="btn btn-primary" disabled={pending}>
              {pending && <span className="spinner" />}
              Change password
            </button>
          </form>
        </div>
        <p className="field-hint" style={{ textAlign: "center", marginTop: 16 }}>
          Not you?{" "}
          <button type="button" className="link-btn" onClick={signOut}>
            Sign out
          </button>
        </p>
      </div>
    </LoginShell>
  );
}
