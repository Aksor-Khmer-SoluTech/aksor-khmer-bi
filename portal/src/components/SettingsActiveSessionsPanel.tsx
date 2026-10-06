import { useEffect, useState } from "react";
import { DeviceDesktopIcon, DeviceMobileIcon, DeviceTabletIcon } from "../admin/icons";
import { api, ApiError } from "../api";
import { LinesSkeleton } from "./Skeletons";
import type { DeviceType, UserSession } from "../types";

function DeviceIcon({ type }: { type: DeviceType }) {
  if (type === "mobile") return <DeviceMobileIcon />;
  if (type === "tablet") return <DeviceTabletIcon />;
  return <DeviceDesktopIcon />;
}

/** Settings modal — Active Sessions tab: the browsers and devices this account is signed in on right now
 * (api/app/auth_tokens.py), each one revocable. Signing a session out ends it immediately -- its access token
 * stops working on the next request and its refresh cookie can't be renewed. Past sign-ins, including failed
 * attempts, are the Authentication Log's job (see SettingsAuthLogPanel.tsx). */
export default function SettingsActiveSessionsPanel({ onGoToAccess }: { onGoToAccess: () => void }) {
  const [sessions, setSessions] = useState<UserSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    api.sessions
      .list()
      .then((list) => {
        setError(null);
        setSessions(list);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load active sessions"));
  }

  useEffect(load, []);

  async function signOut(id: string) {
    setBusy(id);
    try {
      await api.sessions.revoke(id);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't sign that session out");
    } finally {
      setBusy(null);
    }
  }

  async function signOutOthers() {
    setBusy("others");
    try {
      await api.sessions.revokeOthers();
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't sign the other sessions out");
    } finally {
      setBusy(null);
    }
  }

  if (error && sessions === null) return <p className="alert alert-error">{error}</p>;

  const others = sessions?.filter((s) => !s.current).length ?? 0;

  return (
    <div className="panel max-w-5xl">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="panel-title">Active sessions</h3>
          <p className="panel-subtitle">
            Where you're signed in right now. Sign out any you don't recognize — it ends at once. If one looks wrong, also{" "}
            <button type="button" className="link-btn" onClick={onGoToAccess}>
              change your password
            </button>
            , which signs out every other session.
          </p>
        </div>
        {others > 0 && (
          <button type="button" className="btn btn-sm btn-danger" onClick={signOutOthers} disabled={busy !== null}>
            {busy === "others" && <span className="spinner" />}
            Sign out {others} other session{others === 1 ? "" : "s"}
          </button>
        )}
      </div>
      {error && <p className="alert alert-error">{error}</p>}
      {sessions === null ? (
        <LinesSkeleton count={3} />
      ) : sessions.length === 0 ? (
        <p className="muted">No live sessions.</p>
      ) : (
        <div className="stack">
          {sessions.map((s) => (
            <div key={s.id} className="flex items-start gap-3 rounded-sm border border-border-soft px-3 py-2.5">
              <span className="mt-0.5 text-text-faint">
                <DeviceIcon type={s.device_type} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[0.88rem] font-medium text-text">
                    {s.browser} · {s.os}
                  </span>
                  {s.current && <span className="badge badge-active">This session</span>}
                  {s.remember && <span className="badge badge-system">Kept signed in</span>}
                </div>
                <div className="mt-0.5 text-[0.78rem] text-text-faint">
                  <span className="mono">{s.ip_address ?? "unknown IP"}</span> · signed in {new Date(s.created_at).toLocaleString()} · last
                  active {new Date(s.last_used_at).toLocaleString()} · ends {new Date(s.expires_at).toLocaleString()}
                </div>
              </div>
              {!s.current && (
                <button type="button" className="btn btn-sm" onClick={() => signOut(s.id)} disabled={busy !== null}>
                  {busy === s.id && <span className="spinner" />}
                  Sign out
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
