import { useEffect, useState } from "react";
import { useDialogRef } from "../hooks";
import { type FailureInfo } from "../errorLog";
import { failureInfo } from "../notify";
import ErrorDetails from "./ErrorDetails";

import ModalClose from "./ModalClose";
export default function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Delete",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel?: string;
  /** May return a promise: the dialog then waits on it, and if it rejects shows the reason here and stays open,
   * so a failed delete is never silent. */
  onConfirm: () => void | Promise<unknown>;
  onCancel: () => void;
}) {
  const ref = useDialogRef(open);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; info: FailureInfo } | null>(null);

  useEffect(() => {
    if (open) {
      setError(null);
      setBusy(false);
    }
  }, [open]);

  async function confirm() {
    setError(null);
    const result = onConfirm();
    if (!result || typeof (result as Promise<unknown>).then !== "function") return;
    setBusy(true);
    try {
      await result;
    } catch (err) {
      setError({ message: err instanceof Error ? err.message : "It didn't work. Try again.", info: failureInfo(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog ref={ref} className="modal" onCancel={onCancel}>
      <ModalClose />
      <h2 className="panel-title">{title}</h2>
      <p className="muted" style={{ fontSize: "0.88rem" }}>
        {body}
      </p>
      {error && (
        <div className="alert alert-error dialog-error" role="alert">
          {error.message}
          <ErrorDetails info={error.info} />
        </div>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn btn-danger" onClick={confirm} disabled={busy}>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
