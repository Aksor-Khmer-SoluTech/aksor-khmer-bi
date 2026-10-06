import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import { useDialogRef } from "../../hooks";
import type { Organization } from "../../types";

import ModalClose from "../../components/ModalClose";
export default function OrgFormDialog({
  open,
  onClose,
  onCreated,
  organizations,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (org: Organization) => void;
  organizations: Organization[];
}) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [parentOrgId, setParentOrgId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const ref = useDialogRef(open, () => {
    setId("");
    setName("");
    setParentOrgId("");
    setError(null);
  });

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const org = await api.organizations.create({ id, name, parent_org_id: parentOrgId || null });
      onCreated(org);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the organization");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">New organization</h2>
      <p className="panel-subtitle">Seeds the standard role catalog automatically.</p>
      <form onSubmit={handleSubmit}>
        <label>
          <span>Id (slug)</span>
          <input
            type="text"
            required
            pattern="[a-z0-9][a-z0-9-]*"
            placeholder="e.g. acme"
            value={id}
            onChange={(e) => setId(e.target.value)}
          />
        </label>
        <label>
          <span>Name</span>
          <input type="text" required value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          <span>Parent organization</span>
          <select value={parentOrgId} onChange={(e) => setParentOrgId(e.target.value)}>
            <option value="">None (top-level)</option>
            {organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            Create organization
          </button>
        </div>
      </form>
    </dialog>
  );
}
