import { useDraggable } from "@dnd-kit/core";
import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent, type RefObject } from "react";
import { CircleCheck, Link2, MoreHorizontal } from "lucide-react";
import { UploadIcon } from "../admin/icons";
import { api, ApiError } from "../api";
import type { Folder, ImageResource, ReportMeta, StylesheetResource } from "../types";
import FloatingMenu from "./FloatingMenu";
import ResourceDetails, { STYLE_LABEL, type DetailItem } from "./ResourceDetails";

/* The cards are memoized: a folder can hold hundreds, and they redraw only when their own data changes -- not on
 * every drag, hover, menu or selection elsewhere on the page. Their handlers are stable functions that take the
 * card's id, for the same reason. */
const ReportCard = memo(function ReportCard({ report }: { report: ReportMeta }) {
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
});

/** A report listed here from somewhere else. Not draggable: it is a link, and it opens the original, with the
 * original's permissions. */
const ShortcutCard = memo(function ShortcutCard({
  shortcutId,
  report,
  canManage,
  onRemove,
}: {
  shortcutId: string;
  report: ReportMeta;
  canManage: boolean;
  onRemove: (shortcutId: string) => void;
}) {
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
          <button type="button" className="link-btn" onClick={() => onRemove(shortcutId)}>
            Remove shortcut
          </button>
        )}
      </div>
    </article>
  );
});

/* Card previews, kept for the session: going back to a folder shows them at once instead of fetching them again.
 * Keyed by id and last change, so a replaced picture or an edited stylesheet is fetched fresh. Bounded: past the
 * limit the oldest is dropped (and its object URL released). */
const PREVIEW_LIMIT = 300;
const thumbUrls = new Map<string, string>();
const thumbLoads = new Map<string, Promise<string>>();
const cssHeads = new Map<string, string>();

function remember<V>(map: Map<string, V>, key: string, value: V, release?: (v: V) => void) {
  map.set(key, value);
  if (map.size > PREVIEW_LIMIT) {
    const [oldKey, oldValue] = map.entries().next().value as [string, V];
    map.delete(oldKey);
    release?.(oldValue);
  }
}

function loadThumbnail(image: ImageResource): Promise<string> {
  const key = `${image.id}:${image.updated_at}`;
  let pending = thumbLoads.get(key);
  if (!pending) {
    pending = api.images
      .thumbnailBlob(image.id, 480)
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        remember(thumbUrls, key, url, (old) => URL.revokeObjectURL(old));
        return url;
      })
      .finally(() => thumbLoads.delete(key));
    thumbLoads.set(key, pending);
  }
  return pending;
}

/** True once `ref` is on screen or close to it (and stays true): previews below the fold wait until scrolled near. */
function useNearScreen(ref: RefObject<HTMLElement | null>): boolean {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || near) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    // Measured against the box that scrolls (the folder's own column), not the window: its edges clip the cards, so
    // the margin only reads ahead when it's that box's.
    let root: HTMLElement | null = el.parentElement;
    while (root && !/(auto|scroll)/.test(getComputedStyle(root).overflowY)) root = root.parentElement;
    const observer = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setNear(true), {
      root,
      rootMargin: "300px 0px",
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, near]);
  return near;
}

/* Every loading preview sweeps in step: an animation started now is set back by how far a shared 1.6s clock has
 * run, so cards that appear at different moments still shimmer as one band across the grid instead of flickering
 * out of phase. */
const SWEEP_MS = 1600;
const sweepDelay = () => ({ "--sweep-delay": `-${Math.round(performance.now() % SWEEP_MS)}ms` }) as CSSProperties;

function ImageThumbnail({ image }: { image: ImageResource }) {
  const key = `${image.id}:${image.updated_at}`;
  const ref = useRef<HTMLDivElement>(null);
  const near = useNearScreen(ref);
  const cached = thumbUrls.get(key);
  const [src, setSrc] = useState<string | null>(cached ?? null);
  // A preview already in memory is shown as it is -- no shimmer, no fade, every time the folder is reopened.
  const [shown, setShown] = useState(!!cached);
  const [shimmerGone, setShimmerGone] = useState(!!cached);
  const [failed, setFailed] = useState(false);
  const [delay] = useState(sweepDelay);

  useEffect(() => {
    const ready = thumbUrls.get(key);
    if (ready) {
      setSrc(ready);
      return;
    }
    setShown(false);
    setShimmerGone(false);
    if (!near) return;
    let live = true;
    setFailed(false);
    loadThumbnail(image)
      .then((url) => live && setSrc(url))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` covers the image's identity and version
  }, [key, near]);

  return (
    <div ref={ref} className="resource-thumb">
      {src && (
        <img
          src={src}
          alt=""
          decoding="async"
          className={shown ? "is-shown" : ""}
          // Decoded before it's revealed, so the fade never starts on a picture that is still being drawn.
          onLoad={(e) => {
            const img = e.currentTarget;
            (img.decode ? img.decode() : Promise.resolve()).catch(() => undefined).then(() => setShown(true));
          }}
          onError={() => setFailed(true)}
        />
      )}
      {/* Fades out under the picture as it fades in (one crossfade), then leaves. */}
      {!shimmerGone && !failed && (
        <div
          className={`resource-thumb-skel${shown ? " is-done" : ""}`}
          style={delay}
          aria-hidden="true"
          onTransitionEnd={() => shown && setShimmerGone(true)}
        />
      )}
      {failed && <span className="muted text-[0.74rem]">No preview</span>}
    </div>
  );
}

/** A stylesheet card's first lines, fetched when the card comes near the screen and kept for the session. */
function StylesheetHead({ sheet }: { sheet: StylesheetResource }) {
  const key = `${sheet.id}:${sheet.updated_at}`;
  const ref = useRef<HTMLDivElement>(null);
  const near = useNearScreen(ref);
  const [head, setHead] = useState<string | null>(() => cssHeads.get(key) ?? null);
  const [delay] = useState(sweepDelay);
  useEffect(() => {
    const known = cssHeads.get(key);
    if (known !== undefined) {
      setHead(known);
      return;
    }
    if (!near) return;
    let live = true;
    api.stylesheets
      .source(sheet.id)
      .then((text) => {
        const first = text.split("\n").slice(0, 6).join("\n");
        remember(cssHeads, key, first);
        if (live) setHead(first);
      })
      .catch(() => live && setHead(""));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` covers the sheet's identity and version
  }, [key, near]);
  return (
    <div ref={ref} className="resource-thumb items-start justify-start overflow-hidden p-2">
      {head === null ? (
        <div className="grid w-full gap-1.5 pt-0.5" aria-hidden="true">
          {["72%", "48%", "86%", "60%", "40%"].map((w, n) => (
            <div key={n} className="resource-line-skel" style={{ ...delay, width: w }} />
          ))}
        </div>
      ) : (
        <pre className="m-0 font-mono text-[0.64rem] leading-[1.45] whitespace-pre text-text-dim">{head}</pre>
      )}
    </div>
  );
}

