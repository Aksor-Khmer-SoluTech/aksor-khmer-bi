import { ArrowLeft, ShieldCheck } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { api, ApiError, TOTP_REQUIRED } from "../api";
import type { AuthInfo } from "../types";
import LoginShell from "./LoginShell";

const CODE_LENGTH = 6;

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
  const [codeFocused, setCodeFocused] = useState(false);
  const codeInput = useRef<HTMLInputElement>(null);

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
      if (code) {
        // A wrong or expired code: clear the boxes and put the cursor back, ready for the next one.
        setTotpCode("");
        codeInput.current?.focus();
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
    if (totpCode.length === CODE_LENGTH) void signIn(totpCode);
  }

  // Digits only (a pasted "123 456" works too); the sixth digit submits by itself.
  function changeCode(value: string) {
    const digits = value.replace(/\D/g, "").slice(0, CODE_LENGTH);
    setTotpCode(digits);
    if (error) setError(null);
    if (digits.length === CODE_LENGTH && !pending) void signIn(digits);
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
            <form onSubmit={handleTotpSubmit} className="totp-step">
              <button type="button" className="totp-account" onClick={backToCredentials} title="Sign in as someone else">
                <ArrowLeft size={15} aria-hidden="true" />
                <span className="totp-account-avatar" aria-hidden="true">
                  {username.trim().charAt(0).toUpperCase() || "?"}
                </span>
                <span className="totp-account-name">{username.trim()}</span>
                <span className="totp-account-change">Change</span>
              </button>

              <div className="totp-title">
                <span className="totp-icon" aria-hidden="true">
                  <ShieldCheck size={20} />
                </span>
                <div>
                  <h2>Two-step verification</h2>
                  <p>Enter the 6-digit code from your authenticator app. It changes every 30 seconds.</p>
                </div>
              </div>

              <label className="totp-code" onClick={() => codeInput.current?.focus()}>
                <span className="sr-only">Authentication code</span>
                <input
                  ref={codeInput}
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]*"
                  maxLength={CODE_LENGTH + 4}
                  autoFocus
                  value={totpCode}
                  readOnly={pending}
                  aria-invalid={error ? true : undefined}
                  onChange={(e) => changeCode(e.target.value)}
                  onFocus={() => setCodeFocused(true)}
                  onBlur={() => setCodeFocused(false)}
                />
                <span className={`totp-cells${error ? " has-error" : ""}`} aria-hidden="true">
                  {Array.from({ length: CODE_LENGTH }, (_, i) => (
                    <span
                      key={i}
                      className={`totp-cell${totpCode[i] ? " filled" : ""}${
                        codeFocused && i === Math.min(totpCode.length, CODE_LENGTH - 1) ? " active" : ""
                      }${i === 2 ? " gap-after" : ""}`}
                    >
                      {totpCode[i] ?? ""}
                    </span>
                  ))}
                </span>
              </label>

              {error && <p className="alert alert-error">{error}</p>}
              <button type="submit" className="btn btn-primary" disabled={pending || totpCode.length < CODE_LENGTH}>
                {pending && <span className="spinner" />}
                {pending ? "Verifying…" : "Verify"}
              </button>
              <p className="totp-help">
                Lost your phone or authenticator? Ask an administrator to reset two-step verification on your account.
              </p>
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
