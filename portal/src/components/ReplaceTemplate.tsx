import { useState, type FormEvent } from "react";
import { TriangleAlert, Upload } from "lucide-react";
import { api, ApiError } from "../api";
import { FORMATS_BY_EXT, versionName, type ReportChangelog, type ReportMeta } from "../types";
import FileDropzone from "./FileDropzone";
import { PlaceholderDiff } from "./HistoryTab";

// Not backend-enforced (the note has no length cap) -- a UX ceiling, like the
// name/description limits on the same page.
const NOTE_MAX = 300;

// Mirrors the server's rule (report_store.VERSION_LABEL_RE) so a bad label is caught before the upload.
const LABEL_RE = /^[0-9A-Za-z][0-9A-Za-z._+-]{0,31}$/;

/** The label to offer for the next upload: a patch bump of a dotted number
 * (1.0 → 1.0.1, 1.0.1 → 1.0.2), or 1.0 when there's nothing numeric to bump. */
function suggestLabel(current: string | null): string {
  if (current && /^\d+(\.\d+)*$/.test(current)) {
    const parts = current.split(".").map(Number);
    if (parts.length < 3) return `${current}.1`;
    parts[parts.length - 1] += 1;
    return parts.join(".");
  }
  return "1.0";
}

// What PUT .../file accepts. An .html replacement is checked like a new html template, against the
// resources this report already has mapped -- one that uses an unmapped resource() is refused with that reason.
const ACCEPT = ".docx,.xlsx,.html,.htm";
type Ext = "docx" | "xlsx" | "html";
const extOf = (name: string): Ext | null => {
  const lower = name.toLowerCase();
  return lower.endsWith(".docx") ? "docx" : lower.endsWith(".xlsx") ? "xlsx" : /\.html?$/.test(lower) ? "html" : null;
};

/** Replace a template's file: choose it, say what changed, confirm. Picking a
 * file only *stages* it -- nothing is uploaded until "Upload new version" -- because
 * the file becomes the live template at once, and the person should get to check
 * it's the right one, describe it (the note is the one thing the change log
 * can't work out for itself), and see if it swaps the template's type first.
 * Afterwards it says what happened, including which placeholders came or went. */
