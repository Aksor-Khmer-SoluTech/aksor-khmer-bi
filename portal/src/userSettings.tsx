import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import { applyServerTheme } from "./preferences";

interface UserSettings {
  /** The raw value this account saved under `code`, or undefined if it
   * never did. The store accepts any JSON, so callers validate what they
   * read (see preferences.ts's parse* helpers) and fall back to their own
   * default. */
  get: (code: string) => unknown;
  /** Saves `value` under `code`. Reflected in `get` immediately; if the
   * server rejects it, the previous value is restored and the error is
   * rethrown so the caller can say so. A break-glass login has no account
   * row to save to (404) -- that isn't a failure, the value just lasts for
   * this session. */
  set: (code: string, value: unknown) => Promise<void>;
}

const UserSettingsContext = createContext<UserSettings | null>(null);

/** Holds the signed-in account's saved settings (GET /users/me/settings --
 * see api/app/db/user_settings.py). Mounted inside App.tsx's signed-in
 * shell, so it fetches once per sign-in and is discarded on sign-out. */
export function UserSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  // `set` reads the pre-change value to roll back to; a ref keeps that
  // read current without making `set` (and so every consumer) re-created
  // on every settings change.
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  useEffect(() => {
    let cancelled = false;
    api.users.settings
      .list()
      .then((saved) => {
        if (cancelled) return;
        // A choice made while this was still in flight wins over the saved one.
        setSettings((current) => ({ ...saved, ...current }));
        applyServerTheme(saved);
      })
      .catch(() => {
        // A break-glass login (404, no account row) or a network blip:
        // there's nothing to load, so everything stays at its default.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const get = useCallback((code: string) => settings[code], [settings]);

  const set = useCallback(async (code: string, value: unknown) => {
    const previous = settingsRef.current[code];
    setSettings((current) => ({ ...current, [code]: value }));
    try {
      await api.users.settings.set(code, value);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return;
      // Only undo our own write -- if a later change to this code has
      // already replaced it, that one is the state worth keeping.
      setSettings((current) => {
        if (current[code] !== value) return current;
        const next = { ...current };
        if (previous === undefined) delete next[code];
        else next[code] = previous;
        return next;
      });
      throw err;
    }
  }, []);

  const value = useMemo(() => ({ get, set }), [get, set]);
  return <UserSettingsContext.Provider value={value}>{children}</UserSettingsContext.Provider>;
}

export function useUserSettings(): UserSettings {
  const ctx = useContext(UserSettingsContext);
  if (!ctx) throw new Error("useUserSettings must be used inside <UserSettingsProvider>");
  return ctx;
}

/** For components that also render outside the signed-in shell (the embedded viewer is anonymous): the
 * account's settings when there are any, else null -- callers fall back to their defaults. */
export function useOptionalUserSettings(): UserSettings | null {
  return useContext(UserSettingsContext);
}
