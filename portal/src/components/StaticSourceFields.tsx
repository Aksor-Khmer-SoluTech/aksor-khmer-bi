import { FlaskConical } from "lucide-react";
import { parseStaticData } from "../dataConfig";

const EXAMPLE = {
  organization: "Sample Organization",
  report_date: "2026-01-31",
  rows: [
    { name: "Phnom Penh", total: 1250000 },
    { name: "Siem Reap", total: 830500 },
  ],
};

/** Fixed sample data for a report that isn't connected to anything yet -- enough to build a
 * template and show it to people before a real source exists. The same JSON object is what a
 * REST API or a query would return, so switching source later needs no template change. */
export default function StaticSourceFields({ text, onChange, error }: { text: string; onChange: (text: string) => void; error: string | null }) {
  const parsed = parseStaticData(text);

  return (
    <div className="static-source">
      <div className="static-source-head">
        <span className="field-label">Sample data (JSON object)</span>
        <div className="static-source-actions">
          <button type="button" className="btn btn-sm" onClick={() => onChange(JSON.stringify(EXAMPLE, null, 2))}>
            <FlaskConical size={13} aria-hidden="true" />
            Insert example
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={parsed.value === null}
            onClick={() => parsed.value && onChange(JSON.stringify(parsed.value, null, 2))}
          >
            Format
          </button>
        </div>
      </div>
      <textarea
        className="mono-input static-source-text"
        rows={16}
        spellCheck={false}
        aria-label="Sample data"
        aria-invalid={error !== null}
        placeholder={'{\n  "rows": [ { "name": "…", "total": 0 } ]\n}'}
        value={text}
        onChange={(e) => onChange(e.target.value)}
      />
      {error && <p className="alert alert-error">{error}</p>}
      <p className="field-hint">
        Every run renders the template with exactly this — filters don't change it. Keys become the template's fields, so a template written
        against sample data keeps working when you switch to a REST API or a database that returns the same shape. Not for confidential
        data: anyone who can edit this report can read it.
      </p>
    </div>
  );
}
