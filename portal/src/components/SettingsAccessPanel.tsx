import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import type { TotpEnrollment, User } from "../types";
import ChangePasswordDialog from "./ChangePasswordDialog";

type TotpStep = "status" | "enrolling" | "disabling";

/** Two-factor authentication -- see api/app/totp.py's module docstring.
 * Signing in (Login.tsx's two-step flow) needs the code, and an account with 2FA
 * can't use a bare username and password on the API either, so the second
 * factor guards the whole account. The copy below says what that means for
 * scripts, which is the one thing it changes for them. */
function TwoFactorSection({ user, onUpdated }: { user: User; onUpdated: (u: User) => void }) {
  const [step, setStep] = useState<TotpStep>("status");
  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setStep("status");
    setEnrollment(null);
    setCode("");
    setError(null);
  }

  async function startEnroll() {
    setBusy(true);
    setError(null);
    try {
      setEnrollment(await api.users.totp.enroll());
      setStep("enrolling");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start enrollment");
    } finally {
      setBusy(false);
    }
  }

  async function confirmEnroll(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onUpdated(await api.users.totp.confirm(code));
      reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That code didn't match");
    } finally {
      setBusy(false);
    }
  }

  async function confirmDisable(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onUpdated(await api.users.totp.disable(code));
      reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That code didn't match");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3 className="panel-title">Two-factor authentication</h3>
      <p className="panel-subtitle">
        Adds a code step to signing in. Once it's on, your password alone no longer works for scripts calling
        the API either, so the second factor can't be walked around — give a script its own service account
        (or, to run reports, an API client under Manage → API Clients). If you think your password's been exposed,
        change it too.
      </p>

      {step === "status" && (
        <div className="stack">
          <div>
            <span className={`badge ${user.totp_enabled ? "badge-enabled" : "badge-disabled"}`}>
              {user.totp_enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          {error && <p className="alert alert-error">{error}</p>}
          {user.totp_enabled ? (
            <div>
              <button type="button" className="btn btn-sm btn-danger" onClick={() => setStep("disabling")}>
                Disable
              </button>
            </div>
          ) : (
            <div>
              <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={startEnroll}>
                {busy && <span className="spinner" />}
                Enable 2FA
              </button>
            </div>
          )}
        </div>
      )}

      {step === "enrolling" && enrollment && (
        <form onSubmit={confirmEnroll} className="stack">
          <p className="mt-0 text-[0.85rem] text-text-dim">
            Scan this with an authenticator app (Google Authenticator, 1Password, Authy, ...):
          </p>
          <img src={enrollment.qr_code_data_url} alt="Scan this QR code with your authenticator app" className="h-40 w-40 rounded-sm border border-border" />
          <p className="text-[0.78rem] text-text-faint">
            Can't scan it? Enter this key manually: <span className="mono">{enrollment.secret}</span>
          </p>
          <label>
            <span>Code from the app</span>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              className="mono"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
          {error && <p className="alert alert-error">{error}</p>}
          <div className="dialog-actions justify-start">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy && <span className="spinner" />}
              Confirm
            </button>
            <button type="button" className="btn" onClick={reset}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {step === "disabling" && (
        <form onSubmit={confirmDisable} className="stack">
          <label>
            <span>Current code</span>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              className="mono"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
          {error && <p className="alert alert-error">{error}</p>}
          <div className="dialog-actions justify-start">
            <button type="submit" className="btn btn-danger" disabled={busy}>
              {busy && <span className="spinner" />}
              Disable
            </button>
            <button type="button" className="btn" onClick={reset}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/** Settings modal — Access tab: how this account authenticates. A
 * `local` user changes their own password via the ChangePasswordDialog
 * popup (current_password required there — see UserSelfUpdate's
 * docstring on api/app/models/rbac.py); an `ldap` user's password lives
 * in their directory, so no button renders at all for them. */
export default function SettingsAccessPanel({ user, onUpdated }: { user: User; onUpdated: (u: User) => void }) {
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);

  return (
    <div className="stack max-w-5xl">
      <div className="panel">
        <div className="spread">
          <div>
            <h3 className="panel-title">Authentication type</h3>
            <p className="panel-subtitle mb-0">
              <span className={`badge badge-${user.auth_source}`}>{user.auth_source}</span>{" "}
              {user.auth_source === "local" ? "— password managed here." : "— managed by your identity provider."}
            </p>
          </div>
          {user.auth_source === "local" && (
            <button type="button" className="btn" onClick={() => setPasswordDialogOpen(true)}>
              Change password
            </button>
          )}
        </div>
      </div>

      <TwoFactorSection user={user} onUpdated={onUpdated} />

      <ChangePasswordDialog
        open={passwordDialogOpen}
        onUpdated={onUpdated}
        onClose={() => setPasswordDialogOpen(false)}
      />
    </div>
  );
}
