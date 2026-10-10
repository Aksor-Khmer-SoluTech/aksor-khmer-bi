import { useState } from "react";
import { api, ApiError } from "../api";
import type { User } from "../types";

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative mt-0.5 inline-flex h-6 w-11 flex-none cursor-pointer items-center rounded-full border-none p-0 transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        checked ? "bg-accent" : "bg-bg-panel-hover"
      }`}
    >
      <span
        aria-hidden="true"
        className={`inline-block h-[18px] w-[18px] rounded-full bg-bg-raised shadow-card transition-transform ${
          checked ? "translate-x-[22px]" : "translate-x-1"
        }`}
      />
    </button>
  );
}

/** Settings modal — Notifications tab: exactly one real, working
 * preference, deliberately — this console has no email/push delivery
 * channel to speak of yet (see NotificationsMenu.tsx's own history), so
 * the only notification honest to ship is the one already fully wired
 * end to end: an in-app alert (the bell in TopBar) when app/auth_events.py
 * notices a sign-in from a browser that has never signed in to this
 * account before. */
export default function SettingsNotificationsPanel({ user, onUpdated }: { user: User; onUpdated: (u: User) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle(next: boolean) {
    setSaving(true);
    setError(null);
    try {
      onUpdated(await api.users.updateMe({ notify_new_signin: next }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="stack max-w-5xl">
      <div className="panel">
        <div className="flex items-start gap-3">
          <Toggle checked={user.notify_new_signin} onChange={toggle} disabled={saving} />
          <div>
            <div className="text-[0.9rem] font-medium text-text">New sign-in alerts</div>
            <p className="mt-1 mb-0 text-[0.8rem] leading-snug text-text-faint">
              When this account signs in on a browser it hasn't used before, the bell in the top bar asks you —
              on your other signed-in browsers — whether it was you. If it wasn't, one click signs that device out.
              In the portal only; there's no email or push yet.
            </p>
          </div>
        </div>
      </div>
      {error && <p className="alert alert-error">{error}</p>}
    </div>
  );
}
