import { api } from "./api";

/** One shared, in-memory copy of the signed-in user's avatar image, so the
 * top-bar circle, the account menu's header and the Profile tab's larger
 * preview (three separate UserAvatar instances, two of which mount only when
 * a menu/tab opens) don't each download the same blob -- and so React
 * StrictMode's dev-only double effect run doesn't either. The blob needs an
 * explicit fetch anyway (the access token is a header this app attaches, not
 * something a plain `<img src>` can carry), then becomes an object URL that
 * every instance points at.
 *
 * Only one user is ever signed in per page load (sign-out reloads the
 * page), so there's no per-user key -- `invalidateAvatar()` is the one
 * refresh path, called after an upload/remove. */

let version = 0;
let url: string | null = null;
let pending: Promise<string | null> | null = null;
const listeners = new Set<() => void>();

export function subscribeAvatar(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Bumps on every invalidation, so a mounted UserAvatar can re-run its load
 * even when `avatar_content_type` didn't change (a new PNG over an old one). */
export function avatarVersion(): number {
  return version;
}

/** The already-fetched object URL, or null if nothing's cached yet -- lets a
 * freshly mounted avatar paint the photo on its first render instead of
 * flashing the placeholder for a frame. */
export function peekAvatarUrl(): string | null {
  return url;
}

/** Resolves to the object URL (fetching once, however many callers ask at
 * the same time), or null if the account has no photo / the fetch failed --
 * a failure isn't cached, so the next mount simply tries again. */
export function loadAvatarUrl(): Promise<string | null> {
  if (url) return Promise.resolve(url);
  if (!pending) {
    const generation = version;
    pending = api.users
      .avatarBlob()
      .then((blob) => {
        const objectUrl = URL.createObjectURL(blob);
        if (generation !== version) {
          // Invalidated while this was in flight -- the answer is stale.
          URL.revokeObjectURL(objectUrl);
          return null;
        }
        url = objectUrl;
        return objectUrl;
      })
      .catch(() => null)
      .finally(() => {
        if (generation === version) pending = null;
      });
  }
  return pending;
}

/** Drop the cached image after an upload or removal and tell every mounted
 * avatar to reload. */
export function invalidateAvatar(): void {
  if (url) URL.revokeObjectURL(url);
  url = null;
  pending = null;
  version += 1;
  listeners.forEach((listener) => listener());
}
