import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** A menu at a point on screen -- a right-click, or under the "…" button that opened it. Rendered into <body>, so no
 * scrolling box, clipped cell or neighbouring card can cut it off or cover it; kept on screen; closed by a press
 * elsewhere, Esc, scrolling or resizing; ↑/↓ move between its items.
 *
 * In React it still sits inside whatever opened it, and React passes its events up to that: a click on "Delete"
 * would also open the card underneath, a press would start dragging it. So clicks, presses and keys stop here. */
export default function FloatingMenu({
  x,
  y,
  label,
  onClose,
  ignore,
  width = 200,
  children,
}: {
  x: number;
  y: number;
  label: string;
  onClose: () => void;
  /** The button that opened it: a press there is the button's own toggle, not "a press elsewhere". */
  ignore?: HTMLElement | null;
  width?: number;
  children: (close: () => void) => ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  // Flip in from the right / bottom edge when it wouldn't fit.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width: w, height: h } = el.getBoundingClientRect();
    setPos({
      left: Math.max(8, Math.min(x, window.innerWidth - w - 8)),
      top: Math.max(8, y + h > window.innerHeight - 8 ? y - h : y),
    });
    el.querySelector<HTMLElement>("[role=menuitem]")?.focus();
  }, [x, y]);

  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      if (ignore?.contains(e.target as Node)) return;
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    // Esc while focus is outside the menu (inside, onKeyDown below handles it).
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onClose);
    window.addEventListener("scroll", onClose, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onClose);
      window.removeEventListener("scroll", onClose, true);
    };
  }, [onClose, ignore]);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    e.stopPropagation();
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const items = [...(ref.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];
      if (!items.length) return;
      e.preventDefault();
      const at = items.indexOf(document.activeElement as HTMLElement);
      items[(at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    }
  }

  return createPortal(
    <div
      ref={ref}
      role="menu"
      aria-label={`${label} actions`}
      className="account-panel floating-menu"
      style={{ position: "fixed", left: pos.left, top: pos.top, right: "auto", width }}
      onContextMenu={(e) => e.preventDefault()}
      onClick={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={onKeyDown}
    >
      {children(onClose)}
    </div>,
    document.body,
  );
}
