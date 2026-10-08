/** Keeps `[data-tip]` tooltips (CSS-only pills, see styles/pages.css) on screen. The pill is centred over its
 * control, so one at the edge of the window ran off it. On hover or focus this measures the pill, nudges it
 * back inside the viewport with `--tip-shift`, and drops it below the control when there's no room above. */
const MARGIN = 8;
const canvas = document.createElement("canvas").getContext("2d");

function place(el: HTMLElement) {
  const text = el.getAttribute("data-tip");
  if (!text) return;
  const style = getComputedStyle(el, "::after");
  let width = text.length * 7 + 18;
  if (canvas) {
    canvas.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    width = canvas.measureText(text).width + parseFloat(style.paddingLeft || "9") + parseFloat(style.paddingRight || "9");
  }
  const rect = el.getBoundingClientRect();
  const centre = rect.left + rect.width / 2;
  const viewport = document.documentElement.clientWidth;
  let shift = 0;
  if (centre - width / 2 < MARGIN) shift = MARGIN - (centre - width / 2);
  else if (centre + width / 2 > viewport - MARGIN) shift = viewport - MARGIN - (centre + width / 2);
  el.style.setProperty("--tip-shift", `${Math.round(shift)}px`);
  el.toggleAttribute("data-tip-below", rect.top < 44);
}

export function keepTooltipsOnScreen() {
  const handler = (event: Event) => {
    const el = (event.target as Element | null)?.closest?.("[data-tip]");
    if (el instanceof HTMLElement) place(el);
  };
  document.addEventListener("pointerover", handler, { passive: true });
  document.addEventListener("focusin", handler);
}
