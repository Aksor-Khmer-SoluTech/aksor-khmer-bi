import { useEffect, useState } from "react";
import { AuthFailureIcon, AuthSuccessIcon } from "../admin/icons";
import { api, ApiError } from "../api";
import { LinesSkeleton } from "./Skeletons";
import type { AuthEvent } from "../types";

/** Settings modal — Authentication log tab: every recorded sign-in and
 * failed attempt on this account (see app/db/auth_events.py), most
 * recent first — GitLab's own "Authentication log" page under Access.
 * Split from the active-devices list (see SettingsActiveSessionsPanel.tsx)
 * since the two answer different questions: "where am I signed in right
 * now" vs. "what's been attempted against this account over time." */
export default function SettingsAuthLogPanel() {
  const [log, setLog] = useState<AuthEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.users
      .authLog()
      .then(setLog)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the authentication log"));
  }, []);

  if (error) return <p className="alert alert-error">{error}</p>;

  return (
    <div className="panel max-w-5xl">
      <h3 className="panel-title">Authentication log</h3>
      <p className="panel-subtitle">Every recorded sign-in and failed attempt on this account, most recent first.</p>
      {log === null ? (
        <LinesSkeleton count={4} />
      ) : log.length === 0 ? (
        <p className="muted">Nothing recorded yet.</p>
      ) : (
        <div className="stack">
          {log.map((e) => (
            <div key={e.id} className="flex items-start gap-3 rounded-sm border border-border-soft px-3 py-2.5">
              <span className={`mt-0.5 ${e.success ? "text-success" : "text-danger"}`}>
                {e.success ? <AuthSuccessIcon /> : <AuthFailureIcon />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[0.88rem] font-medium text-text">
                  {e.success ? "Signed in" : "Failed sign-in attempt"} · {e.browser} · {e.os}
                </div>
                <div className="mt-0.5 text-[0.78rem] text-text-faint">
                  <span className="mono">{e.ip_address ?? "unknown IP"}</span> · {new Date(e.created_at).toLocaleString()}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
