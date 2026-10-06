import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import { useDialogRef } from "../../hooks";
import type { Organization, Role } from "../../types";

import ModalClose from "../../components/ModalClose";
export default function RoleFormDialog({
  open,
  onClose,
  onCreated,
  organizations,
  defaultOrgId,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (role: Role) => void;
  organizations: Organization[];
  defaultOrgId: string;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [orgId, setOrgId] = useState(defaultOrgId);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const ref = useDialogRef(open, () => {
    setName("");
    setDescription("");
    setOrgId(defaultOrgId);
    setError(null);
  });

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const role = await api.roles.create({ org_id: orgId, name, description: description || null });
      onCreated(role);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the role");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">New role</h2>
      <p className="panel-subtitle">Custom, per-organization — permissions are assigned after creation.</p>
      <form onSubmit={handleSubmit}>
        <label>
          <span>Name</span>
          <input
            type="text"
            required
            placeholder="e.g. ROLE_AUDITOR"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          <span>Description</span>
          <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label>
          <span>Organization</span>
          {organizations.length > 1 ? (
            <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              {organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          ) : (
            // Only one organization exists (or this account can only see its own) -- nothing
            // to choose, but still shown so it's clear where this role is being created.
            <input type="text" value={organizations[0]?.name ?? orgId} readOnly aria-readonly="true" />
          )}
        </label>
        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            Create role
          </button>
        </div>
      </form>
    </dialog>
  );
}
