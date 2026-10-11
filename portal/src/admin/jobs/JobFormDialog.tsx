import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import { useDialogRef } from "../../hooks";
import type { Job, Organization } from "../../types";

import ModalClose from "../../components/ModalClose";
import JobFields, { draftToBody, newDraft, type JobDraft } from "./JobFields";

export default function JobFormDialog({
  open,
  onClose,
  onCreated,
  organizations,
  defaultOrgId,
  isSuperuser,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (job: Job) => void;
  organizations: Organization[];
  defaultOrgId: string;
  isSuperuser: boolean;
}) {
  const [orgId, setOrgId] = useState(defaultOrgId);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [draft, setDraft] = useState<JobDraft>(newDraft);
  // Remounts the fields on each open, so the schedule picker re-reads its fresh expression.
  const [generation, setGeneration] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const ref = useDialogRef(open, () => {
    setOrgId(defaultOrgId);
    setName("");
    setDescription("");
    setIsEnabled(true);
    setDraft(newDraft());
    setGeneration((g) => g + 1);
    setError(null);
  });

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body = draftToBody(draft);
    if ("error" in body) {
      setError(body.error);
      return;
    }
    setPending(true);
    try {
      const job = await api.jobs.create(orgId, {
        name,
        description: description || null,
        job_type: draft.jobType,
        is_enabled: isEnabled,
        ...body,
      });
      onCreated(job);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the job");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal modal-wide" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">New job</h2>
      <p className="panel-subtitle">Runs on its schedule — or any time from its panel, or the API.</p>
      <form onSubmit={handleSubmit} className="mt-4">
        <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
          <label>
            <span>
              Name <span className="required-mark" aria-hidden="true">*</span>
            </span>
            <input type="text" required maxLength={200} value={name} placeholder="Daily sales to finance" onChange={(e) => setName(e.target.value)} />
          </label>
          {isSuperuser ? (
            <label>
              <span>Organization</span>
              <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                {organizations.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <span className="hidden sm:block" />
          )}
          <label className="sm:col-span-2">
            <span>
              Description <span className="run-field-optional">(optional)</span>
            </span>
            <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
        </div>

        <JobFields key={generation} draft={draft} onChange={setDraft} canChangeType />

        <label className="checkbox-label">
          <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} /> Turn it on now (otherwise it waits until
          you enable it)
        </label>

        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            Create job
          </button>
        </div>
      </form>
    </dialog>
  );
}
