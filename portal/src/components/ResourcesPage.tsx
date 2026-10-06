import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { has } from "../admin/sections";
import { FolderIcon, ImageIcon, TemplatesIcon } from "../admin/icons";
import type { AuthInfo, Folder, ImageResource, ReportMeta } from "../types";
import FolderGrantsDialog from "./FolderGrantsDialog";
import ResourceTree from "./ResourceTree";
import ResourceContentPane from "./ResourceContentPane";
import { CardGridSkeleton, TreeSkeleton } from "./Skeletons";

type DragKind = "folder" | "report" | "image";
type DraggedItem = { kind: DragKind; id: string; label: string };

/** The Resources repository — a JasperReports-Server-style folder tree
 * holding report templates and uploaded images, drag-and-drop to
 * reorganize, per-folder role/user access grants. Two panes sharing one
 * DndContext: the tree on the left is both drag source (moving a folder)
 * and drop target (receiving a folder/report/image); the content pane on
 * the right is drag source only (its cards move *into* a tree folder,
 * never receive drops themselves). */
export default function ResourcesPage({ auth }: { auth: AuthInfo }) {
  const [folders, setFolders] = useState<Folder[] | null>(null);
  const [reports, setReports] = useState<ReportMeta[] | null>(null);
  const [images, setImages] = useState<ImageResource[] | null>(null);
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

  function load() {
    Promise.all([api.folders.list(), api.listReports(), api.images.list()])
      .then(([f, r, i]) => {
        setFolders(f);
        setReports(r);
        setImages(i);
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

  const reportsInFolder = (reports ?? []).filter((r) => r.folder_id === selectedFolderId);
  const imagesInFolder = (images ?? []).filter((i) => i.folder_id === selectedFolderId);

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
          : images?.find((i) => i.id === dragged.id)?.name;
    setActiveDrag({ kind: dragged.kind, id: dragged.id, label: label ?? "" });
  }

  async function handleDragEnd(event: DragEndEvent) {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;
    const dragged = active.data.current as { kind: "folder" | "report" | "image"; id: string } | undefined;
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
      } else {
        // No move-image endpoint exists (images are folder-scoped at
        // upload time) — re-upload-to-move isn't worth building for a
        // first pass, so an image drag currently only reorders visually
        // within its own folder pane, never actually moves between
        // folders. Left as a known gap rather than a silent failure:
        setMoveError("Moving an existing image between folders isn't supported yet — delete and re-upload it into the new folder.");
        return;
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

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd} onDragCancel={() => setActiveDrag(null)}>
      <div className="resources-page">
        <div className="page-header">
          <div>
            <h1 className="page-title">Resources</h1>
            <p className="page-subtitle">Organize report templates and images into folders — drag items between them.</p>
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
          />

          <ResourceContentPane
            folder={selectedFolder}
            reports={reportsInFolder}
            images={imagesInFolder}
            canManage={canManageSelected}
            orgId={auth.orgId ?? "root"}
            onImageUploaded={(img) => setImages((prev) => [...(prev ?? []), img])}
            onImageDeleted={(id) => setImages((prev) => prev?.filter((i) => i.id !== id) ?? null)}
          />
        </div>

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
