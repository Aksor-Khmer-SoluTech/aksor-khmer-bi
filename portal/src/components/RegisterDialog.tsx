import { useRef, useState, type ChangeEvent, type DragEvent, type FormEvent } from "react";
import { FileText, UploadCloud, X } from "lucide-react";
import { api, ApiError } from "../api";
import { onDialogCancel, useDialogRef } from "../hooks";
import { checkCode, isCodeError, suggestCode } from "../reportCode";
import type { AuthInfo, ImageResource, ParsedTemplate, ReportMeta, ResourceBinding, StylesheetResource } from "../types";
import ReportCodeField from "./ReportCodeField";

import ModalClose from "./ModalClose";
const NAME_MAX = 100;
const DESCRIPTION_MAX = 500;
const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(kb < 10 ? 1 : 0)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function extOf(filename: string): "html" | "docx" | "xlsx" | null {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  if (lower.endsWith(".docx")) return "docx";
  if (lower.endsWith(".xlsx")) return "xlsx";
  return null;
}

/** Best-guess which resource store a `{{ resource('name') }}` reference
 * belongs to, from the extension in its literal name — e.g. "logo.png"
 * -> image, "theme.css" -> stylesheet. Only used to default the inline
 * "upload new" affordance's target store and to pre-filter the picker;
 * the dropdown itself always lists both stores, since a template author
 * can name a resource() reference anything. */
function guessKind(resourceName: string): "image" | "stylesheet" {
  const lower = resourceName.toLowerCase();
  return IMAGE_EXTS.some((ext) => lower.endsWith(ext)) ? "image" : "stylesheet";
}

/** One row of the "map this template's resources" step — a
 * {{ resource('name') }} reference the parse found, a dropdown of
 * already-uploaded images/stylesheets to bind it to, and a small inline
 * uploader for when the right file isn't in the Resources library yet
 * (skips a trip out to the Resources page mid-registration). */
