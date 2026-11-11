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
  confirmText,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel?: string;
  /** When set, the confirm button stays disabled until this exact text is typed (GitHub-style), for deletes that
   * can't be undone. */
  confirmText?: string;
  /** May return a promise: the dialog then waits on it, and if it rejects shows the reason here and stays open,
   * so a failed delete is never silent. */
  onConfirm: () => void | Promise<unknown>;
  onCancel: () => void;
}) {
  const ref = useDialogRef(open);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; info: FailureInfo } | null>(null);
  const [typed, setTyped] = useState("");
  const matches = !confirmText || typed === confirmText;

  useEffect(() => {
    if (open) {
      setError(null);
      setBusy(false);
      setTyped("");
    }
  }, [open]);

  async function confirm() {
    if (!matches) return;
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
      {confirmText && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void confirm();
          }}
        >
          <label className="confirm-type">
            <span className="confirm-type-label">
              To confirm, type <strong>{confirmText}</strong> below:
            </span>
            <input
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              autoFocus
              aria-label={`Type ${confirmText} to confirm`}
            />
          </label>
        </form>
      )}
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
        <button type="button" className="btn btn-danger" onClick={confirm} disabled={busy || !matches}>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
