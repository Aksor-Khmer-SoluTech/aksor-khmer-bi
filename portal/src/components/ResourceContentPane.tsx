import { useDraggable } from "@dnd-kit/core";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link2 } from "lucide-react";
import { UploadIcon } from "../admin/icons";
import { api, ApiError } from "../api";
import { useDialogRef } from "../hooks";
import type { Folder, ImageResource, ReportMeta, StyleFormat, StylesheetResource } from "../types";
import ModalClose from "./ModalClose";

function ReportCard({ report }: { report: ReportMeta }) {
  const draggable = useDraggable({ id: `drag-report:${report.report_id}`, data: { kind: "report", id: report.report_id } });
  return (
    <article
      ref={draggable.setNodeRef}
      {...draggable.listeners}
      {...draggable.attributes}
      className="card resource-card"
      style={{ opacity: draggable.isDragging ? 0.4 : 1, cursor: "grab" }}
    >
      <div className="card-top">
        <h3 className="card-name">{report.name}</h3>
        <span className={`badge badge-${report.template_ext}`}>{report.template_ext}</span>
      </div>
      {/* Always rendered, even blank -- .card-desc reserves two lines'
          worth of height either way, so a card with no description is
          never shorter than one that has it (matters most in a CSS
          Grid row that's otherwise alone, with nothing else to stretch
          against -- see styles/pages.css's own note on .card-desc). */}
      <p className="card-desc">{report.description}</p>
      <div className="card-meta">
        <span>Report</span>
        <span>{new Date(report.updated_at).toLocaleDateString()}</span>
      </div>
    </article>
  );
}

/** A report listed here from somewhere else. Not draggable: it is a link, and it opens the original, with the
 * original's permissions. */
function ShortcutCard({ report, canManage, onRemove }: { report: ReportMeta; canManage: boolean; onRemove: () => void }) {
  return (
    <article className="card resource-card resource-card-shortcut">
      <div className="card-top">
        <h3 className="card-name">{report.name}</h3>
        <span className="shortcut-chip">
          <Link2 size={12} aria-hidden="true" /> Shortcut
        </span>
      </div>
      <p className="card-desc">{report.description}</p>
      <div className="card-meta">
        <a className="link-btn" href={`#/reports/${encodeURIComponent(report.report_id)}`}>
          Open the original
        </a>
        {canManage && (
          <button type="button" className="link-btn" onClick={onRemove}>
            Remove shortcut
          </button>
        )}
      </div>
    </article>
  );
}

function ImageThumbnail({ image }: { image: ImageResource }) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    api.images
      .fileBlob(image.id)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [image.id]);

  return (
    <div className="resource-thumb">
      {src ? <img src={src} alt="" /> : <span className="muted">…</span>}
    </div>
  );
}

function ImageCard({ image, canManage, onDelete }: { image: ImageResource; canManage: boolean; onDelete: () => void }) {
  const draggable = useDraggable({ id: `drag-image:${image.id}`, data: { kind: "image", id: image.id } });
  return (
    <article
      ref={draggable.setNodeRef}
      {...draggable.listeners}
      {...draggable.attributes}
      className="card resource-card"
      style={{ opacity: draggable.isDragging ? 0.4 : 1, cursor: "grab" }}
    >
      <ImageThumbnail image={image} />
      <div className="card-top">
        <h3 className="card-name">{image.name}</h3>
        <span className="badge badge-docx">{image.file_ext}</span>
      </div>
      <div className="card-meta">
        <span>
          {image.width_px}×{image.height_px}px
        </span>
        {canManage && (
          <button
            type="button"
            className="link-btn"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
          >
            delete
          </button>
        )}
      </div>
    </article>
  );
}

const STYLE_LABEL: Record<StyleFormat, string> = { css: "CSS", scss: "SCSS", sass: "Sass", less: "Less" };
const STYLE_ACCEPT = ".css,.scss,.sass,.less";

/** A stylesheet in the library: its first lines as the "thumbnail", the format it was written in, and what you can
 * do with it -- view the source and the compiled CSS, replace it (any format), delete it. */
