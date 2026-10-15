import { useEffect, useMemo, useRef, useState } from "react";
import { FileCode2, FileSpreadsheet, FileText, FolderInput, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { api, ApiError } from "../api";
import { useDialogRef } from "../hooks";
import type { Folder, ImageResource, ResourceUsage, StylesheetResource, TemplateExt } from "../types";
import CopyButton from "./CopyButton";
import FolderPicker from "./FolderPicker";
import ModalClose from "./ModalClose";

/** One image or stylesheet, opened from its card in Manage → Resources: what it is, how a template uses it (the exact
 * line to paste, its id), which templates already do, and what you can do with it -- replace, rename, move, delete.
 * The answer to "what's the URL of this logo?": there isn't one -- a template names it (html) or points at its id
 * (Word data), and Aksor puts the file in itself. */

export type DetailItem = { kind: "image"; data: ImageResource } | { kind: "stylesheet"; data: StylesheetResource };

export const STYLE_LABEL = { css: "CSS", scss: "SCSS", sass: "Sass", less: "Less" } as const;
const IMAGE_ACCEPT = "image/*";
const STYLE_ACCEPT = ".css,.scss,.sass,.less";
const EXT_ICON: Record<TemplateExt, typeof FileText> = { docx: FileText, xlsx: FileSpreadsheet, html: FileCode2 };

export function folderPath(folders: Folder[], id: string | null): string {
  const parts: string[] = [];
  let cursor = id ? folders.find((f) => f.id === id) : undefined;
  while (cursor) {
    parts.unshift(cursor.name);
    const parent = cursor.parent_folder_id;
    cursor = parent ? folders.find((f) => f.id === parent) : undefined;
  }
  return parts.join(" / ") || "Root";
}

function Snippet({ label, code, hint }: { label: string; code: string; hint?: string }) {
  return (
    <div className="grid gap-1">
      <span className="text-[0.76rem] text-text-faint">{label}</span>
      <div className="relative">
        <pre className="m-0 overflow-x-auto rounded-[8px] border border-border-soft bg-bg-panel py-2.5 pr-16 pl-3 font-mono text-[0.78rem] leading-[1.5]">{code}</pre>
        <CopyButton text={code} />
      </div>
      {hint && <span className="text-[0.74rem] text-text-faint">{hint}</span>}
    </div>
  );
}

export default function ResourceDetails({
  item,
  folders,
  canManage,
  initialAction,
  onChanged,
  onDeleted,
  onClose,
}: {
  item: DetailItem;
  folders: Folder[];
  canManage: boolean;
  /** Opened from a card menu's Replace / Move / Delete: start there. */
  initialAction?: "replace" | "move" | "delete" | null;
  onChanged: (item: DetailItem) => void;
  onDeleted: (kind: DetailItem["kind"], id: string) => void;
  onClose: () => void;
}) {
  const ref = useDialogRef(true);
  const { kind, data } = item;
  const [usage, setUsage] = useState<ResourceUsage[] | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [css, setCss] = useState<{ source?: string; compiled?: string; tab: "source" | "compiled" }>({ tab: "source" });
  const [moving, setMoving] = useState(initialAction === "move");
  const [moveTo, setMoveTo] = useState<string | null>(data.folder_id);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(data.name);
  const [confirmDelete, setConfirmDelete] = useState(initialAction === "delete");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const fmt = kind === "stylesheet" ? (data.source_format ?? "css") : null;

  useEffect(() => {
    (kind === "image" ? api.images.usage(data.id) : api.stylesheets.usage(data.id)).then(setUsage).catch(() => setUsage([]));
  }, [kind, data.id]);

  useEffect(() => {
    let url: string | null = null;
    if (kind === "image") {
      api.images
        .fileBlob(data.id)
        .then((blob) => {
          url = URL.createObjectURL(blob);
          setPreview(url);
        })
        .catch(() => setPreview(null));
    } else {
      void Promise.all([api.stylesheets.source(data.id), fmt !== "css" ? api.stylesheets.css(data.id) : Promise.resolve(undefined)]).then(([source, compiled]) =>
        setCss((c) => ({ ...c, source, compiled })),
      );
    }
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [kind, data.id, data.updated_at, fmt]);

  useEffect(() => {
    if (initialAction === "replace") fileRef.current?.click();
  }, [initialAction]);

  const where = useMemo(() => folderPath(folders, data.folder_id), [folders, data.folder_id]);

  async function run(action: () => Promise<DetailItem | null>) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      if (next) onChanged(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work — try again");
    } finally {
      setBusy(false);
    }
  }

  const replace = (file: File | undefined) =>
    file &&
    run(async () =>
      kind === "image" ? { kind, data: await api.images.replace(data.id, file) } : { kind, data: await api.stylesheets.replace(data.id, file) },
    );
  const move = () =>
    run(async () => {
      const next = kind === "image" ? { kind, data: await api.images.update(data.id, { folder_id: moveTo }) } : { kind, data: await api.stylesheets.update(data.id, { folder_id: moveTo }) };
      setMoving(false);
      return next as DetailItem;
    });
  const rename = () =>
    name.trim() && name.trim() !== data.name
      ? run(async () => {
          const next = kind === "image" ? { kind, data: await api.images.update(data.id, { name: name.trim() }) } : { kind, data: await api.stylesheets.update(data.id, { name: name.trim() }) };
          setRenaming(false);
          return next as DetailItem;
        })
      : setRenaming(false);
  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await (kind === "image" ? api.images.delete(data.id) : api.stylesheets.delete(data.id));
      onDeleted(kind, data.id);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete it");
      setBusy(false);
    }
  }

  const sizeText = data.size_bytes < 1024 ? `${data.size_bytes} B` : `${(data.size_bytes / 1024).toFixed(1)} KB`;
  const meta =
    kind === "image"
      ? `${(item.data as ImageResource).file_ext.toUpperCase()} · ${(item.data as ImageResource).width_px}×${(item.data as ImageResource).height_px} · ${sizeText}`
      : `${STYLE_LABEL[fmt ?? "css"]} · ${sizeText} of CSS`;

  return (
    <dialog ref={ref} className="modal modal-wide" onCancel={onClose} onClose={onClose}>
      <ModalClose />
      <div className="mb-3 flex items-center gap-3 pr-8">
        {kind === "image" ? (
          <div className="grid h-14 w-20 shrink-0 place-items-center overflow-hidden rounded-[8px] border border-border-soft bg-bg-panel">
            {preview ? <img src={preview} alt="" className="max-h-full max-w-full object-contain" /> : <span className="muted">…</span>}
          </div>
        ) : (
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-[8px] border border-border-soft bg-bg-panel font-mono text-[0.72rem] font-semibold text-text-dim">
            {STYLE_LABEL[fmt ?? "css"]}
          </span>
        )}
        <div className="min-w-0 flex-1">
          {renaming ? (
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => void rename()}
              onKeyDown={(e) => {
                if (e.key === "Enter") void rename();
                if (e.key === "Escape") {
                  setName(data.name);
                  setRenaming(false);
                }
              }}
              aria-label="Name"
            />
          ) : (
            <h2 className="panel-title m-0 flex items-center gap-2">
              <span className="truncate">{data.name}</span>
              {canManage && (
                <button type="button" className="btn btn-ghost btn-sm icon-only" aria-label="Rename" onClick={() => setRenaming(true)}>
                  <Pencil size={13} />
                </button>
              )}
            </h2>
          )}
          <p className="muted m-0 text-[0.82rem]">
            {meta} · in {where}
          </p>
        </div>
      </div>

      {error && <p className="alert alert-error">{error}</p>}

      <div className="grid gap-4">
        <section className="grid gap-2.5">
          <h3 className="docs-home-label m-0">Use it in a template</h3>
          {kind === "image" ? (
            <>
              <Snippet label="HTML template" code={`<img src="{{ resource('${data.name}') }}" alt="">`} hint="When you register the template, map this name to this image." />
              <Snippet label="Word template — in its data" code={`{"LOGO": {"image_id": "${data.id}", "width_mm": 40}}`} hint="Type {{ LOGO }} where the picture goes. A picture that never changes can just be pasted into the Word file." />
            </>
          ) : (
            <Snippet label="HTML template" code={`<link rel="stylesheet" href="{{ resource('${data.name}') }}">`} hint="When you register the template, map this name to this stylesheet." />
          )}
        </section>

        {kind === "stylesheet" && (
          <section className="grid gap-2">
            <div className="flex items-center gap-2">
              <h3 className="docs-home-label m-0 flex-1">{fmt === "css" ? "CSS" : "Source and compiled CSS"}</h3>
              {fmt !== "css" && (
                <div className="segmented segmented-sm" role="tablist">
                  <button type="button" className={`segmented-btn${css.tab === "source" ? " active" : ""}`} onClick={() => setCss((c) => ({ ...c, tab: "source" }))}>
                    {STYLE_LABEL[fmt ?? "css"]}
                  </button>
                  <button type="button" className={`segmented-btn${css.tab === "compiled" ? " active" : ""}`} onClick={() => setCss((c) => ({ ...c, tab: "compiled" }))}>
                    Compiled CSS
                  </button>
                </div>
              )}
            </div>
            <pre className="m-0 max-h-[34vh] overflow-auto rounded-[8px] border border-border-soft bg-bg-panel p-3 font-mono text-[0.76rem] leading-[1.5]">
              {(css.tab === "source" || fmt === "css" ? css.source : css.compiled) ?? "Loading…"}
            </pre>
          </section>
        )}

        <section className="grid gap-1.5">
          <h3 className="docs-home-label m-0">Used by</h3>
          {usage === null ? (
            <span className="muted text-[0.84rem]">Looking…</span>
          ) : usage.length === 0 ? (
            <span className="muted text-[0.84rem]">No template uses it yet.</span>
          ) : (
            <ul className="m-0 grid list-none gap-1 p-0">
              {usage.map((u) => {
                const Icon = EXT_ICON[u.template_ext] ?? FileText;
                return (
                  <li key={u.report_id} className="flex items-center gap-2 text-[0.88rem]">
                    <Icon size={14} className="shrink-0 text-text-faint" aria-hidden="true" />
                    <a href={`#/reports/${encodeURIComponent(u.report_id)}`}>{u.name}</a>
                    <span className="text-[0.78rem] text-text-faint">
                      {[u.as.length ? `as ${u.as.map((n) => `'${n}'`).join(", ")}` : "", u.in_data ? "in its data" : ""].filter(Boolean).join(" · ")}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {canManage && moving && (
          <section className="grid gap-2 rounded-[10px] border border-border-soft p-3">
            <FolderPicker value={moveTo} onChange={setMoveTo} folders={folders} label="Move to" hint={null} />
            <div className="flex gap-2">
              <button type="button" className="btn btn-sm btn-primary" disabled={busy || moveTo === data.folder_id} onClick={() => void move()}>
                Move here
              </button>
              <button type="button" className="btn btn-sm" onClick={() => setMoving(false)}>
                Cancel
              </button>
            </div>
          </section>
        )}

        {canManage && confirmDelete && (
          <div className="alert alert-warning flex flex-wrap items-center gap-2">
            <span className="min-w-0 flex-1">
              {usage?.length
                ? `${usage.length} template${usage.length === 1 ? " uses" : "s use"} it — they won't render until they're given another. Delete anyway?`
                : "Delete it? This can't be undone."}
            </span>
            <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={() => void remove()}>
              Delete
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setConfirmDelete(false)}>
              Keep it
            </button>
          </div>
        )}
      </div>

      <div className="dialog-actions">
        {canManage && (
          <>
            <input ref={fileRef} type="file" accept={kind === "image" ? IMAGE_ACCEPT : STYLE_ACCEPT} className="hidden" onChange={(e) => void replace(e.target.files?.[0])} />
            <button type="button" className="btn btn-ghost mr-auto text-danger" onClick={() => setConfirmDelete(true)} disabled={busy}>
              <Trash2 size={14} aria-hidden="true" /> Delete
            </button>
            <button type="button" className="btn" onClick={() => setMoving((m) => !m)} disabled={busy}>
              <FolderInput size={14} aria-hidden="true" /> Move
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              title={usage?.length ? `Every template using it changes too (${usage.length})` : undefined}
            >
              {busy ? <span className="spinner" /> : <RefreshCw size={14} aria-hidden="true" />} Replace
            </button>
          </>
        )}
        <button type="button" className="btn btn-primary" onClick={onClose}>
          Done
        </button>
      </div>
    </dialog>
  );
}
