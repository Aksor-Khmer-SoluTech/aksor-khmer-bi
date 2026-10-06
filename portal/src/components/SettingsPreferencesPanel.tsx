import { useState } from "react";
import { ApiError } from "../api";
import {
  ACCENTS,
  MODES,
  PREVIEW_LAYOUTS,
  REPORT_SCROLLBARS_CODE,
  REPORT_SCROLLBAR_OPTIONS,
  PREVIEW_LAYOUT_CODE,
  THEME_ACCENT_CODE,
  THEME_MODE_CODE,
  getAccent,
  getMode,
  parsePreviewLayout,
  parseReportScrollbars,
  type ReportScrollbars,
  setAccent as persistAccent,
  setMode as persistMode,
  type PreviewLayout,
  type ThemeAccent,
  type ThemeMode,
} from "../preferences";
import { useUserSettings } from "../userSettings";

/** Each swatch is a real miniature of the app chrome (topbar + sidebar +
 * a primary button), not a flat color chip — so picking an accent shows
 * what it actually does rather than asking the user to imagine it. It's
 * self-contained: `data-theme="light" data-accent={id}` scopes the real
 * CSS tokens to just this preview, independent of the page's own current
 * mode/accent, so every swatch always previews true to itself. */
function AccentPreview({ id }: { id: ThemeAccent }) {
  return (
    <span className="accent-preview" data-theme="light" data-accent={id}>
      <span className="accent-preview-topbar">
        <span className="accent-preview-dot" />
        <span className="accent-preview-bar" style={{ width: 30 }} />
      </span>
      <span className="accent-preview-body">
        <span className="accent-preview-sidebar" />
        <span className="accent-preview-content">
          <span className="accent-preview-line" style={{ width: "72%" }} />
          <span className="accent-preview-line" style={{ width: "48%" }} />
          <span className="accent-preview-btn" />
        </span>
      </span>
    </span>
  );
}

/** A miniature "browser window" with a shaded panel standing in for the
 * report preview drawer, parked just off-frame in whichever direction
 * that option opens from (or a near-full one that fades up leaving a slim
 * margin, for "center") — and animated into place on hover, so picking a
 * layout shows what it does
 * instead of asking the user to imagine it (same idea as AccentPreview
 * above, applied to motion instead of color). */
function PreviewLayoutPreview({ id }: { id: PreviewLayout }) {
  return (
    <span className={`layout-preview layout-preview-${id}`}>
      <span className="layout-preview-page">
        <span className="layout-preview-line" style={{ width: "68%" }} />
        <span className="layout-preview-line" style={{ width: "42%" }} />
        <span className="layout-preview-line" style={{ width: "54%" }} />
      </span>
      <span className="layout-preview-panel">
        <span className="layout-preview-panel-bar" />
      </span>
    </span>
  );
}

/** Settings modal — Preferences tab: mode, accent, and report-preview
 * layout. Each choice is saved to the account through the generic
 * settings store (see ../userSettings.tsx and ../preferences.ts), so it
 * follows the user to any browser; mode/accent are also applied to this
 * browser immediately, since the theme can't wait on a round-trip.
 *
 * Still the one tab that renders for a break-glass login with no
 * database row behind it (`accountBacked` false) -- the choices just
 * can't be saved anywhere beyond this browser/session. Used to be its
 * own top-level page/route; moved in here so every account-related
 * setting lives behind one entry point. */
