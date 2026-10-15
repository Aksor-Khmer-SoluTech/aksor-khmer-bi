import { useDraggable } from "@dnd-kit/core";
import { useEffect, useRef, useState, type CSSProperties, type DragEvent } from "react";
import { CircleCheck, Link2, MoreHorizontal } from "lucide-react";
import { UploadIcon } from "../admin/icons";
import { api, ApiError } from "../api";
import type { Folder, ImageResource, ReportMeta, StylesheetResource } from "../types";
import ResourceDetails, { STYLE_LABEL, type DetailItem } from "./ResourceDetails";

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

type CardAction = "open" | "copy" | "replace" | "move" | "delete";

/** The one "…" menu on an image or stylesheet card -- everything else happens in its details panel. */
function CardMenu({ canManage, onAction }: { canManage: boolean; onAction: (action: CardAction) => void }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => rootRef.current && !rootRef.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  const items: [CardAction, string][] = [
    ["open", "Details"],
    ["copy", "Copy reference"],
    ...(canManage ? ([["replace", "Replace…"], ["move", "Move…"], ["delete", "Delete"]] as [CardAction, string][]) : []),
  ];
  return (
    <div className="relative" ref={rootRef} onPointerDown={(e) => e.stopPropagation()}>
      <button
        type="button"
        className="btn btn-ghost btn-sm icon-only"
        aria-label="More"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        <MoreHorizontal size={15} />
      </button>
      {open && (
        <div className="account-panel resource-row-panel right-0 left-auto" role="menu" onClick={(e) => e.stopPropagation()}>
          {items.map(([action, label]) => (
            <button
              key={action}
              type="button"
              className={`account-item${action === "delete" ? " account-item-danger" : ""}`}
              onClick={() => {
                setOpen(false);
                onAction(action);
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** An image or a stylesheet: its picture (or first lines of CSS), name, type, and the one menu. Click to open it. */
function FileCard({ item, canManage, onAction }: { item: DetailItem; canManage: boolean; onAction: (action: CardAction) => void }) {
  const draggable = useDraggable({ id: `drag-${item.kind}:${item.data.id}`, data: { kind: item.kind, id: item.data.id } });
  const [head, setHead] = useState<string | null>(null);
  const fmt = item.kind === "stylesheet" ? (item.data.source_format ?? "css") : null;
  useEffect(() => {
    if (item.kind !== "stylesheet") return;
    let live = true;
    api.stylesheets
      .source(item.data.id)
      .then((text) => live && setHead(text.split("\n").slice(0, 6).join("\n")))
      .catch(() => live && setHead(""));
    return () => {
      live = false;
    };
  }, [item.kind, item.data.id, item.data.updated_at]);
  return (
    <article
      ref={draggable.setNodeRef}
      {...draggable.listeners}
      {...draggable.attributes}
      className="card resource-card cursor-pointer"
      style={{ opacity: draggable.isDragging ? 0.4 : 1 }}
      onClick={() => onAction("open")}
      onKeyDown={(e) => e.key === "Enter" && onAction("open")}
      title="Open — how to use it, where it's used"
    >
      {item.kind === "image" ? (
        <ImageThumbnail image={item.data} />
      ) : (
        <div className="resource-thumb items-start justify-start overflow-hidden p-2">
          <pre className="m-0 font-mono text-[0.64rem] leading-[1.45] whitespace-pre text-text-dim">{head ?? "…"}</pre>
        </div>
      )}
      <div className="card-top items-center">
        <h3 className="card-name">{item.data.name}</h3>
        <span className="ml-auto flex shrink-0 items-center gap-1">
          <span className={`badge ${item.kind === "image" ? "badge-docx" : fmt === "css" ? "badge-html" : "badge-xlsx"}`}>
            {item.kind === "image" ? item.data.file_ext : STYLE_LABEL[fmt ?? "css"]}
          </span>
          <CardMenu canManage={canManage} onAction={onAction} />
        </span>
      </div>
    </article>
  );
}

const STYLE_EXT = /\.(css|scss|sass|less)$/i;
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|svg|tiff?)$/i;
type Filter = "all" | "templates" | "images" | "stylesheets";
type UploadNote = { name: string; kind: DetailItem["kind"]; id: string; same: { id: string; name: string; where: string }[]; compiled?: string };

export default function ResourceContentPane({
  folder,
  folders,
  reports,
  images,
  stylesheets,
  shortcuts,
  onRemoveShortcut,
  canManage,
  orgId,
  onImageChanged,
  onImageDeleted,
  onStylesheetChanged,
  onStylesheetDeleted,
}: {
  folder: Folder | null;
  folders: Folder[];
  reports: ReportMeta[];
  images: ImageResource[];
  stylesheets: StylesheetResource[];
  shortcuts: { shortcut: { id: string }; report: ReportMeta }[];
  onRemoveShortcut: (id: string) => void;
  canManage: boolean;
  orgId: string;
  /** Added, replaced, renamed or moved. */
  onImageChanged: (image: ImageResource) => void;
  onImageDeleted: (id: string) => void;
  onStylesheetChanged: (sheet: StylesheetResource) => void;
  onStylesheetDeleted: (id: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<UploadNote[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<{ item: DetailItem; action: "replace" | "move" | "delete" | null } | null>(null);
  const [dropping, setDropping] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    setFilter("all");
    setNotes([]);
  }, [folder?.id]);

  function changed(item: DetailItem) {
    if (item.kind === "image") onImageChanged(item.data);
    else onStylesheetChanged(item.data);
    setOpen((o) => (o && o.item.data.id === item.data.id ? { ...o, item } : o));
  }
  function deleted(kind: DetailItem["kind"], id: string) {
    if (kind === "image") onImageDeleted(id);
    else onStylesheetDeleted(id);
    setNotes((n) => n.filter((x) => x.id !== id));
  }

  /** Images and style files in one go, each to its own kind -- told apart by the file name. */
  async function upload(files: File[]) {
    if (!files.length) return;
    setUploading(true);
    setError(null);
    const done: UploadNote[] = [];
    const problems: string[] = [];
    for (const file of files) {
      try {
        if (STYLE_EXT.test(file.name)) {
          const sheet = await api.stylesheets.upload(file.name.replace(STYLE_EXT, ""), orgId, folder?.id ?? null, file);
          onStylesheetChanged(sheet);
          const fmt = sheet.source_format ?? "css";
          done.push({ name: file.name, kind: "stylesheet", id: sheet.id, same: sheet.duplicates ?? [], compiled: fmt !== "css" ? STYLE_LABEL[fmt] : undefined });
        } else if (IMAGE_EXT.test(file.name) || file.type.startsWith("image/")) {
          const image = await api.images.upload(file.name.replace(/\.[^.]+$/, ""), orgId, folder?.id ?? null, file);
          onImageChanged(image);
          done.push({ name: file.name, kind: "image", id: image.id, same: image.duplicates ?? [] });
        } else {
          problems.push(`${file.name}: not an image or a stylesheet (.css, .scss, .sass, .less)`);
        }
      } catch (err) {
        problems.push(`${file.name}: ${err instanceof ApiError ? err.message : "couldn't upload it"}`);
      }
    }
    setNotes(done);
    setError(problems.length ? problems.join("\n") : null);
    setUploading(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function removeNew(note: UploadNote) {
    try {
      await (note.kind === "image" ? api.images.delete(note.id) : api.stylesheets.delete(note.id));
      deleted(note.kind, note.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove it");
    }
  }

  function act(item: DetailItem, action: CardAction) {
    if (action === "copy") {
      void navigator.clipboard?.writeText(`{{ resource('${item.data.name}') }}`).then(() => {
        setCopied(item.data.id);
        window.setTimeout(() => setCopied(null), 1500);
      });
      return;
    }
    setOpen({ item, action: action === "open" ? null : action });
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    if (!canManage || !e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    setDropping(true);
  }
  function onDrop(e: DragEvent<HTMLDivElement>) {
    if (!canManage || !e.dataTransfer.files.length) return;
    e.preventDefault();
    setDropping(false);
    void upload([...e.dataTransfer.files]);
  }

  const counts = { templates: reports.length + shortcuts.length, images: images.length, stylesheets: stylesheets.length };
  const total = counts.templates + counts.images + counts.stylesheets;
  const show = (f: Filter) => filter === "all" || filter === f;
  const files: DetailItem[] = [
    ...(show("images") ? images.map((data) => ({ kind: "image" as const, data })) : []),
    ...(show("stylesheets") ? stylesheets.map((data) => ({ kind: "stylesheet" as const, data })) : []),
  ];

  return (
    <div
      className={`resource-content relative rounded-[12px] ${dropping ? "outline-2 outline-offset-4 outline-accent outline-dashed" : ""}`}
      onDragOver={onDragOver}
      onDragLeave={(e) => e.currentTarget === e.target && setDropping(false)}
      onDrop={onDrop}
    >
      <div className="resource-content-header">
        <div>
          <h2 className="resource-content-title">{folder ? folder.name : "Root"}</h2>
          {folder?.description && <p className="muted" style={{ margin: "2px 0 0" }}>{folder.description}</p>}
        </div>
        {canManage && (
          <>
            <input ref={inputRef} type="file" multiple accept={`image/*,.css,.scss,.sass,.less`} className="hidden" onChange={(e) => void upload([...(e.target.files ?? [])])} />
            <button
              type="button"
              className="btn btn-sm"
              disabled={uploading}
              onClick={() => inputRef.current?.click()}
              title="Images, and stylesheets in CSS, SCSS, Sass or Less — or drop files on this folder"
            >
              {uploading ? <span className="spinner" /> : <UploadIcon />}
              Upload
            </button>
          </>
        )}
      </div>

      {total > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5" role="tablist" aria-label="Show">
          {(
            [
              ["all", "All", total],
              ["templates", "Templates", counts.templates],
              ["images", "Images", counts.images],
              ["stylesheets", "Stylesheets", counts.stylesheets],
            ] as const
          )
            .filter(([f, , n]) => f === "all" || n > 0)
            .map(([f, label, n]) => (
              <button
                key={f}
                type="button"
                role="tab"
                aria-selected={filter === f}
                className={`rounded-full border px-2.5 py-0.5 text-[0.78rem] ${filter === f ? "border-accent-border bg-accent-soft text-accent-strong" : "border-border-soft text-text-dim hover:bg-bg-panel"}`}
                onClick={() => setFilter(f)}
              >
                {label} <span className="font-mono text-[0.72rem] opacity-80">{n}</span>
              </button>
            ))}
        </div>
      )}

      {error && <p className="alert alert-error whitespace-pre-wrap">{error}</p>}
      {notes.length > 0 && (
        <div className="mb-3 grid gap-1 rounded-[10px] border border-border-soft px-3 py-2 text-[0.84rem]">
          {notes.map((n) => (
            <div key={n.id} className="flex flex-wrap items-center gap-x-2">
              <CircleCheck size={14} className="shrink-0 text-success" aria-hidden="true" />
              <span className="min-w-0">
                {n.name} uploaded{n.compiled ? ` · ${n.compiled} compiled to CSS` : ""}
                {n.same.length > 0 && (
                  <span className="text-text-dim">
                    {" "}
                    · same file as “{n.same[0].name}” in {n.same[0].where}
                  </span>
                )}
              </span>
              {n.same.length > 0 && (
                <button type="button" className="link-btn text-[0.82rem]" onClick={() => void removeNew(n)} title="Remove the copy you just uploaded and keep the one already here">
                  Use that one
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {total === 0 ? (
        <div className="empty-state">
          <p>{canManage ? "Drop files here, or press Upload." : "Nothing here yet."}</p>
          <p className="muted" style={{ maxWidth: 400, margin: "6px auto 0" }}>
            Images, and stylesheets in CSS, SCSS, Sass or Less. Templates come in from Templates, or drag one here from another folder.
          </p>
        </div>
      ) : (
        <div className="card-grid">
          {show("templates") &&
            reports.map((r, i) => (
              <div key={r.report_id} style={{ "--i": i } as CSSProperties}>
                <ReportCard report={r} />
              </div>
            ))}
          {show("templates") &&
            shortcuts.map(({ shortcut, report }, i) => (
              <div key={shortcut.id} style={{ "--i": reports.length + i } as CSSProperties}>
                <ShortcutCard report={report} canManage={canManage} onRemove={() => onRemoveShortcut(shortcut.id)} />
              </div>
            ))}
          {files.map((item, i) => (
            <div key={`${item.kind}-${item.data.id}`} className="relative" style={{ "--i": counts.templates + i } as CSSProperties}>
              <FileCard item={item} canManage={canManage} onAction={(a) => act(item, a)} />
              {copied === item.data.id && (
                <span className="pointer-events-none absolute top-2 right-2 rounded-full bg-accent px-2 py-0.5 text-[0.72rem] text-accent-ink">Copied</span>
              )}
            </div>
          ))}
        </div>
      )}

      {open && (
        <ResourceDetails
          key={`${open.item.kind}-${open.item.data.id}`}
          item={open.item}
          folders={folders}
          canManage={canManage}
          initialAction={open.action}
          onChanged={changed}
          onDeleted={deleted}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}
