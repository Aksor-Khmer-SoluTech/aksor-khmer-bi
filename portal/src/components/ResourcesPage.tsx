import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { has } from "../admin/sections";
import { FolderIcon, ImageIcon, TemplatesIcon } from "../admin/icons";
import type { AuthInfo, Folder, ImageResource, ReportMeta, ReportShortcut, StylesheetResource } from "../types";
import FolderGrantsDialog from "./FolderGrantsDialog";
import ResourceTree from "./ResourceTree";
import FontsPanel from "./FontsPanel";
import { ExportProjectDialog, ImportProjectDialog } from "./ProjectTransfer";
import { Download, Package, Upload } from "lucide-react";
import ResourceContentPane from "./ResourceContentPane";
import { CardGridSkeleton, TreeSkeleton } from "./Skeletons";

type DragKind = "folder" | "report" | "image" | "stylesheet";
type DraggedItem = { kind: DragKind; id: string; label: string };

/** The Resources repository — a JasperReports-Server-style folder tree
 * holding report templates and uploaded images, drag-and-drop to
 * reorganize, per-folder role/user access grants. Two panes sharing one
 * DndContext: the tree on the left is both drag source (moving a folder)
 * and drop target (receiving a folder/report/image); the content pane on
 * the right is drag source only (its cards move *into* a tree folder,
 * never receive drops themselves). */
/** One shared empty list, so an empty folder's props don't change identity on every render. */
const NONE: never[] = [];