export default function SettingsPreferencesPanel({ accountBacked }: { accountBacked: boolean }) {
  const { get, set } = useUserSettings();
  const [mode, setModeState] = useState<ThemeMode>(getMode);
  const [accent, setAccentState] = useState<ThemeAccent>(getAccent);
  const previewLayout = parsePreviewLayout(get(PREVIEW_LAYOUT_CODE));
  const scrollbars = parseReportScrollbars(get(REPORT_SCROLLBARS_CODE));
  const [saveError, setSaveError] = useState<string | null>(null);

  function save(code: string, value: string) {
    setSaveError(null);
    set(code, value).catch((err) =>
      setSaveError(`Couldn't save that to your account: ${err instanceof ApiError ? err.message : "the server didn't respond"}`)
    );
  }

  function chooseMode(next: ThemeMode) {
    persistMode(next);
    setModeState(next);
    save(THEME_MODE_CODE, next);
  }

  function chooseAccent(next: ThemeAccent) {
    persistAccent(next);
    setAccentState(next);
    save(THEME_ACCENT_CODE, next);
  }

  function choosePreviewLayout(next: PreviewLayout) {
    save(PREVIEW_LAYOUT_CODE, next);
  }

  function chooseScrollbars(next: ReportScrollbars) {
    save(REPORT_SCROLLBARS_CODE, next);
  }

  return (
    <div className="max-w-5xl">
      <p className="mt-0 mb-5 text-[0.85rem] text-text-faint">
        {accountBacked
          ? "Saved to your account — these follow you to any browser you sign in from."
          : "This sign-in has no account behind it, so these apply to this browser only."}
      </p>
      {saveError && <p className="alert alert-error mb-5">{saveError}</p>}

      <div className="panel">
        <h3 className="panel-title">Mode</h3>
        <p className="panel-subtitle">Choose a color mode, or follow your system.</p>
        <div className="segmented" role="group" aria-label="Color mode">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`segmented-btn ${mode === m.id ? "active" : ""}`}
              onClick={() => chooseMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">Theme</h3>
        <p className="panel-subtitle">Pick the accent color used for buttons, links, and active states.</p>
        <div className="accent-grid">
          {ACCENTS.map((a) => (
            <button
              key={a.id}
              type="button"
              className={`accent-card ${accent === a.id ? "selected" : ""}`}
              onClick={() => chooseAccent(a.id)}
              aria-pressed={accent === a.id}
            >
              <AccentPreview id={a.id} />
              <span className="accent-card-label">
                <span className="accent-card-radio" aria-hidden="true" />
                {a.label}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">Report preview</h3>
        <p className="panel-subtitle">Choose how the Preview tab opens a rendered report — hover an option to see it.</p>
        <div className="accent-grid">
          {PREVIEW_LAYOUTS.map((l) => (
            <button
              key={l.id}
              type="button"
              className={`accent-card ${previewLayout === l.id ? "selected" : ""}`}
              onClick={() => choosePreviewLayout(l.id)}
              aria-pressed={previewLayout === l.id}
            >
              <PreviewLayoutPreview id={l.id} />
              <span className="accent-card-label">
                <span className="accent-card-radio" aria-hidden="true" />
                {l.label}
              </span>
              <span className="mt-[-4px] text-[0.76rem] text-text-faint">{l.description}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">Report scrollbars</h3>
        <p className="panel-subtitle">
          How scrollbars behave when you read a report. Some systems hide them until you scroll; keep them visible to always see how far a
          report goes.
        </p>
        <div className="scrollbar-pref">
          <div>
            <div className="segmented" role="group" aria-label="Report scrollbars">
              {REPORT_SCROLLBAR_OPTIONS.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  className={`segmented-btn ${scrollbars === o.id ? "active" : ""}`}
                  onClick={() => chooseScrollbars(o.id)}
                  aria-pressed={scrollbars === o.id}
                >
                  {o.label}
                </button>
              ))}
            </div>
            <p className="mt-3 mb-0 text-[0.78rem] text-text-faint">{REPORT_SCROLLBAR_OPTIONS.find((o) => o.id === scrollbars)?.description}</p>
            <p className="mt-2 mb-0 text-[0.74rem] text-text-faint">Firefox on macOS follows the system setting (System Settings → Appearance → Show scroll bars).</p>
          </div>
          <div className={`scrollbar-sample${scrollbars === "always" ? " scrollbars-always" : ""}`} tabIndex={0} aria-label="Scrollbar preview">
            <div className="scrollbar-sample-page">
              {Array.from({ length: 14 }, (_, i) => (
                <p key={i} style={{ width: `${78 - ((i * 13) % 40)}%` }} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
