import { useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { invalidateAvatar } from "../avatarStore";
import type { User } from "../types";
import UserAvatar from "./UserAvatar";

/** Settings modal — Profile tab: an avatar photo, plus view/edit the
 * account's own display name and email. Username stays read-only (it's
 * the login identifier, changing it is an admin operation on
 * /users/{id}, not a self-service one — see UserFormDialog). */
export default function SettingsProfilePanel({ user, onUpdated }: { user: User; onUpdated: (u: User) => void }) {
  const [email, setEmail] = useState(user.email ?? "");
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await api.users.updateMe({ email: email || null, display_name: displayName || null });
      onUpdated(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  async function handleAvatarFile(file: File) {
    setAvatarBusy(true);
    setAvatarError(null);
    try {
      const updated = await api.users.uploadAvatar(file);
      invalidateAvatar();
      onUpdated(updated);
    } catch (err) {
      setAvatarError(err instanceof ApiError ? err.message : "Couldn't upload photo");
    } finally {
      setAvatarBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function removeAvatar() {
    setAvatarBusy(true);
    setAvatarError(null);
    try {
      const updated = await api.users.deleteAvatar();
      invalidateAvatar();
      onUpdated(updated);
    } catch (err) {
      setAvatarError(err instanceof ApiError ? err.message : "Couldn't remove photo");
    } finally {
      setAvatarBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="stack max-w-5xl">
      <div className="mb-1 flex items-center gap-4">
        <UserAvatar profile={user} username={user.username} size={64} />
        <div className="flex flex-col gap-1.5">
          <div className="flex gap-2">
            <button
              type="button"
              className="btn btn-sm"
              disabled={avatarBusy}
              onClick={() => fileInputRef.current?.click()}
            >
              {avatarBusy && <span className="spinner" />}
              {user.avatar_content_type ? "Change photo" : "Upload photo"}
            </button>
            {user.avatar_content_type && (
              <button type="button" className="btn btn-sm btn-danger" disabled={avatarBusy} onClick={removeAvatar}>
                Remove
              </button>
            )}
          </div>
          <span className="text-[0.74rem] text-text-faint">PNG or JPEG, up to 5 MB. Resized automatically.</span>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleAvatarFile(file);
          }}
        />
      </div>
      {avatarError && <p className="alert alert-error">{avatarError}</p>}

      <label className="max-w-sm">
        <span>Username</span>
        <input type="text" value={user.username} disabled className="mono" />
      </label>
      <div className="row">
        <label>
          <span>Email</span>
          <input type="text" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </label>
        <label>
          <span>Display name</span>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="How your name shows up around the console"
          />
        </label>
      </div>
      {error && <p className="alert alert-error">{error}</p>}
      {saved && <p className="alert alert-success">Saved.</p>}
      <div className="dialog-actions justify-start">
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving && <span className="spinner" />}
          Save changes
        </button>
      </div>
    </form>
  );
}
