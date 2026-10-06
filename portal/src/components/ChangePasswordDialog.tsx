import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { useDialogRef } from "../hooks";
import { PASSWORD_HINT, passwordProblem } from "../passwords";
import type { User } from "../types";

import ModalClose from "./ModalClose";
/** Popup for Settings > Access's "Change password" button — used to be
 * three fields sitting inline on the page at all times; moved into its
 * own dialog (matches GitLab's own Password section: a button that
 * opens the actual form, not fields always on display) since a password
 * change is an occasional action, not something that needs permanent
 * screen space. */
export default function ChangePasswordDialog({
  open,
  onUpdated,
  onClose,
}: {
  open: boolean;
  onUpdated: (u: User) => void;
  onClose: () => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ref = useDialogRef(open, () => {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setError(null);
  });

  async function savePassword(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const problem = passwordProblem(newPassword);
    if (problem) {
      setError(problem);
      return;
    }
    if (newPassword === currentPassword) {
      setError("Choose a password different from your current one.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New password and confirmation don't match.");
      return;
    }
    setSaving(true);
    try {
      const updated = await api.users.updateMe({ current_password: currentPassword, new_password: newPassword });
      onUpdated(updated);
      // Nothing to re-store: this session keeps working (its access token doesn't carry the password),
      // while the account's *other* sessions are signed out by the server.
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change password");
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog ref={ref} className="modal" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">Change password</h2>
      <form onSubmit={savePassword} className="stack">
        <label>
          <span>Current password</span>
          <input
            type="password"
            autoComplete="current-password"
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
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving && <span className="spinner" />}
            Change password
          </button>
        </div>
      </form>
    </dialog>
  );
}
