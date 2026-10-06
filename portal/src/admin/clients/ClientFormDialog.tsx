import { useMemo, useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import ReportPicker from "../../components/ReportPicker";
import { useDialogRef } from "../../hooks";
import type { ApiClientWithSecret, Organization, ReportMeta } from "../../types";

import ModalClose from "../../components/ModalClose";
/** "ERP Sync" -> "erp-sync": the slug shape the server accepts (lowercase letters, digits, single hyphens). */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

export default function ClientFormDialog({
  open,
  onClose,
  onCreated,
  organizations,
  defaultOrgId,
  reports,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (result: ApiClientWithSecret) => void;
  organizations: Organization[];
  defaultOrgId: string;
  reports: ReportMeta[];
}) {
  const [name, setName] = useState("");
  const [clientId, setClientId] = useState("");
  const [idEdited, setIdEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [orgId, setOrgId] = useState(defaultOrgId);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const ref = useDialogRef(open, () => {
    setName("");
    setClientId("");
    setIdEdited(false);
    setDescription("");
    setOrgId(defaultOrgId);
    setSelected(new Set());
    setError(null);
  });

  const available = useMemo(
    () => reports.filter((r) => (r.org_id ?? "root") === orgId).sort((a, b) => a.name.localeCompare(b.name)),
    [reports, orgId]
  );

  function changeName(value: string) {
    setName(value);
    if (!idEdited) setClientId(slugify(value));
  }

  function toggle(reportId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(reportId)) next.delete(reportId);
      else next.add(reportId);
      return next;
    });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await api.clients.create({
        org_id: orgId,
        client_id: clientId,
        name,
        description: description || null,
        report_ids: Array.from(selected),
      });
      onCreated(result);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the client");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal client-dialog" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">New API client</h2>
      <p className="panel-subtitle">An app that runs reports with a client ID and secret instead of a user login.</p>
      <form onSubmit={handleSubmit}>
        <div className="client-dialog-grid">
          {/* Left: what the client itself is. Right: what it may run -- its own
              column so a long report list has real vertical room, rather than
              being squeezed below four stacked fields (see .client-dialog-grid). */}
          <div className="client-dialog-fields">
            <label>
              <span>Name</span>
              <input type="text" required maxLength={120} placeholder="e.g. ERP Sync" value={name} onChange={(e) => changeName(e.target.value)} />
            </label>
            <label>
              <span>Client ID</span>
              <input
                type="text"
                required
                minLength={3}
                maxLength={64}
                pattern="[a-z0-9]+(-[a-z0-9]+)*"
                title="Lowercase letters, digits and single hyphens"
                placeholder="erp-sync"
                value={clientId}
                onChange={(e) => {
                  setIdEdited(true);
                  setClientId(e.target.value);
                }}
              />
            </label>
            <label>
              <span>Description</span>
              <textarea
                rows={3}
                maxLength={500}
                placeholder="What it is, and who owns it"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label>
              <span>Organization</span>
              {organizations.length > 1 ? (
                <select
                  value={orgId}
                  onChange={(e) => {
                    setOrgId(e.target.value);
                    setSelected(new Set());
                  }}
                >
                  {organizations.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              ) : (
                // Only one organization exists (or this account can only see its own) -- nothing
                // to choose, but still shown so it's clear where this client is being created.
                <input type="text" value={organizations[0]?.name ?? orgId} readOnly aria-readonly="true" />
              )}
            </label>
          </div>

          <div className="client-dialog-reports">
            <span className="field-label">Reports it may run</span>
            <ReportPicker reports={available} selected={selected} onToggle={toggle} onSelectMany={(ids) => setSelected(new Set(ids))} />
          </div>
        </div>

        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            Create client
          </button>
        </div>
      </form>
    </dialog>
  );
}
