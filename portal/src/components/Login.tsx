import { useState, type FormEvent } from "react";
import { api, ApiError, TOTP_REQUIRED } from "../api";
import type { AuthInfo } from "../types";
import LoginShell from "./LoginShell";

export default function Login({ onSignedIn }: { onSignedIn: (auth: AuthInfo) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // Stay signed in on this browser for weeks, rather than until the working day (or the browser) ends.
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Step 2FA-enabled accounts land on: the username/password step already
  // passed (that's what earned the TOTP_REQUIRED answer). The password stays
  // in this component's state, and nowhere else, just long enough to send it
  // again with the code -- so the person isn't asked for it twice.
  const [needsCode, setNeedsCode] = useState(false);
  const [totpCode, setTotpCode] = useState("");

  async function signIn(code?: string) {
    setError(null);
    setPending(true);
    let result: AuthInfo | ApiError;
    try {
      result = await api.login(username, password, { totpCode: code, remember });
    } catch {
      // api.login reports its own failures as an ApiError; this is the "something truly unexpected" net, so the
      // button comes back and the person is told, rather than left looking at a spinner.
      result = new ApiError(0, "Something went wrong signing in. Try again.");
    } finally {
      setPending(false);
    }
    if (result instanceof ApiError) {
      if (result.message === TOTP_REQUIRED) {
        setNeedsCode(true);
        return;
      }
      setError(
        result.status === 503
          ? "Portal authentication isn't configured on the server (PORTAL_USERNAME/PORTAL_PASSWORD)."
          : result.message
      );
      return;
    }
    setPassword("");
    setTotpCode("");
    onSignedIn(result);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    void signIn();
  }

  function handleTotpSubmit(e: FormEvent) {
    e.preventDefault();
    void signIn(totpCode);
  }

  function backToCredentials() {
    setNeedsCode(false);
    setTotpCode("");
    setError(null);
  }

  return (
    <LoginShell>
      <div className="login-card">
        <h1 className="login-heading">Sign in</h1>
        <div className="panel">
          {needsCode ? (
            <form onSubmit={handleTotpSubmit}>
              <p className="field-hint" style={{ marginTop: 0 }}>
                Enter the 6-digit code from your authenticator app.
              </p>
              <label>
                <span>Authentication code</span>
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  required
                  className="mono"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                />
              </label>
              {error && <p className="alert alert-error">{error}</p>}
              <div className="dialog-actions justify-between">
                <button type="button" className="link-btn" onClick={backToCredentials}>
                  Back
                </button>
                <button type="submit" className="btn btn-primary" disabled={pending}>
                  {pending && <span className="spinner" />}
                  Verify
                </button>
              </div>
            </form>
          ) : (
            <form onSubmit={handleSubmit}>
              <label>
                <span>Username</span>
                <input
                  type="text"
                  autoComplete="username"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </label>
              <label>
                <span>Password</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <label className="checkbox-label" style={{ marginBottom: 14 }}>
                <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                Keep me signed in on this device
              </label>
              {error && <p className="alert alert-error">{error}</p>}
              <button type="submit" className="btn btn-primary" disabled={pending}>
                {pending && <span className="spinner" />}
                Sign in
              </button>
            </form>
          )}
        </div>
        <p className="field-hint" style={{ textAlign: "center", marginTop: 16 }}>
          This console's own screens require a sign-in, but the underlying API stays open for
          reading and rendering — see the Integration tab on any template for a plain curl example.
        </p>
      </div>
    </LoginShell>
  );
}
