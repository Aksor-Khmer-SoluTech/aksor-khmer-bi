import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

/** A large window over a list page for one item's details (a user, ...) -- room for wide content that an expanded
 * table row or a side panel squeezes. Escape or a click on the backdrop closes it.
 *
 * Deliberately not a <dialog>: the console's confirmations (ConfirmDialog...) are <dialog>s opened with showModal(),
 * which puts them in the top layer -- above this window, as they should be -- and this window ignores keys while one
 * is open. Rendered into <body>, so no transformed ancestor can shift its position. */
export default function DetailModal({
  title,
  subtitle,
  leading,
  badges,
  onClose,
  label,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** An avatar or icon before the title. */
  leading?: ReactNode;
  badges?: ReactNode;
  onClose: () => void;
  /** For screen readers: what the window shows, e.g. "User sokha". */
  label: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);

  // Focus moves into the window when it opens, and back where it was when it closes.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    return () => before?.focus?.();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (document.querySelector("dialog[open]")) return;
      const target = e.target as HTMLElement | null;
      const typing = !!target?.closest("input, textarea, select, [contenteditable='true']");
      if (e.key !== "Escape") return;
      e.preventDefault();
      if (typing) target?.blur();
      else onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const icon =
    "grid size-8 cursor-pointer place-items-center rounded-lg text-text-dim transition-colors hover:bg-bg-panel hover:text-text";

  return createPortal(
    <div className="detail-modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className="detail-modal" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}>
        <header className="detail-modal-header">
          {leading}
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="m-0 truncate font-display text-[1.2rem] font-semibold tracking-tight text-text">{title}</h2>
              {badges}
            </div>
            {subtitle && <div className="truncate text-[0.8rem] text-text-faint">{subtitle}</div>}
          </div>
          <button type="button" className={icon} onClick={onClose} title="Close (Esc)" aria-label="Close">
            <X size={17} />
          </button>
        </header>
        <div className="detail-modal-body">{children}</div>
      </div>
    </div>,
    document.body
  );
}