export default function ReplaceTemplate({
  report,
  changelog,
  onReplaced,
  onOpenHistory,
}: {
  report: ReportMeta;
  changelog: ReportChangelog | null;
  onReplaced: (r: ReportMeta) => void;
  onOpenHistory: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [label, setLabel] = useState<string | null>(null); // null = untouched, follow the suggestion
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<number | null>(null);
  const [uploadedName, setUploadedName] = useState("");
  const [previousName, setPreviousName] = useState("");

  const suggested = suggestLabel(report.version_label);
  const labelValue = label ?? suggested;
  const labelTrimmed = labelValue.trim().replace(/^v(?=\d)/i, "");
  const labelInvalid = labelTrimmed !== "" && !LABEL_RE.test(labelTrimmed);
  const newExt = file ? extOf(file.name) : null;
  const changesType = newExt !== null && newExt !== report.template_ext;

  function stage(f: File) {
    setUploaded(null);
    if (extOf(f.name) === null) {
      setError("Only a .docx, .xlsx or .html file can replace this template.");
      return;
    }
    if (f.size === 0) {
      setError("That file is empty.");
      return;
    }
    setError(null);
    setFile(f);
  }

  function reset() {
    setFile(null);
    setNote("");
    setLabel(null);
    setError(null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file || pending || labelInvalid) return;
    setError(null);
    setPending(true);
    try {
      const updated = await api.replaceFile(report.report_id, file, note, labelTrimmed);
      onReplaced(updated);
      setUploaded(updated.version);
      setUploadedName(versionName(updated.version, updated.version_label));
      setPreviousName(versionName(report.version, report.version_label));
      reset();
    } catch (err) {
      // Stay staged, so a rejected upload can be retried or swapped without starting over.
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setPending(false);
    }
  }

  // The change log is refetched after an upload (TemplateDetail), so this appears a
  // moment after the confirmation itself.
  const result = uploaded === null ? null : changelog?.entries.find((e) => e.kind === "version" && e.version.version === uploaded);
  const resultVersion = result && result.kind === "version" ? result.version : null;

  return (
    <div className="mb-6">
      {uploaded !== null && (
        <div className="alert alert-success" role="status">
          <strong>Uploaded as {uploadedName}.</strong> {previousName} is kept and can still be downloaded.{" "}
          <button type="button" className="link-btn" onClick={onOpenHistory}>
            View in History
          </button>
          {resultVersion &&
            (resultVersion.identical_to_previous ? (
              <div className="mt-2 text-[0.8rem]">Same file as {previousName} — nothing changed.</div>
            ) : (
              <div className="mt-2">
                <PlaceholderDiff v={resultVersion} />
              </div>
            ))}
        </div>
      )}

      <form onSubmit={submit}>
        <FileDropzone
          compact
          file={file}
          onFile={stage}
          onClear={reset}
          onReject={setError}
          accept={ACCEPT}
          exts={["docx", "xlsx"]}
          idleTitle="Drag & drop the new file here"
          disabled={pending}
        />

        {error && (
          <p className="alert alert-error" role="alert" style={{ marginTop: 12, marginBottom: 0 }}>
            {error}
          </p>
        )}

        {file && (
          <div className="mt-3.5">
            {changesType && newExt && (
              <div className="mb-3.5 flex items-start gap-2.5 rounded-sm border border-highlight/40 bg-highlight-soft px-3 py-2.5 text-[0.82rem] text-text">
                <TriangleAlert size={16} className="mt-0.5 shrink-0 text-highlight" aria-hidden />
                <span>
                  <strong>This changes the template from .{report.template_ext} to .{newExt}.</strong> It will produce{" "}
                  <span className="font-mono">{FORMATS_BY_EXT[newExt].join(", ")}</span> instead of{" "}
                  <span className="font-mono">{FORMATS_BY_EXT[report.template_ext].join(", ")}</span> — anything that asks for a format
                  the new file can't produce will fail.
                </span>
              </div>
            )}

            <label>
              <span className="field-label-row">
                <span>Version</span>
                <span className="text-[0.76rem] text-text-faint">Currently {versionName(report.version, report.version_label)}</span>
              </span>
              <input
                type="text"
                className="font-mono"
                maxLength={33}
                value={labelValue}
                disabled={pending}
                placeholder={suggested}
                aria-invalid={labelInvalid}
                onChange={(e) => setLabel(e.target.value)}
              />
              {/* field-hint's default margin-top (-8px) assumes it follows a whole
                  </label> block, whose own 14px bottom margin it's clawing back into --
                  here it sits inside this label, right after the input with no such
                  margin to claw into, so left alone it overlaps the input's own
                  bottom border (see .conn-name-hint for the same fix elsewhere). */}
              <span className={`field-hint${labelInvalid ? " text-danger" : ""}`} style={{ marginTop: 6 }}>
                {labelInvalid
                  ? "Use letters, digits and . - _ + only, up to 32 characters."
                  : labelTrimmed === ""
                    ? "Left blank, it will be numbered automatically."
                    : "Your own numbering, e.g. 1.0.1. Must differ from earlier versions of this template."}
              </span>
            </label>

            <label>
              <span className="field-label-row">
                <span>What changed? (optional)</span>
                <span className={`char-counter${note.length >= NOTE_MAX ? " char-counter-limit" : ""}`}>
                  {note.length}/{NOTE_MAX}
                </span>
              </span>
              <input
                type="text"
                maxLength={NOTE_MAX}
                value={note}
                disabled={pending}
                placeholder="e.g. Added the branch column, fixed the footer"
                onChange={(e) => setNote(e.target.value)}
              />
            </label>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button type="submit" className="btn btn-primary" disabled={pending || labelInvalid}>
                {pending ? <span className="spinner" aria-hidden /> : <Upload size={15} aria-hidden />}
                {pending ? "Uploading…" : "Upload new version"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={reset} disabled={pending}>
                Cancel
              </button>
              <span className="text-[0.76rem] text-text-faint">{versionName(report.version, report.version_label)} stays in History.</span>
            </div>
          </div>
        )}
      </form>
    </div>
  );
}