function StyleCard({
  sheet,
  canManage,
  onView,
  onReplace,
  onDelete,
}: {
  sheet: StylesheetResource;
  canManage: boolean;
  onView: () => void;
  onReplace: () => void;
  onDelete: () => void;
}) {
  const [head, setHead] = useState<string | null>(null);
  const fmt = sheet.source_format ?? "css";
  useEffect(() => {
    let live = true;
    api.stylesheets
      .source(sheet.id)
      .then((text) => live && setHead(text.split("\n").slice(0, 7).join("\n")))
      .catch(() => live && setHead(""));
    return () => {
      live = false;
    };
  }, [sheet.id, sheet.updated_at]);
  return (
    <article className="card resource-card">
      <button
        type="button"
        onClick={onView}
        className="mb-2 block h-[104px] w-full cursor-pointer overflow-hidden rounded-[8px] border border-border-soft bg-bg-panel p-2 text-left"
        title="View the source and the compiled CSS"
      >
        <pre className="m-0 font-mono text-[0.66rem] leading-[1.45] whitespace-pre text-text-dim">{head ?? "…"}</pre>
      </button>
      <div className="card-top">
        <h3 className="card-name">{sheet.name}</h3>
        <span className={`badge ${fmt === "css" ? "badge-html" : "badge-xlsx"}`}>{STYLE_LABEL[fmt]}</span>
      </div>
      <div className="card-meta">
        <span>{sheet.size_bytes < 1024 ? `${sheet.size_bytes} B` : `${(sheet.size_bytes / 1024).toFixed(1)} KB`} CSS</span>
        <span className="flex gap-2.5">
          <button type="button" className="link-btn" onClick={onView}>
            view
          </button>
          {canManage && (
            <>
              <button type="button" className="link-btn" onClick={onReplace}>
                replace
              </button>
              <button type="button" className="link-btn" onClick={onDelete}>
                delete
              </button>
            </>
          )}
        </span>
      </div>
    </article>
  );
}

/** The source as uploaded beside the CSS a template gets -- for SCSS / Sass / Less the two differ. */
function StyleViewer({ sheet, onClose }: { sheet: StylesheetResource; onClose: () => void }) {
  const ref = useDialogRef(true);
  const fmt = sheet.source_format ?? "css";
  const [tab, setTab] = useState<"source" | "css">("source");
  const [text, setText] = useState<{ source?: string; css?: string }>({});
  useEffect(() => {
    void Promise.all([api.stylesheets.source(sheet.id), fmt === "css" ? Promise.resolve(undefined) : api.stylesheets.css(sheet.id)]).then(([source, css]) =>
      setText({ source, css }),
    );
  }, [sheet.id, fmt]);
  return (
    <dialog ref={ref} className="modal modal-wide" onCancel={onClose} onClose={onClose}>
      <ModalClose />
      <h2 className="panel-title">
        {sheet.name} <span className="badge badge-xlsx align-middle">{STYLE_LABEL[fmt]}</span>
      </h2>
      {fmt !== "css" && (
        <div className="segmented segmented-sm mb-2" role="tablist">
          <button type="button" className={`segmented-btn${tab === "source" ? " active" : ""}`} onClick={() => setTab("source")}>
            {STYLE_LABEL[fmt]} source
          </button>
          <button type="button" className={`segmented-btn${tab === "css" ? " active" : ""}`} onClick={() => setTab("css")}>
            Compiled CSS — what templates get
          </button>
        </div>
      )}
      <pre className="m-0 max-h-[60vh] overflow-auto rounded-[8px] border border-border-soft bg-bg-panel p-3 font-mono text-[0.78rem] leading-[1.5]">
        {(tab === "source" ? text.source : text.css) ?? "Loading…"}
      </pre>
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </dialog>
  );
}

type Duplicate = { kind: "image" | "stylesheet"; id: string; duplicates: { id: string; name: string; where: string }[] };