function ResourceMapRow({
  name,
  binding,
  images,
  stylesheets,
  onBind,
  onUploaded,
  orgId,
}: {
  name: string;
  binding: ResourceBinding | undefined;
  images: ImageResource[];
  stylesheets: StylesheetResource[];
  onBind: (binding: ResourceBinding) => void;
  onUploaded: (resource: ImageResource | StylesheetResource, kind: "image" | "stylesheet") => void;
  orgId: string;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const value = binding ? `${binding.kind}:${binding.id}` : "";

  async function handleUploadFile(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const kind = guessKind(f.name);
    setUploading(true);
    setUploadError(null);
    try {
      if (kind === "image") {
        const resource = await api.images.upload(f.name, orgId, null, f);
        onUploaded(resource, "image");
        onBind({ kind: "image", id: resource.id });
      } else {
        const resource = await api.stylesheets.upload(f.name, orgId, null, f);
        onUploaded(resource, "stylesheet");
        onBind({ kind: "stylesheet", id: resource.id });
      }
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="resource-map-row">
      <code className="resource-map-name">{name}</code>
      <select
        value={value}
        onChange={(e) => {
          const [kind, id] = e.target.value.split(":") as [ResourceBinding["kind"], string];
          onBind({ kind, id });
        }}
        aria-label={`Resource for ${name}`}
      >
        <option value="" disabled>
          Choose a resource…
        </option>
        {images.length > 0 && (
          <optgroup label="Images">
            {images.map((img) => (
              <option key={img.id} value={`image:${img.id}`}>
                {img.name}
              </option>
            ))}
          </optgroup>
        )}
        {stylesheets.length > 0 && (
          <optgroup label="Stylesheets">
            {stylesheets.map((css) => (
              <option key={css.id} value={`stylesheet:${css.id}`}>
                {css.name}
              </option>
            ))}
          </optgroup>
        )}
      </select>
      <button
        type="button"
        className="btn btn-sm resource-map-upload"
        onClick={() => uploadInputRef.current?.click()}
        disabled={uploading}
        title="Upload a new image or stylesheet for this reference"
      >
        {uploading ? <span className="spinner" /> : "Upload new"}
      </button>
      <input
        ref={uploadInputRef}
        type="file"
        accept={[...IMAGE_EXTS, ".css"].join(",")}
        className="sr-only-input"
        onChange={handleUploadFile}
      />
      {uploadError && <p className="resource-map-error">{uploadError}</p>}
    </div>
  );
}

export default function RegisterDialog({
  open,
  auth,
  onClose,
  onCreated,
}: {
  open: boolean;
  auth: AuthInfo;
  onClose: () => void;
  onCreated: (report: ReportMeta) => void;
}) {
  const orgId = auth.orgId ?? "root";
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // html-template-only: the pre-flight parse result, and the resource()
  // name -> uploaded resource mapping the caller picks from it.
  const [parsedTemplate, setParsedTemplate] = useState<ParsedTemplate | null>(null);
  const [parsing, setParsing] = useState(false);
  const [resourceMap, setResourceMap] = useState<Record<string, ResourceBinding>>({});
  const [images, setImages] = useState<ImageResource[]>([]);
  const [stylesheets, setStylesheets] = useState<StylesheetResource[]>([]);

  const ref = useDialogRef(open, () => {
    setName("");
    setDescription("");
    setCode("");
    setCodeError(null);
    setFile(null);
    setIsDragging(false);
    setError(null);
    setParsedTemplate(null);
    setParsing(false);
    setResourceMap({});
  });

  async function acceptFile(f: File) {
    const ext = extOf(f.name);
    if (ext === null) {
      setError("Template file must be a .docx, .xlsx, or .html");
      return;
    }
    setError(null);
    setFile(f);
    setParsedTemplate(null);
    setResourceMap({});

    if (ext !== "html") return;
    setParsing(true);
    try {
      const parsed = await api.parseTemplate(f);
      setParsedTemplate(parsed);
      if (parsed.resources.length > 0 && images.length === 0 && stylesheets.length === 0) {
        const [imgs, css] = await Promise.all([
          api.images.list({ orgId }),
          api.stylesheets.list({ orgId }),
        ]);
        setImages(imgs);
        setStylesheets(css);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't parse template");
    } finally {
      setParsing(false);
    }
  }

  function handleFileInput(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) acceptFile(f);
  }

  function handleDragEnter(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setIsDragging(true);
  }

  function handleDragOver(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
  }

  function handleDragLeave(e: DragEvent<HTMLLabelElement>) {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsDragging(false);
  }

  function handleDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) acceptFile(dropped);
  }

  function removeFile(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setFile(null);
    setParsedTemplate(null);
    setResourceMap({});
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function bindResource(resourceName: string, binding: ResourceBinding) {
    setResourceMap((prev) => ({ ...prev, [resourceName]: binding }));
  }

  function addUploadedResource(resource: ImageResource | StylesheetResource, kind: "image" | "stylesheet") {
    if (kind === "image") setImages((prev) => [...prev, resource as ImageResource]);
    else setStylesheets((prev) => [...prev, resource as StylesheetResource]);
  }

  const isHtml = file !== null && extOf(file.name) === "html";
  const templateErrors = parsedTemplate?.errors ?? [];
  const unmappedResources = (parsedTemplate?.resources ?? []).filter((r) => !resourceMap[r]);
  const blockedByHtmlValidation = isHtml && (parsing || templateErrors.length > 0 || unmappedResources.length > 0);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Choose a template file to upload");
      return;
    }
    if (blockedByHtmlValidation) {
      setError(
        templateErrors.length > 0
          ? "Fix the template errors below before registering"
          : "Map every referenced resource before registering"
      );
      return;
    }
    if (checkCode(code)) return; // the field is already saying why
    setPending(true);
    setError(null);
    setCodeError(null);
    try {
      const report = await api.createReport(name, description, file, isHtml ? resourceMap : undefined, code);
      onCreated(report);
      onClose();
    } catch (err) {
      if (err instanceof ApiError && code.trim() && isCodeError(err.status, err.message)) setCodeError(err.message);
      else setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal" onCancel={onDialogCancel(onClose)}>
      <ModalClose />
      <h2 className="panel-title">Register a template</h2>
      <p className="panel-subtitle">
        A .docx, .xlsx, or .html file with {"{{ field }}"} placeholders — an html template can also reference an
        uploaded image or stylesheet via {"{{ resource('name') }}"}.{" "}
        <a href="#/docs/create-a-template" target="_blank" rel="noreferrer">
          Create a template: the guide
        </a>
      </p>
      <form onSubmit={handleSubmit}>
        <label>
          <span className="field-label-row">
            <span>
              Name <span className="required-mark">*</span>
            </span>
            <span className={`char-counter${name.length >= NAME_MAX ? " char-counter-limit" : ""}`}>
              {name.length}/{NAME_MAX}
            </span>
          </span>
          <input type="text" required maxLength={NAME_MAX} value={name} onChange={(e) => setName(e.target.value)} />
        </label>

        <ReportCodeField
          value={code}
          onChange={(v) => {
            setCode(v);
            setCodeError(null);
          }}
          suggestion={suggestCode(name)}
          serverError={codeError}
        />

        <label>
          <span className="field-label-row">
            <span>Description</span>
            <span className={`char-counter${description.length >= DESCRIPTION_MAX ? " char-counter-limit" : ""}`}>
              {description.length}/{DESCRIPTION_MAX}
            </span>
          </span>
          <textarea
            rows={3}
            maxLength={DESCRIPTION_MAX}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>

        <div className="field-block">
          <span className="field-label">
            Template file <span className="required-mark">*</span>
          </span>
          <label
            className={`dropzone${isDragging ? " dropzone-active" : ""}`}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".docx,.xlsx,.html,.htm"
              className="sr-only-input"
              onChange={handleFileInput}
            />
            {file ? (
              <div className="dropzone-file">
                <FileText size={22} strokeWidth={1.6} />
                <div className="dropzone-file-info">
                  <span className="dropzone-file-name">{file.name}</span>
                  <span className="dropzone-file-size">{formatBytes(file.size)}</span>
                </div>
                <button type="button" className="dropzone-remove" onClick={removeFile} title="Remove file">
                  <X size={14} />
                </button>
              </div>
            ) : (
              <div className="dropzone-empty">
                <UploadCloud size={26} strokeWidth={1.5} />
                <p className="dropzone-title">Drag & drop your template here</p>
                <p className="dropzone-sub">or click to browse</p>
                <div className="dropzone-exts">
                  <span className="badge badge-docx">docx</span>
                  <span className="badge badge-xlsx">xlsx</span>
                  <span className="badge badge-html">html</span>
                </div>
              </div>
            )}
          </label>
        </div>

        {isHtml && parsing && <p className="muted template-parse-status">Checking template…</p>}

        {isHtml && !parsing && templateErrors.length > 0 && (
          <div className="alert alert-error template-errors">
            <p className="template-errors-title">This template has {templateErrors.length === 1 ? "an error" : "errors"}:</p>
            <ul>
              {templateErrors.map((issue, i) => (
                <li key={i}>
                  {issue.message}
                  {issue.line != null && <span className="template-error-loc"> (line {issue.line})</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {isHtml && !parsing && templateErrors.length === 0 && parsedTemplate && parsedTemplate.resources.length > 0 && (
          <div className="field-block resource-map">
            <span className="field-label">Map referenced resources</span>
            <p className="field-hint" style={{ marginTop: -2 }}>
              This template points at {parsedTemplate.resources.length} resource
              {parsedTemplate.resources.length === 1 ? "" : "s"} via {"{{ resource('name') }}"} — pick which uploaded
              file each one renders as.
            </p>
            {parsedTemplate.resources.map((resourceName) => (
              <ResourceMapRow
                key={resourceName}
                name={resourceName}
                binding={resourceMap[resourceName]}
                images={images}
                stylesheets={stylesheets}
                orgId={orgId}
                onBind={(binding) => bindResource(resourceName, binding)}
                onUploaded={addUploadedResource}
              />
            ))}
          </div>
        )}

        {isHtml && !parsing && templateErrors.length === 0 && parsedTemplate && parsedTemplate.fields.length > 0 && (
          <p className="field-hint template-fields-hint">
            Detected fields: {parsedTemplate.fields.join(", ")}
          </p>
        )}

        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending || blockedByHtmlValidation || checkCode(code) !== null}>
            {pending && <span className="spinner" />}
            Register
          </button>
        </div>
      </form>
    </dialog>
  );
}
