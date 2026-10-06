import type { DataConfigDraft } from "../dataConfig";

/** The Save row both data-config tabs end with. Saving writes the whole draft
 * (see dataConfig.ts), so when the *other* tab has unsaved edits it says so
 * rather than saving them silently. */
export default function DataConfigSaveBar({ draft, here }: { draft: DataConfigDraft; here: "parameters" | "source" }) {
  const dirty = draft.parametersDirty || draft.sourceDirty;
  const otherDirty = here === "parameters" ? draft.sourceDirty : draft.parametersDirty;
  const other = here === "parameters" ? "Data source" : "Parameters";

  return (
    <div className="data-config-actions-block">
      <div className="data-config-actions">
        <button type="button" className="btn btn-primary" onClick={draft.save} disabled={draft.saving || !dirty}>
          {draft.saving && <span className="spinner" />}
          Save changes
        </button>
        {draft.saved && !dirty && <span className="alert alert-success data-config-saved">Saved.</span>}
        {dirty && !draft.saving && (
          <span className="muted data-config-unsaved">
            Unsaved changes{otherDirty ? ` — including on the ${other} tab, which this saves too` : ""}
          </span>
        )}
      </div>
      {draft.saveError && <p className="alert alert-error data-config-save-error">{draft.saveError}</p>}
    </div>
  );
}