export default function ResourceContentPane({
  folder,
  reports,
  images,
  stylesheets,
  shortcuts,
  onRemoveShortcut,
  canManage,
  orgId,
  onImageUploaded,
  onImageDeleted,
  onStylesheetChanged,
  onStylesheetDeleted,
}: {
  folder: Folder | null;
  reports: ReportMeta[];
  images: ImageResource[];
  stylesheets: StylesheetResource[];
  shortcuts: { shortcut: { id: string }; report: ReportMeta }[];
  onRemoveShortcut: (id: string) => void;
  canManage: boolean;
  orgId: string;
  onImageUploaded: (image: ImageResource) => void;
  onImageDeleted: (id: string) => void;
  /** Added or replaced. */
  onStylesheetChanged: (sheet: StylesheetResource) => void;
  onStylesheetDeleted: (id: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const styleInputRef = useRef<HTMLInputElement>(null);
  const replaceRef = useRef<{ input: HTMLInputElement | null; id: string | null }>({ input: null, id: null });
  const [uploading, setUploading] = useState<"image" | "style" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<StylesheetResource | null>(null);
  // The file just uploaded was already here (same content): say where, and offer to drop the new copy.
  const [duplicate, setDuplicate] = useState<Duplicate | null>(null);

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading("image");
    setError(null);
    try {
      const image = await api.images.upload(file.name, orgId, folder?.id ?? null, file);
      onImageUploaded(image);
      setDuplicate(image.duplicates?.length ? { kind: "image", id: image.id, duplicates: image.duplicates } : null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't upload image");
    } finally {
      setUploading(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleStyleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading("style");
    setError(null);
    try {
      const name = file.name.replace(/\.(css|scss|sass|less)$/i, "");
      const sheet = await api.stylesheets.upload(name, orgId, folder?.id ?? null, file);
      onStylesheetChanged(sheet);
      setDuplicate(sheet.duplicates?.length ? { kind: "stylesheet", id: sheet.id, duplicates: sheet.duplicates } : null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't upload the stylesheet");
    } finally {
      setUploading(null);
      if (styleInputRef.current) styleInputRef.current.value = "";
    }
  }

  async function handleReplace(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    const id = replaceRef.current.id;
    if (!file || !id) return;
    setError(null);
    try {
      onStylesheetChanged(await api.stylesheets.replace(id, file));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't replace the stylesheet");
    } finally {
      e.target.value = "";
    }
  }

  async function handleDelete(id: string) {
    setError(null);
    try {
      await api.images.delete(id);
      onImageDeleted(id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete image");
    }
  }

  async function handleDeleteStyle(id: string) {
    setError(null);
    try {
      await api.stylesheets.delete(id);
      onStylesheetDeleted(id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete the stylesheet");
    }
  }

  const empty = reports.length === 0 && images.length === 0 && stylesheets.length === 0 && shortcuts.length === 0;

  return (
    <div className="resource-content">
      <div className="resource-content-header">
        <div>
          <h2 className="resource-content-title">{folder ? folder.name : "Root"}</h2>
          {folder?.description && <p className="muted" style={{ margin: "2px 0 0" }}>{folder.description}</p>}
        </div>
        {canManage && (
          <div className="flex flex-wrap gap-2">
            <input ref={fileInputRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handleFileChange} />
            <input ref={styleInputRef} type="file" accept={STYLE_ACCEPT} style={{ display: "none" }} onChange={handleStyleChange} />
            <input
              ref={(el) => {
                replaceRef.current.input = el;
              }}
              type="file"
              accept={STYLE_ACCEPT}
              style={{ display: "none" }}
              onChange={handleReplace}
            />
            <button type="button" className="btn btn-sm" disabled={uploading !== null} onClick={() => fileInputRef.current?.click()}>
              {uploading === "image" ? <span className="spinner" /> : <UploadIcon />}
              Upload image
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={uploading !== null}
              onClick={() => styleInputRef.current?.click()}
              title="CSS, SCSS, Sass or Less -- compiled to CSS on upload"
            >
              {uploading === "style" ? <span className="spinner" /> : <UploadIcon />}
              Upload stylesheet
            </button>
          </div>
        )}
      </div>

      {error && <p className="alert alert-error whitespace-pre-wrap">{error}</p>}
      {duplicate ? (
        <div className="alert alert-warning flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span className="min-w-0 flex-1 leading-snug">
            This exact {duplicate.kind === "image" ? "image" : "stylesheet"} is already here as{" "}
            {duplicate.duplicates.map((d, i) => (
              <span key={d.id}>
                {i > 0 && ", "}“<b>{d.name}</b>” <span className="text-text-dim">in {d.where}</span>
              </span>
            ))}
            . A separate copy keeps this folder self-contained (a project moves with its own files); one shared file is updated once, for everyone.
          </span>
          <button type="button" className="btn btn-sm" onClick={() => setDuplicate(null)}>
            Keep both
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              void (duplicate.kind === "image" ? handleDelete(duplicate.id) : handleDeleteStyle(duplicate.id));
              setDuplicate(null);
            }}
          >
            Remove the new copy
          </button>
        </div>
      ) : null}

      {empty ? (
        <div className="empty-state">
          <p>Nothing here yet.</p>
          <p className="muted" style={{ maxWidth: 380, margin: "6px auto 0" }}>
            Drag a report or image from another folder into this one from the tree on the left, or upload an image or a stylesheet (CSS, SCSS, Sass or
            Less) directly.
          </p>
        </div>
      ) : (
        <div className="card-grid">
          {reports.map((r, i) => (
            <div key={r.report_id} style={{ "--i": i } as CSSProperties}>
              <ReportCard report={r} />
            </div>
          ))}
          {shortcuts.map(({ shortcut, report }, i) => (
            <div key={shortcut.id} style={{ "--i": reports.length + i } as CSSProperties}>
              <ShortcutCard report={report} canManage={canManage} onRemove={() => onRemoveShortcut(shortcut.id)} />
            </div>
          ))}
          {images.map((img, i) => (
            <div key={img.id} style={{ "--i": reports.length + shortcuts.length + i } as CSSProperties}>
              <ImageCard image={img} canManage={canManage} onDelete={() => handleDelete(img.id)} />
            </div>
          ))}
          {stylesheets.map((sheet, i) => (
            <div key={sheet.id} style={{ "--i": reports.length + shortcuts.length + images.length + i } as CSSProperties}>
              <StyleCard
                sheet={sheet}
                canManage={canManage}
                onView={() => setViewing(sheet)}
                onReplace={() => {
                  replaceRef.current.id = sheet.id;
                  replaceRef.current.input?.click();
                }}
                onDelete={() => void handleDeleteStyle(sheet.id)}
              />
            </div>
          ))}
        </div>
      )}
      {viewing && <StyleViewer sheet={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}