export default function ResourcesPage({ auth }: { auth: AuthInfo }) {
  const [folders, setFolders] = useState<Folder[] | null>(null);
  const [reports, setReports] = useState<ReportMeta[] | null>(null);
  const [images, setImages] = useState<ImageResource[] | null>(null);
  const [stylesheets, setStylesheets] = useState<StylesheetResource[]>([]);
  const [shortcuts, setShortcuts] = useState<ReportShortcut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [grantsFolderId, setGrantsFolderId] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [activeDrag, setActiveDrag] = useState<DraggedItem | null>(null);

  // A plain click has near-zero pointer movement between down and up —
  // without this threshold, PointerSensor treats *every* mousedown on a
  // draggable row as the start of a drag, which swallows clicks meant
  // for nested interactive elements (the chevron, the "…" menu) before
  // they ever fire. 5px lets an intentional drag still start immediately
  // while a plain click reaches its target normally.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  const canManageRoot = has(auth, "folder:manage") || auth.isSuperuser;
  // Fonts are server-wide, so they sit beside the folder library rather than inside a folder. Anyone who manages
  // reports may look (to check a template's fonts); adding and removing needs font:manage.
  const canManageFonts = has(auth, "font:manage") || auth.isSuperuser;
  const canSeeFonts = canManageFonts || has(auth, "report:manage");
  const [section, setSection] = useState<"library" | "fonts">("library");
  // Projects: a top-level folder exported and imported as one package (api/app/projects.py).
  const canTransfer = has(auth, "project:transfer") || auth.isSuperuser;
  const [exportingId, setExportingId] = useState<string | null>(null);
  const [importing, setImporting] = useState<{ into: string | null } | null>(null);

  function load() {
    Promise.all([api.folders.list(), api.listReports(), api.images.list(), api.listShortcuts().catch(() => []), api.stylesheets.list().catch(() => [])])
      .then(([f, r, i, s, css]) => {
        setFolders(f);
        setReports(r);
        setImages(i);
        setShortcuts(s);
        setStylesheets(css);
      })
      .catch(() => setError("Couldn't load Resources — is the API reachable?"));
  }

  useEffect(load, []);

  const childrenByParent = useMemo(() => {
    const map = new Map<string | null, Folder[]>();
    for (const f of folders ?? []) {
      const key = f.parent_folder_id;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(f);
    }
    for (const list of map.values()) list.sort((a, b) => a.name.localeCompare(b.name));
    return map;
  }, [folders]);

  const selectedFolder = folders?.find((f) => f.id === selectedFolderId) ?? null;
  const canManageSelected = selectedFolder === null ? canManageRoot : true; // server re-checks regardless; see handlers below

  // Everything grouped by folder once, when the lists change -- not re-filtered on every render (a drag, a hover, a
  // menu) -- and each folder's list keeps its identity between renders, so the cards beside it don't redraw.
  const byFolder = useMemo(() => {
    const group = <T,>(items: T[], folderOf: (item: T) => string | null) => {
      const map = new Map<string | null, T[]>();
      for (const item of items) {
        const key = folderOf(item);
        const list = map.get(key);
        if (list) list.push(item);
        else map.set(key, [item]);
      }
      return map;
    };
    const reportById = new Map((reports ?? []).map((r) => [r.report_id, r]));
    return {
      reports: group(reports ?? [], (r) => r.folder_id),
      images: group(images ?? [], (i) => i.folder_id),
      stylesheets: group(stylesheets, (s) => s.folder_id),
      // A shortcut is a link to a report filed somewhere else, so it shows the original's details.
      shortcuts: group(
        shortcuts.flatMap((s) => {
          const report = reportById.get(s.report_id);
          return report ? [{ shortcut: s, report }] : [];
        }),
        (x) => x.shortcut.folder_id,
      ),
    };
  }, [reports, images, stylesheets, shortcuts]);
  const reportsInFolder = byFolder.reports.get(selectedFolderId) ?? NONE;
  const imagesInFolder = byFolder.images.get(selectedFolderId) ?? NONE;
  const stylesheetsInFolder = byFolder.stylesheets.get(selectedFolderId) ?? NONE;
  const shortcutsInFolder = byFolder.shortcuts.get(selectedFolderId) ?? NONE;

  // Stable (only setters inside), so the memoized shortcut cards keep it across renders.
  const removeShortcut = useCallback(async (id: string) => {
    setMoveError(null);
    try {
      await api.deleteShortcut(id);
      setShortcuts((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setMoveError(err instanceof ApiError ? err.message : "Couldn't remove the shortcut");
    }
  }, []);

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function createFolder(name: string, parentFolderId: string | null) {
    setMoveError(null);
    try {
      const created = await api.folders.create({ org_id: auth.orgId ?? "root", name, parent_folder_id: parentFolderId });
      setFolders((prev) => [...(prev ?? []), created]);
      if (parentFolderId) setExpanded((prev) => new Set(prev).add(parentFolderId));
    } catch (err) {
      setMoveError(err instanceof ApiError ? err.message : "Couldn't create folder");
    }
  }

  async function renameFolder(id: string, name: string) {
    setMoveError(null);
    try {
      const updated = await api.folders.update(id, { name });
      setFolders((prev) => prev?.map((f) => (f.id === id ? updated : f)) ?? null);
    } catch (err) {
      setMoveError(err instanceof ApiError ? err.message : "Couldn't rename folder");
    }
  }

  async function setProject(id: string, isProject: boolean) {
    setMoveError(null);
    try {
      const updated = await api.folders.update(id, { is_project: isProject });
      setFolders((prev) => prev?.map((f) => (f.id === id ? { ...f, ...updated } : f)) ?? null);
    } catch (err) {
      setMoveError(err instanceof ApiError ? err.message : "Couldn't change the folder");
    }
  }

  async function deleteFolder(id: string) {
    setMoveError(null);
    try {
      await api.folders.delete(id);
      setFolders((prev) => prev?.filter((f) => f.id !== id) ?? null);
      if (selectedFolderId === id) setSelectedFolderId(null);
    } catch (err) {
      setMoveError(err instanceof ApiError ? err.message : "Couldn't delete folder — is it empty?");
    }
  }

  function handleDragStart(event: DragStartEvent) {
    const dragged = event.active.data.current as { kind: DragKind; id: string } | undefined;
    if (!dragged) return;
    const label =
      dragged.kind === "folder"
        ? folders?.find((f) => f.id === dragged.id)?.name
        : dragged.kind === "report"
          ? reports?.find((r) => r.report_id === dragged.id)?.name
          : dragged.kind === "image"
            ? images?.find((i) => i.id === dragged.id)?.name
            : stylesheets.find((x) => x.id === dragged.id)?.name;
    setActiveDrag({ kind: dragged.kind, id: dragged.id, label: label ?? "" });
  }

  async function handleDragEnd(event: DragEndEvent) {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;
    const dragged = active.data.current as { kind: DragKind; id: string } | undefined;
    const target = over.data.current as { folderId: string | null } | undefined;
    if (!dragged || !target) return;
    if (dragged.kind === "folder" && dragged.id === target.folderId) return;

    setMoveError(null);
    try {
      if (dragged.kind === "folder") {
        // Dropping onto itself is already a no-op above; dropping it
        // onto one of its own descendants is rejected server-side (400)
        // and surfaces below via moveError.
        const updated = await api.folders.update(dragged.id, { parent_folder_id: target.folderId });
        setFolders((prev) => prev?.map((f) => (f.id === dragged.id ? updated : f)) ?? null);
      } else if (dragged.kind === "report") {
        const updated = await api.updateReport(dragged.id, { folder_id: target.folderId });
        setReports((prev) => prev?.map((r) => (r.report_id === dragged.id ? updated : r)) ?? null);
      } else if (dragged.kind === "image") {
        const updated = await api.images.update(dragged.id, { folder_id: target.folderId });
        setImages((prev) => prev?.map((i) => (i.id === dragged.id ? updated : i)) ?? null);
      } else {
        const updated = await api.stylesheets.update(dragged.id, { folder_id: target.folderId });
        setStylesheets((prev) => prev.map((x) => (x.id === dragged.id ? updated : x)));
      }
      // Land the drop somewhere visible instead of requiring a second
      // click to expand the folder you just dropped into.
      if (target.folderId) setExpanded((prev) => new Set(prev).add(target.folderId!));
    } catch (err) {
      setMoveError(err instanceof ApiError ? err.message : "Couldn't move item");
    }
  }

  if (error) return <p className="alert alert-error" style={{ margin: 24 }}>{error}</p>;
  if (folders === null || reports === null || images === null) {
    return (
      <div className="resources-page">
        <div className="page-header">
          <div>
            <h1 className="page-title">Resources</h1>
            <p className="page-subtitle">Organize report templates and images into folders — drag items between them.</p>
          </div>
        </div>
        <div className="resources-shell">
          <div className="resource-tree">
            <TreeSkeleton />
          </div>
          <CardGridSkeleton count={6} />
        </div>
      </div>
    );
  }

  const sectionSwitch = canSeeFonts && (
    <div className="segmented" role="group" aria-label="Resources section">
      <button type="button" className={`segmented-btn${section === "library" ? " active" : ""}`} onClick={() => setSection("library")}>
        Library
      </button>
      <button type="button" className={`segmented-btn${section === "fonts" ? " active" : ""}`} onClick={() => setSection("fonts")}>
        Fonts
      </button>
    </div>
  );

  if (section === "fonts" && canSeeFonts) {
    return (
      <div className="resources-page">
        <div className="page-header">
          <div>
            <h1 className="page-title">Resources</h1>
            <p className="page-subtitle">Fonts added for the whole server — check them here before a template depends on them.</p>
          </div>
          {sectionSwitch}
        </div>
        <FontsPanel canManage={canManageFonts} />
      </div>
    );
  }

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd} onDragCancel={() => setActiveDrag(null)}>
      <div className="resources-page">
        <div className="page-header">
          <div>
            <h1 className="page-title">Resources</h1>
            <p className="page-subtitle">Organize report templates, images and stylesheets into folders — drag items between them.</p>
          </div>
          <div className="page-header-actions flex-wrap">
            {canTransfer && (
              <button type="button" className="btn" onClick={() => setImporting({ into: null })}>
                <Upload size={14} aria-hidden="true" /> Import project
              </button>
            )}
            {sectionSwitch}
          </div>
        </div>

        {moveError && <p className="alert alert-error">{moveError}</p>}

        <div className="resources-shell">
          <ResourceTree
            childrenByParent={childrenByParent}
            selectedFolderId={selectedFolderId}
            expanded={expanded}
            canManageRoot={canManageRoot}
            onSelect={setSelectedFolderId}
            onToggleExpanded={toggleExpanded}
            onCreateFolder={createFolder}
            onRenameFolder={renameFolder}
            onDeleteFolder={deleteFolder}
            onManageAccess={setGrantsFolderId}
            canTransfer={canTransfer}
            onSetProject={setProject}
            onExportProject={setExportingId}
          />

          <div className="grid min-w-0 content-start gap-3">
          {selectedFolder?.is_project && (
            <div className="flex flex-wrap items-center gap-3 rounded-[12px] border border-accent-border bg-accent-soft px-3.5 py-2.5">
              <Package size={18} className="shrink-0 text-accent-strong" aria-hidden="true" />
              <span className="min-w-0 flex-1 text-[0.86rem] leading-snug">
                <b className="font-semibold">{selectedFolder.name}</b> is a project — its templates, images and stylesheets, with its subfolders, move to
                another server as one package.
              </span>
              {canTransfer && (
                <>
                  <button type="button" className="btn btn-sm" onClick={() => setImporting({ into: selectedFolder.id })}>
                    <Upload size={13} aria-hidden="true" /> Update from a package
                  </button>
                  <button type="button" className="btn btn-sm btn-primary" onClick={() => setExportingId(selectedFolder.id)}>
                    <Download size={13} aria-hidden="true" /> Export
                  </button>
                </>
              )}
            </div>
          )}
          <ResourceContentPane
            folder={selectedFolder}
            folders={folders}
            reports={reportsInFolder}
            images={imagesInFolder}
            stylesheets={stylesheetsInFolder}
            shortcuts={shortcutsInFolder}
            onRemoveShortcut={removeShortcut}
            canManage={canManageSelected}
            orgId={auth.orgId ?? "root"}
            onImageChanged={(img) => setImages((prev) => [...(prev ?? []).filter((i) => i.id !== img.id), img].sort((a, b) => a.name.localeCompare(b.name)))}
            onImageDeleted={(id) => setImages((prev) => prev?.filter((i) => i.id !== id) ?? null)}
            onStylesheetChanged={(sheet) => setStylesheets((prev) => [...prev.filter((s) => s.id !== sheet.id), sheet].sort((a, b) => a.name.localeCompare(b.name)))}
            onStylesheetDeleted={(id) => setStylesheets((prev) => prev.filter((s) => s.id !== id))}
          />
          </div>
        </div>

        {exportingId && <ExportProjectDialog folderId={exportingId} onClose={() => setExportingId(null)} />}
        {importing && (
          <ImportProjectDialog
            orgId={auth.orgId ?? "root"}
            projects={(folders ?? []).filter((f) => f.is_project)}
            initialInto={importing.into}
            onClose={() => setImporting(null)}
            onImported={(summary) => {
              load();
              setSelectedFolderId(summary.project.id);
            }}
          />
        )}

        {grantsFolderId && (
          <FolderGrantsDialog open folderId={grantsFolderId} onClose={() => setGrantsFolderId(null)} />
        )}
      </div>

      <DragOverlay dropAnimation={{ duration: 150, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }}>
        {activeDrag && (
          <div className="resource-drag-preview">
            {activeDrag.kind === "folder" ? <FolderIcon /> : activeDrag.kind === "report" ? <TemplatesIcon /> : <ImageIcon />}
            <span>{activeDrag.label}</span>
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}
