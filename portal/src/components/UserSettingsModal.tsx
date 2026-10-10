import { useState, type ReactElement } from "react";
import { AccessIcon, AuthLogIcon, BellIcon, PreferencesIcon, ProfileIcon, SessionsIcon } from "../admin/icons";
import { onDialogCancel, useDialogRef } from "../hooks";
import type { User } from "../types";
import SettingsAccessPanel from "./SettingsAccessPanel";
import SettingsActiveSessionsPanel from "./SettingsActiveSessionsPanel";
import SettingsAuthLogPanel from "./SettingsAuthLogPanel";
import SettingsNotificationsPanel from "./SettingsNotificationsPanel";
import SettingsPreferencesPanel from "./SettingsPreferencesPanel";
import SettingsProfilePanel from "./SettingsProfilePanel";
import { LinesSkeleton } from "./Skeletons";

export type SettingsTab = "profile" | "notifications" | "preferences" | "access" | "sessions" | "authLog";

// Active Sessions and Authentication log used to be one crowded tab;
// split to match GitLab's own Access sub-nav (Password and
// authentication / Active sessions / Authentication log as separate
// entries) rather than bundling "where am I signed in" with "what's
// been attempted over time."
const NAV: { id: SettingsTab; label: string; icon: () => ReactElement; needsProfile: boolean }[] = [
  { id: "profile", label: "Profile", icon: ProfileIcon, needsProfile: true },
  { id: "notifications", label: "Notifications", icon: BellIcon, needsProfile: true },
  { id: "preferences", label: "Preferences", icon: PreferencesIcon, needsProfile: false },
  { id: "access", label: "Access", icon: AccessIcon, needsProfile: true },
  { id: "sessions", label: "Active Sessions", icon: SessionsIcon, needsProfile: true },
  { id: "authLog", label: "Authentication Log", icon: AuthLogIcon, needsProfile: true },
];

/** One entry point for everything account-related — replaces the old
 * ProfileDialog (Profile/Change password tabs) and the standalone
 * PreferencesPage route, plus adds the Notifications and Active Sessions
 * tabs. Opened from AccountMenu's Profile/Settings items.
 *
 * `profile` is owned by AccountMenu (not fetched here) — it also needs
 * it to render the trigger button's own avatar even while this modal is
 * closed, and keeping one copy means an avatar/name change made in here
 * is instantly reflected there too, with no separate refetch to go stale.
 *
 * A break-glass login (PORTAL_USERNAME/PORTAL_PASSWORD) has no database
 * row behind it — /users/me 404s — so every tab except Preferences
 * (pure client-side, see ../preferences.ts) needs `profile` to have
 * resolved to a real user first; the nav below hides them until then. */
export default function UserSettingsModal({
  open,
  initialTab = "profile",
  profile,
  profileChecked,
  profileError,
  onRetryProfile,
  onProfileUpdated,
  onClose,
}: {
  open: boolean;
  initialTab?: SettingsTab;
  profile: User | null;
  profileChecked: boolean;
  profileError: string | null;
  onRetryProfile: () => void;
  onProfileUpdated: (u: User) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<SettingsTab>(initialTab);

  const ref = useDialogRef(open, () => {
    setTab(initialTab);
  });

  const items = NAV.filter((item) => !item.needsProfile || profile !== null);
  const activeTab = items.some((item) => item.id === tab) ? tab : "preferences";

  return (
    <dialog
      ref={ref}
      onCancel={onDialogCancel(onClose)}
      // `open:flex`, not a bare `flex` -- an unconditional `display`
      // utility on the dialog itself would out-rank the UA stylesheet's
      // `dialog:not([open]) { display: none }` (author origin always
      // beats user-agent origin, regardless of layers/specificity),
      // which would leave the dialog visibly rendered even after
      // .close() clears its `open` attribute.
      className="modal open:flex h-[min(900px,94vh)] w-[96vw] max-w-[1320px] flex-col overflow-hidden p-0 max-md:h-full max-md:max-h-full max-md:w-full max-md:rounded-none"
    >
      <div className="flex min-h-0 flex-1 max-md:flex-col">
        <nav className="flex w-60 flex-none flex-col gap-0.5 overflow-y-auto border-r border-border-soft bg-bg-panel p-3 max-md:w-full max-md:flex-row max-md:flex-wrap max-md:border-r-0 max-md:border-b max-md:gap-1">
          <div className="px-2 pt-1 pb-3 font-display text-[1.05rem] font-semibold text-text max-md:hidden">Settings</div>
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`flex w-full cursor-pointer appearance-none items-center gap-2.5 rounded-sm border-none px-3 py-[9px] text-left text-[0.86rem] font-medium max-md:w-auto ${
                activeTab === item.id
                  ? "bg-accent-soft text-accent-strong"
                  : "bg-transparent text-text-dim hover:bg-bg-panel-hover hover:text-text"
              }`}
              onClick={() => setTab(item.id)}
            >
              <item.icon />
              <span className="truncate">{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex flex-none items-center justify-between border-b border-border-soft px-6 py-4">
            <h2 className="m-0 font-display text-[1.1rem] font-semibold text-text">
              {items.find((i) => i.id === activeTab)?.label ?? "Settings"}
            </h2>
            <button type="button" className="btn btn-ghost btn-sm icon-only" onClick={onClose} aria-label="Close settings">
              ✕
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {!profileChecked ? (
              <LinesSkeleton count={3} />
            ) : profileError ? (
              <div className="alert alert-error max-w-md">
                <p className="m-0 font-medium">Couldn't load your profile</p>
                <p className="mt-1 mb-2 text-[0.82rem]">{profileError}</p>
                <p className="mt-1 mb-2 text-[0.82rem]">
                  If this is a self-hosted instance you just updated, the database may need its latest migration
                  (<code className="mono">alembic upgrade head</code>) before Profile/Notifications/Access/Sessions
                  will load.
                </p>
                <button type="button" className="btn btn-sm" onClick={onRetryProfile}>
                  Retry
                </button>
              </div>
            ) : (
              <>
                {activeTab === "profile" && profile && (
                  <SettingsProfilePanel user={profile} onUpdated={onProfileUpdated} />
                )}
                {activeTab === "notifications" && profile && (
                  <SettingsNotificationsPanel user={profile} onUpdated={onProfileUpdated} />
                )}
                {profile === null && (
                  <div className="alert alert-warning mb-5 max-w-2xl">
                    <p className="m-0 font-medium">You're signed in with the built-in admin account</p>
                    <p className="mt-1 mb-0 text-[0.84rem] leading-relaxed">
                      It comes from the server's settings (<code className="mono">PORTAL_USERNAME</code> in{" "}
                      <code className="mono">.env</code>) and is meant for the first sign-in and emergencies, so it has
                      no profile, password, two-factor or session settings — only Preferences. Create your own account
                      in{" "}
                      <a href="#/admin/users" onClick={onClose}>
                        Manage → Users
                      </a>{" "}
                      with the administrator role, then sign in with it to get all of these.
                    </p>
                  </div>
                )}
                {activeTab === "preferences" && <SettingsPreferencesPanel accountBacked={profile !== null} />}
                {activeTab === "access" && profile && (
                  <SettingsAccessPanel user={profile} onUpdated={onProfileUpdated} />
                )}
                {activeTab === "sessions" && profile && (
                  <SettingsActiveSessionsPanel onGoToAccess={() => setTab("access")} />
                )}
                {activeTab === "authLog" && profile && <SettingsAuthLogPanel />}
              </>
            )}
          </div>
        </div>
      </div>
    </dialog>
  );
}
