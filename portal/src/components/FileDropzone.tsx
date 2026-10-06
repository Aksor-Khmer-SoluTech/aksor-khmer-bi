import { useState, type ChangeEvent, type DragEvent, type MouseEvent } from "react";
import { FileText, UploadCloud, X } from "lucide-react";
import { fmtBytes } from "./AuditParts";

/** A drag-and-drop-or-click file picker for one file, on the app's shared
 * `.dropzone` look (the same one RegisterDialog uses). It only *chooses* a
 * file: what's acceptable, and what happens next, are the caller's call
 * (onFile / onReject) -- so picking a file never uploads anything by itself.
 *
 * The native input is visually hidden but stays keyboard-reachable; the zone
 * draws the focus ring for it (`.dropzone:has(input:focus-visible)`). */
export default function FileDropzone({
  file,
  onFile,
  onClear,
  onReject,
  accept,
  exts,
  idleTitle = "Drag & drop your file here",
  activeTitle = "Drop it to use this file",
  disabled = false,
  compact = false,
}: {
  file: File | null;
  onFile: (file: File) => void;
  onClear: () => void;
  /** Called for a drop the zone itself can't take (more than one file). */
  onReject?: (message: string) => void;
  /** The input's `accept` string, e.g. ".docx,.xlsx". */
  accept: string;
  /** Extension badges shown while empty, e.g. ["docx", "xlsx"]. */
  exts: string[];
  idleTitle?: string;
  activeTitle?: string;
  disabled?: boolean;
  compact?: boolean;
}) {
  const [dragging, setDragging] = useState(false);

  function pick(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) onFile(f);
    // Without this, choosing the same file again (after removing it) fires no change.
    e.target.value = "";
  }

  function drop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    const files = e.dataTransfer.files;
    if (files.length > 1) onReject?.("Drop one file at a time.");
    else if (files[0]) onFile(files[0]);
  }

  function clear(e: MouseEvent) {
    // The button sits inside the <label>: without this it would also open the picker.
    e.preventDefault();
    e.stopPropagation();
    onClear();
  }

  const ext = file ? file.name.split(".").pop()?.toLowerCase() : null;

  return (
    <label
      className={`dropzone${dragging ? " dropzone-active" : ""}${compact ? " dropzone-compact" : ""}${disabled ? " dropzone-disabled" : ""}`}
      onDragEnter={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={(e) => {
        // dragleave also fires when crossing into a child; only a real exit clears it.
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
      }}
      onDrop={drop}
    >
      <input type="file" accept={accept} className="sr-only-input" disabled={disabled} onChange={pick} />
      {file ? (
        <div className="dropzone-file">
          <FileText size={22} strokeWidth={1.6} />
          <div className="dropzone-file-info">
            <span className="dropzone-file-name" title={file.name}>
              {file.name}
            </span>
            <span className="dropzone-file-size">
              {fmtBytes(file.size)}
              {ext && <span className={`badge badge-${ext} dropzone-file-badge`}>{ext}</span>}
            </span>
          </div>
          <button type="button" className="dropzone-remove" onClick={clear} disabled={disabled} title="Remove file" aria-label="Remove file">
            <X size={14} />
          </button>
        </div>
      ) : (
        <div className="dropzone-empty">
          <UploadCloud size={compact ? 22 : 26} strokeWidth={1.5} />
          <p className="dropzone-title">{dragging ? activeTitle : idleTitle}</p>
          <p className="dropzone-sub">or click to browse</p>
          <div className="dropzone-exts">
            {exts.map((x) => (
              <span key={x} className={`badge badge-${x}`}>
                {x}
              </span>
            ))}
          </div>
        </div>
      )}
    </label>
  );
}
