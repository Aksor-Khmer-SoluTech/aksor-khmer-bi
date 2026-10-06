import { useCallback, useState } from "react";

/** The reports a person has starred, kept in this browser (per account, so a shared machine doesn't mix
 * them). Not synced between devices -- it's a convenience, not a record. */
const keyFor = (username: string) => `portal_favorite_reports:${username}`;

function read(username: string): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(keyFor(username)) ?? "[]");
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export function useFavoriteReports(username: string): { favorites: string[]; isFavorite: (id: string) => boolean; toggle: (id: string) => void } {
  const [favorites, setFavorites] = useState<string[]>(() => read(username));

  const toggle = useCallback(
    (id: string) => {
      setFavorites((current) => {
        const next = current.includes(id) ? current.filter((f) => f !== id) : [id, ...current];
        try {
          localStorage.setItem(keyFor(username), JSON.stringify(next));
        } catch {
          // best-effort only -- the star just won't be remembered
        }
        return next;
      });
    },
    [username],
  );

  return { favorites, isFavorite: (id) => favorites.includes(id), toggle };
}
