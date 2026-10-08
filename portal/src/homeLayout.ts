import { useCallback, useState } from "react";

/** The order of the Home page's cards, kept in this browser per account (like the starred reports -- see
 * favorites.ts), so a shared machine doesn't mix people's layouts. Anything unknown in storage is dropped and
 * any card the stored order doesn't mention (a card added in a later release) goes to the end. */
const keyFor = (username: string) => `portal_home_layout:${username}`;

function normalise(stored: unknown, defaults: readonly string[]): string[] {
  const known = new Set(defaults);
  const kept = Array.isArray(stored) ? stored.filter((id): id is string => typeof id === "string" && known.has(id)) : [];
  const unique = [...new Set(kept)];
  return [...unique, ...defaults.filter((id) => !unique.includes(id))];
}

function read(username: string, defaults: readonly string[]): string[] {
  try {
    return normalise(JSON.parse(localStorage.getItem(keyFor(username)) ?? "null"), defaults);
  } catch {
    return [...defaults];
  }
}

export function useHomeLayout(username: string, defaults: readonly string[]) {
  const [order, setOrder] = useState<string[]>(() => read(username, defaults));

  const save = useCallback(
    (next: string[]) => {
      setOrder(next);
      try {
        localStorage.setItem(keyFor(username), JSON.stringify(next));
      } catch {
        // best-effort only -- the layout just won't be remembered
      }
    },
    [username],
  );

  const reset = useCallback(() => {
    setOrder([...defaults]);
    try {
      localStorage.removeItem(keyFor(username));
    } catch {
      // nothing stored to clear
    }
  }, [username, defaults]);

  return { order, save, reset, customised: order.some((id, i) => id !== defaults[i]) };
}
