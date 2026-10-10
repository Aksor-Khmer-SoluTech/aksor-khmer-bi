import { useEffect, useRef, useState } from "react";
import { BellIcon } from "../admin/icons";
import { api, ApiError } from "../api";
import { ago } from "../relativeTime";
import type { AuthEvent } from "../types";
import { openSettings } from "./AccountMenu";

/** Notifications bell in TopBar: sign-ins to your account from a browser that had never signed in to it before
 * (app/auth_events.py), gated by Settings > Notifications' toggle. The server shows each one only to your *other*
 * sessions, so whoever is on the new device never sees it. Each alert stays until you answer it -- opening the bell
 * doesn't dismiss anything:
 *  - "It was me" dismisses it;
 *  - "Not me" signs that device out at once, then offers to change the password (which keeps them out) and to
 *    review the rest of your sign-in activity (Settings > Authentication Log). */
export default function NotificationsMenu() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AuthEvent[]>([]);
  // Alerts answered "Not me" in this panel: kept on screen to say what happened and offer the next steps.
  const [disowned, setDisowned] = useState<Record<string, boolean>>({});
  const disownedRef = useRef(disowned);
  disownedRef.current = disowned;
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // Checked on load, every minute, and when you come back to the tab -- a sign-in elsewhere should show up here
  // without a reload. Alerts already answered "Not me" in this panel stay until you move on.
  useEffect(() => {
    const load = () =>
      api.users
        .notifications()
        .then((fresh) => setItems((current) => [...fresh, ...current.filter((x) => x.id in disownedRef.current && !fresh.some((f) => f.id === x.id))]))
        .catch(() => {});
    load();
    const timer = window.setInterval(load, 60_000);
    const onVisible = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  async function answer(e: AuthEvent, mine: boolean) {
    setBusy(e.id);
    setError(null);
    try {
      if (mine) {
        await api.users.confirmSignIn(e.id);
        setItems((list) => list.filter((x) => x.id !== e.id));
      } else {
        const { signed_out } = await api.users.disownSignIn(e.id);
        setDisowned((d) => ({ ...d, [e.id]: signed_out }));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work -- try again.");
    } finally {
      setBusy(null);
    }
  }

  function goTo(tab: "access" | "authLog") {
    setOpen(false);
    // Answered alerts leave once you move on.
    setItems((list) => list.filter((x) => !(x.id in disowned)));
    openSettings(tab);
  }

  const pending = items.filter((e) => !(e.id in disowned));

  return (
    <div className="notif-menu" ref={rootRef}>
      <button
        type="button"
        className={`btn btn-ghost btn-sm icon-only relative ${open ? "active" : ""}`}
        onClick={() => setOpen((o) => !o)}
        title="Notifications"
        data-tour="notifications"
        aria-expanded={open}
        aria-label={pending.length > 0 ? `Notifications: ${pending.length} new sign-in${pending.length === 1 ? "" : "s"} to check` : "Notifications"}
      >
        <BellIcon />
        {pending.length > 0 && (
          <span className="absolute top-1 right-1 h-[7px] w-[7px] rounded-full bg-danger" aria-hidden="true" />
        )}
      </button>

      {open && (
        <div className="notif-panel" role="dialog" aria-label="Notifications">
          <div className="notif-panel-header">Notifications</div>
          {items.length === 0 ? (
            <div className="notif-empty">
              <BellIcon />
              <p>You're all caught up</p>
              <span className="muted">If your account signs in on a browser it hasn't used before, you'll be asked here whether it was you.</span>
            </div>
          ) : (
            <div className="stack p-3">
              {error && <p className="alert alert-error">{error}</p>}
              {items.map((e) => {
                const answeredNotMe = e.id in disowned;
                return (
                  <div
                    key={e.id}
                    className={`rounded-sm border px-3 py-2.5 ${answeredNotMe ? "border-danger/40 bg-danger/5" : "border-border-soft"}`}
                  >
                    <div className="text-[0.85rem] font-medium text-text">
                      {answeredNotMe ? "Device signed out" : "New sign-in to your account"}
                    </div>
                    <div className="mt-0.5 text-[0.78rem] text-text-faint">
                      {e.browser} on {e.os} · <span className="mono">{e.ip_address ?? "unknown IP"}</span>
                    </div>
                    <div className="mt-0.5 text-[0.74rem] text-text-faint" title={new Date(e.created_at).toLocaleString()}>
                      {ago(e.created_at)}
                      {!answeredNotMe && (e.session_active ? " · still signed in" : " · no longer signed in")}
                    </div>

                    {answeredNotMe ? (
                      <div className="mt-2 text-[0.8rem] text-text-dim">
                        {disowned[e.id] ? "That device has been signed out. " : "It had already signed out. "}
                        Change your password so whoever it was can't sign in again.
                        <div className="mt-2 flex flex-wrap gap-2">
                          <button type="button" className="btn btn-primary btn-sm" onClick={() => goTo("access")}>
                            Change password
                          </button>
                          <button type="button" className="btn btn-sm" onClick={() => goTo("authLog")}>
                            Review sign-in activity
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="mt-2 text-[0.8rem] text-text-dim">Was this you?</div>
                        <div className="mt-1.5 flex flex-wrap gap-2">
                          <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={() => answer(e, true)}>
                            It was me
                          </button>
                          <button type="button" className="btn btn-danger btn-sm" disabled={busy !== null} onClick={() => answer(e, false)}>
                            {e.session_active ? "Not me — sign it out" : "Not me"}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
              <button type="button" className="link-btn self-start text-[0.8rem]" onClick={() => goTo("authLog")}>
                See all your sign-in activity
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
