import { X } from "lucide-react";

/** The × at a dialog's top-right corner -- the one close control every modal shares, so leaving never means
 * hunting for a Cancel button at the bottom of a long form.
 *
 * It asks the dialog to cancel the same way Escape does (a `cancel` event), so whatever the dialog already does
 * on Escape -- close, ignore a bubbled file-picker cancel, refuse because a one-time secret is on screen -- is
 * exactly what the × does. Render it as the dialog's first child; it sticks to the corner while a long dialog
 * scrolls. `hidden` drops it for a stage that must not be left with a click (see ResetPasswordDialog). */
export default function ModalClose({ hidden = false }: { hidden?: boolean }) {
  if (hidden) return null;
  return (
    <button
      type="button"
      className="modal-close"
      aria-label="Close"
      title="Close (Esc)"
      // Not in the Tab order: a dialog opens with focus on its first focusable element, and that must be the first
      // field, not this button. Keyboard users have Esc and the Cancel button.
      tabIndex={-1}
      onClick={(e) => e.currentTarget.closest("dialog")?.dispatchEvent(new Event("cancel", { cancelable: true }))}
    >
      <X size={18} strokeWidth={2} aria-hidden="true" />
    </button>
  );
}
