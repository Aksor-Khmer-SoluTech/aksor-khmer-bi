import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { api, ApiError } from "../api";
import { useDialogRef } from "../hooks";
import type { Folder, Grant, Role } from "../types";

import ModalClose from "./ModalClose";
/** Manage which roles can view/manage one Resources folder (and,
 * transitively, everything nested under it — see app/rbac.py's
 * `has_folder_access`). Role grants only, for this first pass — the
 * backend (`api.grants.folders`) already supports granting a specific
 * user too, same as report grants do, but this dialog doesn't expose
 * that yet; the common case this feature exists for is "let this whole
 * role into this folder," not one-off per-user access. */
export default function FolderGrantsDialog({ open, folderId, onClose }: { open: boolean; folderId: string; onClose: () => void }) {
  const [folder, setFolder] = useState<Folder | null>(null);
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [grantRoleId, setGrantRoleId] = useState("");
  const [grantLevel, setGrantLevel] = useState<"view" | "manage">("view");
  const [grantExpiry, setGrantExpiry] = useState("");

  const ref = useDialogRef(open, () => {
    setError(null);
    setGrantRoleId("");
    setGrantLevel("view");
    setGrantExpiry("");
  });

  function load() {
    api.folders.list().then((all) => setFolder(all.find((f) => f.id === folderId) ?? null));
    api.roles.list().then(setRoles);
    api.grants.folders.list(folderId).then(setGrants);
  }

  useEffect(() => {
    if (open) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load is a
    // fresh closure every render but only depends on folderId, which is
    // stable for the dialog's lifetime.
  }, [open, folderId]);

  function toExpiresAt(dateInput: string): string | null {
    return dateInput ? `${dateInput}T23:59:59Z` : null;
  }

  async function grantRole() {
    if (!grantRoleId) return;
    setError(null);
    try {
      await api.grants.folders.grant("role", grantRoleId, folderId, grantLevel, toExpiresAt(grantExpiry));
      setGrantRoleId("");
      setGrantExpiry("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't grant access");
    }
  }

  async function revoke(grantId: string) {
    setError(null);
    try {
      await api.grants.folders.revoke(grantId);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't revoke");
    }
  }

  const roleName = (id: string) => roles?.find((r) => r.id === id)?.name ?? id;
  const activeGrants = grants?.filter((g) => g.is_active) ?? [];

  return (
    <dialog ref={ref} className="modal folder-grants-modal" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">Manage access{folder ? ` — ${folder.name}` : ""}</h2>
      <p className="muted" style={{ fontSize: "0.85rem", marginTop: -4 }}>
        A role granted access here also reaches every subfolder nested underneath, automatically.
      </p>

      {error && <p className="alert alert-error">{error}</p>}

      <div className="grant-block">
        {activeGrants.length === 0 && <p className="muted">No folder-specific access granted — visible only via global permissions.</p>}
        {activeGrants.map((g) => (
          <div key={g.id} className="grant-row">
            <span className="mono">{g.subject_type === "role" ? roleName(g.subject_id ?? "") : g.subject_id}</span>
            <span className={`badge badge-${g.permission_level === "manage" ? "enabled" : "local"}`}>{g.permission_level}</span>
            <span className="muted">{g.expires_at ? `expires ${new Date(g.expires_at).toLocaleDateString()}` : "no expiry"}</span>
            <button type="button" className="link-btn" onClick={() => revoke(g.id)}>
              revoke
            </button>
          </div>
        ))}

        <div className="row grant-form">
          <select value={grantRoleId} onChange={(e) => setGrantRoleId(e.target.value)}>
            <option value="">Grant a role…</option>
            {roles?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
          <select value={grantLevel} onChange={(e) => setGrantLevel(e.target.value as "view" | "manage")}>
            <option value="view">View</option>
            <option value="manage">Manage</option>
          </select>
          <input type="date" value={grantExpiry} onChange={(e) => setGrantExpiry(e.target.value)} title="Optional expiry date" />
          <button type="button" className="btn btn-primary" onClick={grantRole} disabled={!grantRoleId}>
            <Plus size={14} /> Grant
          </button>
        </div>
      </div>

      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </dialog>
  );
}
