import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { PASSWORD_HINT, passwordProblem } from "../passwords";
import type { AuthInfo } from "../types";
import LoginShell from "./LoginShell";

/** Shown instead of the console while the signed-in account is flagged
 * must-change-password (an admin created it or reset its password, so the
 * one they were handed is temporary). The API refuses everything else until
 * this succeeds -- see api/app/auth.py -- so this screen isn't a courtesy the
 * portal could skip; it's the only way forward besides signing out.
 *
 * The same screen runs the first-run setup (`auth.setupRequired`): the built-in
 * admin's password in .env was generated at install time, so instead of changing
 * it, the chosen password becomes a real administrator account with the same name
 * (api.setupAdmin), and the generated one stops working. */
export default function ForcePasswordChange({
  auth,
  onChanged,
  onAccountReady,
}: {
  auth: AuthInfo;
  onChanged: () => void;
  onAccountReady: (info: AuthInfo) => void;
}) {
  const setup = auth.setupRequired;
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
    if (!setup && newPassword === currentPassword) return setError("Choose a password different from the temporary one.");
    if (newPassword !== confirmPassword) return setError("New password and confirmation don't match.");

    setPending(true);
    try {
      if (setup) {
        // Signed in as the new administrator account from here on.
        onAccountReady(await api.setupAdmin(newPassword));
        return;
      }
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
        <h1 className="login-heading">{setup ? "Set your administrator password" : "Choose a new password"}</h1>
        <div className="panel">
          {setup ? (
            <p className="field-hint" style={{ marginTop: 0 }}>
              Welcome. You signed in as <strong className="mono">{auth.username}</strong> with the password generated
              when this server was installed. Choose your own to finish setting up — it becomes your administrator
              account, and the generated password stops working.
            </p>
          ) : (
            <p className="field-hint" style={{ marginTop: 0 }}>
              Signed in as <strong className="mono">{auth.username}</strong>. Your password was set by an
              administrator — choose your own to continue.
            </p>
          )}
          <form onSubmit={handleSubmit}>
            {!setup && (
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
            )}
            <label>
              <span>New password</span>
              <input
                type="password"
                autoComplete="new-password"
                autoFocus={setup}
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
              {setup ? "Finish setup" : "Change password"}
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