type CardAction = "open" | "copy" | "replace" | "move" | "delete";

/** The one "…" menu on an image or stylesheet card -- everything else happens in its details panel. */
function CardMenu({ label, canManage, onAction }: { label: string; canManage: boolean; onAction: (action: CardAction) => void }) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const items: [CardAction, string][] = [
    ["open", "Details"],
    ["copy", "Copy reference"],
    ...(canManage ? ([["replace", "Replace…"], ["move", "Move…"], ["delete", "Delete"]] as [CardAction, string][]) : []),
  ];
  return (
    // A press here must not start dragging the card it sits on.
    <div onPointerDown={(e) => e.stopPropagation()}>
      <button
        ref={trigger}
        type="button"
        className="btn btn-ghost btn-sm icon-only"
        aria-label="More"
        aria-haspopup="menu"
        aria-expanded={at !== null}
        onClick={(e) => {
          e.stopPropagation();
          const r = e.currentTarget.getBoundingClientRect();
          setAt((open) => (open ? null : { x: r.right - 190, y: r.bottom + 4 }));
        }}
      >
        <MoreHorizontal size={15} />
      </button>
      {at && (
        <FloatingMenu x={at.x} y={at.y} width={190} label={label} onClose={() => setAt(null)} ignore={trigger.current}>
          {(close) =>
            items.map(([action, label]) => (
              <button
                key={action}
                type="button"
                role="menuitem"
                className={`account-item${action === "delete" ? " account-item-danger" : ""}`}
                onClick={() => {
                  close();
                  onAction(action);
                }}
              >
                {label}
              </button>
            ))
          }
        </FloatingMenu>
      )}
    </div>
  );
}

/** An image or a stylesheet: its picture (or first lines of CSS), name, type, and the one menu. Click to open it. */
const FileCard = memo(function FileCard({
  kind,
  data,
  canManage,
  onAction: onCardAction,
}: {
  kind: DetailItem["kind"];
  data: DetailItem["data"];
  canManage: boolean;
  onAction: (item: DetailItem, action: CardAction) => void;
}) {
  const item = useMemo(() => ({ kind, data }) as DetailItem, [kind, data]);
  const onAction = (action: CardAction) => onCardAction(item, action);
  const draggable = useDraggable({ id: `drag-${item.kind}:${item.data.id}`, data: { kind: item.kind, id: item.data.id } });
  const fmt = item.kind === "stylesheet" ? (item.data.source_format ?? "css") : null;
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
      {item.kind === "image" ? <ImageThumbnail image={item.data} /> : <StylesheetHead sheet={item.data} />}
      <div className="card-top items-center">
        <h3 className="card-name">{item.data.name}</h3>
        <span className="ml-auto flex shrink-0 items-center gap-1">
          <span className={`badge ${item.kind === "image" ? "badge-docx" : fmt === "css" ? "badge-html" : "badge-xlsx"}`}>
            {item.kind === "image" ? item.data.file_ext : STYLE_LABEL[fmt ?? "css"]}
          </span>
          <CardMenu label={data.name} canManage={canManage} onAction={onAction} />
        </span>
      </div>
    </article>
  );
});

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

  // Only state setters inside, so one function for the pane's whole life -- the memoized cards keep it.
  const act = useCallback((item: DetailItem, action: CardAction) => {
    if (action === "copy") {
      void navigator.clipboard?.writeText(`{{ resource('${item.data.name}') }}`).then(() => {
        setCopied(item.data.id);
        window.setTimeout(() => setCopied(null), 1500);
      });
      return;
    }
    setOpen({ item, action: action === "open" ? null : action });
  }, []);

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
        <div className="card-grid resource-grid">
          {show("templates") &&
            reports.map((r) => (
              <div key={r.report_id} className="resource-grid-cell">
                <ReportCard report={r} />
              </div>
            ))}
          {show("templates") &&
            shortcuts.map(({ shortcut, report }) => (
              <div key={shortcut.id} className="resource-grid-cell">
                <ShortcutCard shortcutId={shortcut.id} report={report} canManage={canManage} onRemove={onRemoveShortcut} />
              </div>
            ))}
          {files.map((item) => (
            <div key={`${item.kind}-${item.data.id}`} className="resource-grid-cell relative">
              <FileCard kind={item.kind} data={item.data} canManage={canManage} onAction={act} />
              {copied === item.data.id && (
                <span className="resource-copied-badge pointer-events-none rounded-full bg-accent px-2 py-0.5 text-[0.72rem] text-accent-ink">Copied</span>
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
