import { CODE_MAX, checkCode } from "../reportCode";

/** The code input, shared by the Register dialog and a template's Overview.
 * A code is an optional, stable alternative to the random report ID -- the
 * same in every environment -- so it's what an integration or an <iframe> should
 * hold. This field says what's allowed as you type, shows the addresses the code
 * unlocks, and warns before a change or a removal that would break callers.
 *
 * Deliberately never fills itself in: codes are claimed globally and kept by their
 * organization for good, so taking one has to be a choice. `suggestion` is
 * offered as a click, not applied. */
export default function ReportCodeField({
  value,
  onChange,
  saved = null,
  suggestion = "",
  serverError = null,
}: {
  value: string;
  onChange: (v: string) => void;
  /** The code the report has now, if any -- to warn when editing it away. */
  saved?: string | null;
  suggestion?: string;
  /** What the server said (taken, invalid), shown against the field. */
  serverError?: string | null;
}) {
  const code = value.trim();
  const problem = checkCode(value);
  const shown = problem ?? serverError;
  const changed = saved !== null && code !== saved;
  const canSuggest = suggestion !== "" && code === "" && suggestion !== saved;

  return (
    <div className="field-block">
      {/* Not the `<label><span>…</span><input/></label>` shape the other fields use: the
          help text below has to sit *outside* the label (whose 14px bottom margin would
          otherwise separate the input from it), so the label and its spacing are set here. */}
      <div className="field-label-row mb-1.5">
        <label htmlFor="report-code-input" className="mb-0 font-medium text-text-dim">
          Code <span className="mb-0 inline font-normal text-text-faint">(optional)</span>
        </label>
        <span className={`char-counter${value.length >= CODE_MAX ? " char-counter-limit" : ""}`}>
          {value.length}/{CODE_MAX}
        </span>
      </div>
      <input
        id="report-code-input"
        type="text"
        className="font-mono"
        value={value}
        maxLength={CODE_MAX}
        placeholder="e.g. revenue-comparison"
        spellCheck={false}
        autoCapitalize="off"
        autoComplete="off"
        aria-invalid={shown ? true : undefined}
        aria-describedby="report-code-help"
        onChange={(e) => onChange(e.target.value.toLowerCase())}
      />
      <div id="report-code-help" className="mt-1.5 text-[0.78rem] leading-relaxed">
        {shown ? (
          <p className="m-0 text-danger-strong" role="alert">
            {shown}
          </p>
        ) : code !== "" ? (
          <p className="m-0 text-text-faint">
            Use it anywhere the ID goes: <span className="font-mono text-text-dim">/api/v1/reports/{code}/render</span> and{" "}
            <span className="font-mono text-text-dim">#/embed/{code}</span>
          </p>
        ) : (
          <p className="m-0 text-text-faint">
            A short code to use instead of the ID in API calls and embed links. Unlike the ID, it can be the same in every
            environment.{" "}
            {canSuggest && (
              <button type="button" className="link-btn" onClick={() => onChange(suggestion)}>
                Use “{suggestion}”
              </button>
            )}
          </p>
        )}
        {!shown && changed && saved && (
          <p className="mb-0 mt-1.5 text-text">
            <strong>{code === "" ? "Removing" : "Changing"} this stops “{saved}” working</strong> for anything that calls the report by
            it. The ID keeps working.
          </p>
        )}
      </div>
    </div>
  );
}
