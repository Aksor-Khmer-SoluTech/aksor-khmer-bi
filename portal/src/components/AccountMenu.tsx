import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { AuthInfo, User } from "../types";
import UserAvatar from "./UserAvatar";
import UserSettingsModal, { type SettingsTab } from "./UserSettingsModal";

/** Dropdown for the signed-in account — "Profile", "Preferences" and "Settings" all
 * open the same UserSettingsModal (Profile straight onto its Profile
 * tab, a quick shortcut to view/edit your own info; Settings onto
 * whichever tab you land on by default, covering Notifications,
 * Preferences, Access, and Active Sessions too), plus Sign out. Used to
 * hold separate Profile/Change password/Preferences items; folded into
 * one modal instead so every account-related setting lives behind one
 * door, with Profile kept as its own menu entry since that's the one
 * people expect to find fastest. "Request support" used to live here
 * too; moved to the footer (see Footer.tsx) since that's on screen at
 * all times, not tucked behind this menu. */
export default function AccountMenu({ auth }: { auth: AuthInfo }) {
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("profile");
  const [profile, setProfile] = useState<User | null>(null);
  const [profileChecked, setProfileChecked] = useState(false);
  // Null profile has two very different causes the UI must not conflate:
  // a break-glass login (expected 404, no row to fetch) vs. a real
  // failure (e.g. a database that hasn't run the latest migration --
  // /users/me 500s once app code expects a column that isn't there yet).
  // Only the latter belongs here; a 404 leaves this null and just falls
  // back to the break-glass copy in UserSettingsModal's sidebar.
  const [profileError, setProfileError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  function loadProfile() {
    setProfileError(null);
    api.users
      .me()
      .then((u) => {
        setProfile(u);
        setProfileError(null);
      })
      .catch((err) => {
        setProfile(null);
        if (!(err instanceof ApiError) || err.status !== 404) {
          setProfileError(err instanceof ApiError ? err.message : "Couldn't load your profile");
        }
      })
      .finally(() => setProfileChecked(true));
  }

  // Fetched once on mount (not lazily on dropdown open) since the
  // trigger button's own avatar needs it even before the menu is ever
  // opened.
  useEffect(() => {
    loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The built-in admin from the server's .env (PORTAL_USERNAME/PORTAL_PASSWORD) has no database row: /users/me
  // answers 404, so there's no profile, password, 2FA or sessions to show. Say so, and point at the fix, instead of
  // offering menu entries that land on an empty page.
  const systemAccount = profileChecked && profile === null && !profileError;
  const canCreateAccounts = auth.isSuperuser || auth.permissions.includes("user:manage");

  function openSettings(tab: SettingsTab) {
    setSettingsTab(tab);
    setSettingsOpen(true);
    setOpen(false);
  }

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

  return (
    <div className="account-menu" ref={rootRef}>
      <button type="button" className="account-trigger" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <UserAvatar profile={profile} username={auth.username} checked={profileChecked} />
        <span className="who-name">{auth.username}</span>
      </button>

      {open && (
        <div className="account-panel" role="menu">
          <div className="account-panel-header">
            <UserAvatar profile={profile} username={auth.username} checked={profileChecked} />
            <div>
              <div className="account-panel-name mono">{auth.username}</div>
              {systemAccount && <div className="account-panel-sub">Built-in admin account</div>}
            </div>
          </div>

          {systemAccount ? (
            <>
              <p className="account-panel-hint">
                This sign-in comes from the server's settings and has no profile, password or sessions. Create your own
                account and sign in with it for everyday use.
              </p>
              {canCreateAccounts && (
                <a className="account-item" href="#/admin/users" onClick={() => setOpen(false)}>
                  Create your own account
                </a>
              )}
              <button type="button" className="account-item" onClick={() => openSettings("preferences")}>
                Preferences
              </button>
            </>
          ) : (
            <>
              <button type="button" className="account-item" onClick={() => openSettings("profile")}>
                Profile
              </button>

              {/* Straight onto the Preferences tab (theme, report preview, scrollbars). */}
              <button type="button" className="account-item" onClick={() => openSettings("preferences")}>
                Preferences
              </button>

              <button type="button" className="account-item" onClick={() => openSettings("profile")}>
                Settings
              </button>
            </>
          )}

          <div className="account-divider" />

          <button
            type="button"
            className="account-item account-item-danger"
            onClick={async () => {
              // Revokes the session on the server and clears the cookie, then back to the sign-in screen.
              await api.logout();
              window.location.reload();
            }}
          >
            Sign out
          </button>
        </div>
      )}

      <UserSettingsModal
        open={settingsOpen}
        initialTab={settingsTab}
        profile={profile}
        profileChecked={profileChecked}
        profileError={profileError}
        onRetryProfile={loadProfile}
        onProfileUpdated={setProfile}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}
