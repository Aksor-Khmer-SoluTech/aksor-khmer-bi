import { useDialogRef } from "../hooks";

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
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useDialogRef(open);

  return (
    <dialog ref={ref} className="modal" onCancel={onCancel}>
      <ModalClose />
      <h2 className="panel-title">{title}</h2>
      <p className="muted" style={{ fontSize: "0.88rem" }}>
        {body}
      </p>
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn btn-danger" onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
