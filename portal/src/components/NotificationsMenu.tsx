import { useEffect, useRef, useState } from "react";
import { BellIcon } from "../admin/icons";
import { api } from "../api";
import type { AuthEvent } from "../types";

/** Notifications bell in TopBar. Its one real, working feed: new-device
 * sign-in alerts from app/auth_events.py, gated by the account's own
 * Settings > Notifications toggle (see SettingsNotificationsPanel.tsx) --
 * this console still has no email/push channel, so unlike everything
 * else here, there's nothing to fake beyond that one in-app alert. Opening
 * the panel acknowledges whatever's showing (api.users.ackNotifications),
 * same "seen as soon as opened" convention as most notification bells. */
export default function NotificationsMenu() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AuthEvent[]>([]);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.users.notifications().then(setItems).catch(() => setItems([]));
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

  function toggle() {
    setOpen((o) => {
      const next = !o;
      if (next && items.length > 0) api.users.ackNotifications().catch(() => {});
      return next;
    });
  }

  return (
    <div className="notif-menu" ref={rootRef}>
      <button
        type="button"
        className={`btn btn-ghost btn-sm icon-only relative ${open ? "active" : ""}`}
        onClick={toggle}
        title="Notifications"
        aria-expanded={open}
      >
        <BellIcon />
        {items.length > 0 && (
          <span className="absolute top-1 right-1 h-[7px] w-[7px] rounded-full bg-danger" aria-hidden="true" />
        )}
      </button>

      {open && (
        <div className="notif-panel" role="menu">
          <div className="notif-panel-header">Notifications</div>
          {items.length === 0 ? (
            <div className="notif-empty">
              <BellIcon />
              <p>You're all caught up</p>
              <span className="muted">New sign-ins from a device we haven't seen before will show up here.</span>
            </div>
          ) : (
            <div className="stack p-3">
              {items.map((e) => (
                <div key={e.id} className="rounded-sm border border-border-soft px-3 py-2.5">
                  <div className="text-[0.85rem] font-medium text-text">New sign-in detected</div>
                  <div className="mt-0.5 text-[0.78rem] text-text-faint">
                    {e.browser} on {e.os} · <span className="mono">{e.ip_address ?? "unknown IP"}</span>
                  </div>
                  <div className="mt-0.5 text-[0.74rem] text-text-faint">{new Date(e.created_at).toLocaleString()}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
