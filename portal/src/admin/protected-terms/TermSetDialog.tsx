import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import TermsInput from "../../components/TermsInput";
import { useDialogRef } from "../../hooks";
import type { Organization, ProtectedTermSet } from "../../types";

import ModalClose from "../../components/ModalClose";
/** Create a term set, or edit / (read-only) view an existing one. Mount it
 * with a new `key` each time it opens (see ProtectedTermsPage). A
 * report author with only `report:manage` can look at a set to decide
 * whether to select it, but only `protected_terms:manage` can change it --
 * so the same dialog serves both, its fields locked when `canEdit` is off. */
export default function TermSetDialog({
  open,
  onClose,
  set,
  canEdit,
  organizations,
  defaultOrgId,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  /** null = creating a new set */
  set: ProtectedTermSet | null;
  canEdit: boolean;
  organizations: Organization[];
  defaultOrgId: string;
  onSaved: (saved: ProtectedTermSet, created: boolean) => void;
}) {
  // Initialised from props, not reset in an effect when the dialog opens:
  // the parent remounts this component (a fresh `key`) for every open, so
  // the fields are already right on the first render. An effect-driven
  // reset lands a task later and lets the dialog paint one frame of the
  // *previous* session's text -- another set's terms, flashing.
  const [name, setName] = useState(set?.name ?? "");
  const [description, setDescription] = useState(set?.description ?? "");
  const [orgId, setOrgId] = useState(set?.org_id ?? defaultOrgId);
  const [terms, setTerms] = useState<string[]>(set?.terms ?? []);
  const [excludeTerms, setExcludeTerms] = useState<string[]>(set?.exclude_terms ?? []);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const ref = useDialogRef(open);


  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canEdit) return;
    setPending(true);
    setError(null);
    const body = {
      name: name.trim(),
      description: description.trim() || null,
      terms,
      exclude_terms: excludeTerms,
    };
    try {
      const saved = set ? await api.protectedTerms.updateSet(set.id, body) : await api.protectedTerms.createSet(orgId, body);
      onSaved(saved, set === null);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the set");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal modal-wide" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">{set ? (canEdit ? "Edit protected term set" : set.name) : "New protected term set"}</h2>
      <p className="panel-subtitle">
        {canEdit
          ? "A list any report in the organization can select. Editing it later updates every report that uses it."
          : "You can see this set but not change it — that needs the “protected terms” permission."}
      </p>
      <form onSubmit={handleSubmit}>
        <div className="terms-dialog-head">
          <label>
            <span>Name</span>
            <input
              type="text"
              required
              maxLength={200}
              readOnly={!canEdit}
              placeholder="e.g. Official branch names"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          {set === null && organizations.length > 1 && (
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
          )}
        </div>
        <label>
          <span>Description</span>
          <input
            type="text"
            maxLength={200}
            readOnly={!canEdit}
            placeholder="Optional — what this list is for"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>

        <TermsInput
          label="Protect"
          hint="Enter adds a term; paste a list to add many."
          readOnly={!canEdit}
          terms={terms}
          onChange={setTerms}
        />
        <TermsInput
          label="Never protect"
          variant="exclude"
          hint="Optional. Wins over anything that protects the term."
          placeholder="Type a term to hand back to the normal word-breaker"
          readOnly={!canEdit}
          terms={excludeTerms}
          onChange={setExcludeTerms}
        />

        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            {canEdit ? "Cancel" : "Close"}
          </button>
          {canEdit && (
            <button type="submit" className="btn btn-primary" disabled={pending || !name.trim()}>
              {pending && <span className="spinner" />}
              {set ? "Save changes" : "Create set"}
            </button>
          )}
        </div>
      </form>
    </dialog>
  );
}
