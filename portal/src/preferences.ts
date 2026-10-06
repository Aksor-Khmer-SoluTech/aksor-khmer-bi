// The Preferences tab's settings. All of them are saved to the account
// through the generic settings store (api/app/db/user_settings.py, client
// side in userSettings.tsx) under the *_CODE constants below, so they
// follow the user to any browser.
//
// Mode/accent additionally keep a localStorage copy: they're applied as
// data-theme/data-accent on <html>, which tokens.css keys its dark-mode
// and accent color-mix() formulas off of, and a blocking inline script in
// index.html has to apply them synchronously before first paint (see its
// comment there) -- an async server fetch can't do that without flashing
// the default theme. The server copy wins once it loads; see
// applyServerTheme.
export type ThemeMode = "light" | "dark" | "auto";
export type ThemeAccent = "default" | "indigo" | "terracotta" | "forest" | "teal" | "plum" | "slate";

export const THEME_MODE_CODE = "theme_mode";
export const THEME_ACCENT_CODE = "theme_accent";
export const PREVIEW_LAYOUT_CODE = "report_preview_layout";
export const REPORT_SCROLLBARS_CODE = "report_scrollbars";

const MODE_KEY = "portal_theme_mode";
const ACCENT_KEY = "portal_theme_accent";

export const MODES: { id: ThemeMode; label: string }[] = [
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
  { id: "auto", label: "Auto" },
];

export const ACCENTS: { id: ThemeAccent; label: string }[] = [
  // `id` stays "default" (it's the literal data-accent attribute value
  // and the fallback when nothing is set -- see tokens.css) even though
  // its color is now this console's own blue, not a neutral graphite.
  { id: "default", label: "Blue" },
  { id: "indigo", label: "Indigo" },
  { id: "terracotta", label: "Terracotta" },
  { id: "forest", label: "Forest" },
  { id: "teal", label: "Teal" },
  { id: "plum", label: "Plum" },
  { id: "slate", label: "Slate" },
];

function parseMode(v: unknown): ThemeMode | null {
  return v === "light" || v === "dark" || v === "auto" ? v : null;
}

function parseAccent(v: unknown): ThemeAccent | null {
  return ACCENTS.some((a) => a.id === v) ? (v as ThemeAccent) : null;
}

export function getMode(): ThemeMode {
  return parseMode(localStorage.getItem(MODE_KEY)) ?? "auto";
}

export function getAccent(): ThemeAccent {
  return parseAccent(localStorage.getItem(ACCENT_KEY)) ?? "default";
}

function applyTheme(mode: ThemeMode, accent: ThemeAccent): void {
  const root = document.documentElement;
  if (mode === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", mode);
  root.setAttribute("data-accent", accent);
}

export function setMode(mode: ThemeMode): void {
  localStorage.setItem(MODE_KEY, mode);
  applyTheme(mode, getAccent());
}

export function setAccent(accent: ThemeAccent): void {
  localStorage.setItem(ACCENT_KEY, accent);
  applyTheme(getMode(), accent);
}

/** Applies whatever mode/accent the account has saved (the map from
 * GET /users/me/settings), writing through to localStorage so the
 * pre-paint script in index.html picks it up next load too. A code the
 * account never saved (or holds an unrecognised value for) leaves this
 * browser's own choice alone. Deliberately doesn't write back to the
 * server -- it only ever reflects the server's own value. */
export function applyServerTheme(settings: Record<string, unknown>): void {
  const mode = parseMode(settings[THEME_MODE_CODE]);
  if (mode && mode !== getMode()) setMode(mode);
  const accent = parseAccent(settings[THEME_ACCENT_CODE]);
  if (accent && accent !== getAccent()) setAccent(accent);
}

// Where the Preview tab's rendered report (ReportViewer, in a <dialog>) appears from —
// read by TemplateDetail.tsx each time it opens one.
export type PreviewLayout = "right" | "left" | "center";

export const PREVIEW_LAYOUTS: { id: PreviewLayout; label: string; description: string }[] = [
  { id: "right", label: "Slide from right", description: "Docks to the right edge, full height." },
  { id: "left", label: "Slide from left", description: "Docks to the left edge, full height." },
  { id: "center", label: "Center screen", description: "Opens as a large modal that nearly fills the window." },
];

/** The stored value is untrusted (the settings store accepts any JSON), so
 * anything unrecognised -- including "never saved" -- falls back to the
 * default rather than leaking through as a broken layout. */
export function parsePreviewLayout(v: unknown): PreviewLayout {
  return PREVIEW_LAYOUTS.some((l) => l.id === v) ? (v as PreviewLayout) : "right";
}

// How the report viewer's scrollbars behave. Most desktop systems (macOS by default) draw thin overlay
// scrollbars that vanish until you scroll, which makes a long or wide report hard to read "where am I"-wise;
// "always" draws a classic bar that stays on screen. Read by ReportViewer.tsx.
export type ReportScrollbars = "auto" | "always";

export const REPORT_SCROLLBAR_OPTIONS: { id: ReportScrollbars; label: string; description: string }[] = [
  { id: "auto", label: "Auto-hide", description: "Follow your system: on macOS, bars fade away until you scroll." },
  { id: "always", label: "Always visible", description: "Keep the scrollbars on screen so you can see how far a report goes." },
];

/** The stored value is untrusted (the settings store accepts any JSON); anything unrecognised -- including
 * "never saved" -- is the system default. */
export function parseReportScrollbars(v: unknown): ReportScrollbars {
  return v === "always" ? "always" : "auto";
}
