import { useEffect, useState, useSyncExternalStore } from "react";
import { avatarVersion, loadAvatarUrl, peekAvatarUrl, subscribeAvatar } from "../avatarStore";
import type { User } from "../types";

/** The `.avatar` circle (AccountMenu's trigger + panel header, and the
 * Profile tab's larger preview via `size`) — shows the uploaded photo
 * once `profile.avatar_content_type` is set, else falls back to the
 * username's first initial exactly as before. The image itself comes from
 * avatarStore.ts's shared cache (fetched once for however many avatar
 * circles are on screen, since the access token is an explicit header this app
 * attaches, not something a plain `<img src>` could carry).
 *
 * `checked` covers the caller's own "have we even loaded `profile` yet"
 * window (AccountMenu's `/users/me` on mount) -- before that resolves,
 * `profile` is null exactly like a genuine no-photo account, so without
 * this the initial letter would flash first and get replaced once the
 * photo arrives. Defaults to true for callers (SettingsProfilePanel) that
 * only ever render once their own `profile` is already resolved. */
export default function UserAvatar({
  profile,
  username,
  size,
  checked = true,
}: {
  profile: User | null;
  username: string;
  size?: number;
  checked?: boolean;
}) {
  const contentType = profile?.avatar_content_type ?? null;
  // Bumps after an upload/remove even when the content type stayed the same
  // (see avatarStore.ts), so the load below re-runs.
  const version = useSyncExternalStore(subscribeAvatar, avatarVersion);
  const loadKey = `${contentType}:${version}`;
  const [failedKey, setFailedKey] = useState<string | null>(null);
  // Only here to re-render once the shared store has the image.
  const [, setTick] = useState(0);

  // Read straight from the shared store on every render rather than mirrored
  // into state, so the "is a photo on its way" answer is right on the very
  // render the profile arrives -- a mirrored flag only flips inside an
  // effect, one frame late, which let the initial letter flash between the
  // shimmer and the photo.
  const photo = contentType ? peekAvatarUrl() : null;
  const pending = contentType !== null && photo === null && failedKey !== loadKey;
  const showSkeleton = !checked || pending;

  useEffect(() => {
    if (!contentType || peekAvatarUrl()) return;
    let cancelled = false;
    loadAvatarUrl().then((objectUrl) => {
      if (cancelled) return;
      if (objectUrl) setTick((n) => n + 1);
      else setFailedKey(loadKey);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadKey is derived from these two
  }, [contentType, version]);

  return (
    <span
      className={`avatar${showSkeleton ? " avatar-skel" : photo ? " avatar-photo" : ""}`}
      aria-hidden="true"
      style={size ? { width: size, height: size, fontSize: size * 0.36 } : undefined}
    >
      {!showSkeleton &&
        (photo ? (
          <img src={photo} alt="" className="avatar-img" />
        ) : (
          <span className="avatar-initial">{username.charAt(0).toUpperCase()}</span>
        ))}
    </span>
  );
}
