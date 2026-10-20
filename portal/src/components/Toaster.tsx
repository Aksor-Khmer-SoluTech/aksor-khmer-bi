import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { dismissToast, subscribeToasts, type Toast } from "../notify";
import ErrorDetails from "./ErrorDetails";

// How long a toast stays: errors long enough to read a sentence and its reference, the rest briefly.
// Hovering or focusing one holds it.
const LIFETIME_MS = { error: 12_000, success: 4_000, info: 6_000 } as const;

function ToastItem({ toast }: { toast: Toast }) {
  const [held, setHeld] = useState(false);
  // Clicked into (details opened, text being copied): stays until dismissed.
  const [pinned, setPinned] = useState(false);
  useEffect(() => {
    if (held || pinned) return;
    const timer = window.setTimeout(() => dismissToast(toast.id), LIFETIME_MS[toast.kind]);
    return () => window.clearTimeout(timer);
  }, [held, pinned, toast.id, toast.kind]);

  return (
    <div
      className={`toast toast-${toast.kind}`}
      role={toast.kind === "error" ? "alert" : "status"}
      onMouseEnter={() => setHeld(true)}
      onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
      onClickCapture={() => setPinned(true)}
    >
      <div className="toast-body">
        <strong className="toast-title">{toast.title}</strong>
        {toast.message && <p className="toast-message">{toast.message}</p>}
        {toast.info && <ErrorDetails info={toast.info} />}
      </div>
      <button type="button" className="toast-close" aria-label="Dismiss" onClick={() => dismissToast(toast.id)}>
        ×
      </button>
    </div>
  );
}

/** Where the toasts must live to be clickable: an open modal <dialog> makes everything outside it inert, so while
 * one is open they are rendered inside the topmost one (still a popover, so still in the corner, above it). */
function useToastHost(): HTMLElement {
  const [host, setHost] = useState<HTMLElement>(document.body);
  useEffect(() => {
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const modals = [...document.querySelectorAll<HTMLDialogElement>("dialog[open]")].filter((d) => d.matches(":modal"));
        setHost(modals[modals.length - 1] ?? document.body);
      });
    };
    const observer = new MutationObserver(update);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["open"] });
    update();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);
  return host;
}

/** Rendered once at the root. A popover so it sits in the top layer, above an open modal <dialog> -- a failure
 * while one is open would otherwise toast behind its backdrop. */
export default function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const host = useToastHost();

  useEffect(() => subscribeToasts(setToasts), []);

  useLayoutEffect(() => {
    const el = ref.current as (HTMLDivElement & { showPopover?: () => void; hidePopover?: () => void }) | null;
    if (!el?.showPopover || !el.hidePopover) return;
    try {
      // Re-showing puts it back on top of anything opened into the top layer since (a dialog opened after it).
      if (el.matches(":popover-open")) el.hidePopover();
      if (toasts.length > 0) el.showPopover();
    } catch {
      /* a browser without popover support keeps the fixed-position fallback */
    }
  }, [toasts, host]);

  return createPortal(
    <div ref={ref} className="toaster" popover="manual" aria-live="polite">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} />
      ))}
    </div>,
    host
  );
}
