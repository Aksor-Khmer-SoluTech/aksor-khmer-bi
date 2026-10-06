import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import CopyButton from "../../components/CopyButton";
import { useDialogRef } from "../../hooks";
import { PASSWORD_HINT, passwordProblem } from "../../passwords";
import type { PasswordResetResult, User } from "../../types";

import ModalClose from "../../components/ModalClose";
type Mode = "generate" | "choose";

/** Admin > Users > a user > "Reset password". Two ways to do it -- let the
 * server generate one (the default: nobody types a password into a chat
 * message, and it's strong) or type one -- and, by default, force the user to
 * replace it at next sign-in, since an admin has now seen it.
 *
 * A generated password comes back exactly once (the server keeps only its
 * hash), so that result stage can't be dismissed with Escape and says so. */
export default function ResetPasswordDialog({
  user,
  onClose,
  onReset,
}: {
  user: User | null;
  onClose: () => void;
  onReset: (user: User) => void;
}) {
  const [mode, setMode] = useState<Mode>("generate");
  const [password, setPassword] = useState("");
  const [requireChange, setRequireChange] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PasswordResetResult | null>(null);

  const ref = useDialogRef(user !== null, () => {
    setMode("generate");
    setPassword("");
    setRequireChange(true);
    setPending(false);
    setError(null);
    setResult(null);
  });

  // Drop the result on the way out, not just on the next open: a generated
  // password shouldn't sit in state (or flash on the next open) after it's been dismissed.
  function close() {
    setResult(null);
    setPassword("");
    onClose();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    setError(null);
    if (mode === "choose") {
      const problem = passwordProblem(password);
      if (problem) return setError(problem);
    }
    setPending(true);
    try {
      const done = await api.users.resetPassword(user.id, {
        ...(mode === "choose" ? { password } : {}),
        require_change: requireChange,
      });
      onReset(done.user);
      setResult(done);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reset the password");
    } finally {
      setPending(false);
    }
  }

  const generated = result?.generated_password ?? null;

  return (
    <dialog
      ref={ref}
      className="modal"
      // A generated password can't be brought back, so leaving that stage takes a click.
      onCancel={(e) => (generated ? e.preventDefault() : close())}
    >
      {user && !result && (
        <form onSubmit={handleSubmit}>
          <h2 className="panel-title">Reset password</h2>
          <p className="panel-subtitle">
            <span className="mono">{user.username}</span>'s current password stops working immediately.
          </p>
      <ModalClose hidden={Boolean(generated)} />

          <div className="stack" style={{ marginBottom: 14 }}>
            <label className="checkbox-label">
              <input type="radio" name="reset-mode" checked={mode === "generate"} onChange={() => setMode("generate")} />
              Generate a temporary password
            </label>
            <label className="checkbox-label">
              <input type="radio" name="reset-mode" checked={mode === "choose"} onChange={() => setMode("choose")} />
              Choose a password
            </label>
          </div>

          {mode === "choose" && (
            <>
              <label>
                <span>New password</span>
                <input
                  type="password"
                  required
                  autoFocus
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <p className="field-hint">{PASSWORD_HINT}</p>
            </>
          )}

          <label className="checkbox-label" style={{ marginBottom: 14 }}>
            <input type="checkbox" checked={requireChange} onChange={(e) => setRequireChange(e.target.checked)} />
            Require them to choose their own password at next sign-in
          </label>

          {error && <p className="alert alert-error">{error}</p>}
          <div className="dialog-actions">
            <button type="button" className="btn" onClick={close}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={pending}>
              {pending && <span className="spinner" />}
              Reset password
            </button>
          </div>
        </form>
      )}

      {user && result && (
        <>
          <h2 className="panel-title">Password reset</h2>
          {generated ? (
            <>
              <p className="alert alert-warning">
                Copy the temporary password now — it is shown only this once and can't be looked up later. Lost it?
                Reset the password again.
              </p>
              <div className="client-credential">
                <span className="client-credential-label">Username</span>
                <code className="mono client-credential-value">{user.username}</code>
                <CopyButton text={user.username} />
              </div>
              <div className="client-credential">
                <span className="client-credential-label">Temporary password</span>
                <code className="mono client-credential-value">{generated}</code>
                <CopyButton text={generated} />
              </div>
            </>
          ) : (
            <p className="alert alert-success">
              {user.username}'s password was changed to the one you entered.
            </p>
          )}
          <p className="muted" style={{ fontSize: "0.82rem" }}>
            {result.user.must_change_password
              ? "They'll be asked to choose their own password when they next sign in."
              : "They can keep using it — no change is required."}{" "}
            Send it over a channel you trust, not somewhere it will sit in plain sight.
          </p>
          <div className="dialog-actions">
            <button type="button" className="btn btn-primary" onClick={close}>
              {generated ? "I've saved it" : "Done"}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
