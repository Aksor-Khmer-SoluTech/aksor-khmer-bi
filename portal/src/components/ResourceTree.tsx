import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";
import { Package } from "lucide-react";
import { ChevronIcon, FolderIcon, FolderOpenIcon, GripIcon, MoreIcon } from "../admin/icons";
import type { Folder } from "../types";
import FloatingMenu from "./FloatingMenu";

type Props = {
  childrenByParent: Map<string | null, Folder[]>;
  selectedFolderId: string | null;
  expanded: Set<string>;
  canManageRoot: boolean;
  onSelect: (id: string | null) => void;
  onToggleExpanded: (id: string) => void;
  onCreateFolder: (name: string, parentFolderId: string | null) => void;
  onRenameFolder: (id: string, name: string) => void;
  onDeleteFolder: (id: string) => void;
  onManageAccess: (id: string) => void;
  /** Projects (api/app/projects.py): mark a top-level folder as one, and export it. */
  canTransfer: boolean;
  onSetProject: (id: string, isProject: boolean) => void;
  onExportProject: (id: string) => void;
};

/** The folder tree — deliberately not a traditional indented-lines
 * explorer: indentation is padding only, a hover-reveal "…" row menu
 * instead of a row of permanently-visible icon buttons, smooth
 * expand/collapse, and a left-accent + tint on the active/drag-over row
 * instead of heavy borders. Each row is simultaneously a drag source
 * (move this folder) and a drop target (receive a folder/report/image),
 * via @dnd-kit's core `useDraggable`/`useDroppable` — this is a
 * reparenting interaction, not a linear reorder, so the lower-level
 * hooks fit better here than `@dnd-kit/sortable`'s list-oriented API. */
export default function ResourceTree(props: Props) {
  const { childrenByParent, canManageRoot, onSelect, onCreateFolder } = props;
  const [creatingRoot, setCreatingRoot] = useState(false);
  const [rootMenu, setRootMenu] = useState<{ x: number; y: number } | null>(null);
  // F2 renames the selected folder, as in a file manager (a nonce, so pressing it again re-opens the field).
  const [renameRequest, setRenameRequest] = useState<{ id: string; at: number } | null>(null);
  const rootDroppable = useDroppable({ id: "drop:root", data: { folderId: null } });

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "F2" || !props.selectedFolderId) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true'], dialog[open]")) return;
      e.preventDefault();
      setRenameRequest({ id: props.selectedFolderId, at: Date.now() });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.selectedFolderId]);

  return (
    <div className="resource-tree">
      <div className="resource-tree-header">
        <span className="sidebar-label" style={{ padding: "2px 0" }}>
          Folders
        </span>
        {canManageRoot && (
          // A "+" that widens into "+ New folder" on hover or focus, so it says what it does.
          <button
            type="button"
            className="group btn btn-ghost btn-sm gap-0 px-2 hover:gap-1.5 focus-visible:gap-1.5"
            title="New root folder"
            aria-label="New root folder"
            onClick={() => setCreatingRoot(true)}
          >
            <span aria-hidden="true">+</span>
            <span className="max-w-0 overflow-hidden whitespace-nowrap opacity-0 transition-[max-width,opacity] duration-200 ease-out group-hover:max-w-[7rem] group-hover:opacity-100 group-focus-visible:max-w-[7rem] group-focus-visible:opacity-100">
              New folder
            </span>
          </button>
        )}
      </div>

      <div
        ref={rootDroppable.setNodeRef}
        className={`resource-row ${props.selectedFolderId === null ? "active" : ""} ${rootMenu ? "menu-target" : ""} ${rootDroppable.isOver ? "drop-target" : ""}`}
        onClick={() => onSelect(null)}
        onContextMenu={(e) => {
          if (!canManageRoot) return; // nothing to offer: leave the browser's own menu
          e.preventDefault();
          // Only the menu: the open folder stays as it is (a click opens Root).
          setRootMenu({ x: e.clientX, y: e.clientY });
        }}
      >
        <span className="resource-row-grip" aria-hidden="true" />
        <span className="tree-chevron" aria-hidden="true" />
        <FolderOpenIcon />
        <span className="resource-row-name">Root</span>
      </div>

      <div className="resource-tree-children">
        {(childrenByParent.get(null) ?? []).map((folder) => (
          <FolderRow key={folder.id} folder={folder} depth={0} renameRequest={renameRequest} {...props} />
        ))}
        {creatingRoot && (
          <NewFolderInput
            depth={0}
            onSubmit={(name) => {
              onCreateFolder(name, null);
              setCreatingRoot(false);
            }}
            onCancel={() => setCreatingRoot(false)}
          />
        )}
      </div>

      {rootMenu && (
        <FloatingMenu x={rootMenu.x} y={rootMenu.y} label="Root" onClose={() => setRootMenu(null)}>
          {(close) => (
            <button type="button" role="menuitem" className="account-item" onClick={() => { close(); setCreatingRoot(true); }}>
              New folder
            </button>
          )}
        </FloatingMenu>
      )}
    </div>
  );
}

function FolderRow({
  folder,
  depth,
  childrenByParent,
  selectedFolderId,
  expanded,
  onSelect,
  onToggleExpanded,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  onManageAccess,
  canTransfer,
  onSetProject,
  onExportProject,
  renameRequest,
}: Props & { folder: Folder; depth: number; renameRequest: { id: string; at: number } | null }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [contextAt, setContextAt] = useState<{ x: number; y: number } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(folder.name);
  const [creatingChild, setCreatingChild] = useState(false);

  const isOpen = expanded.has(folder.id);
  const children = childrenByParent.get(folder.id) ?? [];
  const hasChildren = children.length > 0;

  const draggable = useDraggable({ id: `drag-folder:${folder.id}`, data: { kind: "folder", id: folder.id } });
  const droppable = useDroppable({ id: `drop-folder:${folder.id}`, data: { folderId: folder.id } });

  useEffect(() => {
    if (renameRequest?.id !== folder.id) return;
    setRenameValue(folder.name);
    setRenaming(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when a new request arrives
  }, [renameRequest]);

  const actions: FolderActions = {
    onRename: () => {
      setRenameValue(folder.name);
      setRenaming(true);
    },
    onNewSubfolder: () => {
      setCreatingChild(true);
      if (!isOpen) onToggleExpanded(folder.id);
    },
    onManageAccess: () => onManageAccess(folder.id),
    onDelete: () => onDeleteFolder(folder.id),
    project: depth === 0 ? { is: !!folder.is_project, canTransfer, onSet: (v) => onSetProject(folder.id, v), onExport: () => onExportProject(folder.id) } : null,
  };

  function submitRename() {
    const trimmed = renameValue.trim();
    if (trimmed && trimmed !== folder.name) onRenameFolder(folder.id, trimmed);
    setRenaming(false);
  }

  return (
    <div>
      <div
        ref={(el) => {
          draggable.setNodeRef(el);
          droppable.setNodeRef(el);
        }}
        className={`resource-row ${selectedFolderId === folder.id ? "active" : ""} ${contextAt || menuOpen ? "menu-target" : ""} ${droppable.isOver ? "drop-target" : ""}`}
        style={{ paddingLeft: 12 + depth * 18, opacity: draggable.isDragging ? 0.4 : 1 }}
        onClick={() => onSelect(folder.id)}
        onContextMenu={(e) => {
          if (renaming) return; // the rename field keeps the browser's own menu (paste…)
          e.preventDefault();
          e.stopPropagation();
          // Only the menu, as in a file manager: the open folder and its content stay as they are; the row is outlined
          // so it's clear which folder the menu is for. A click opens it.
          setMenuOpen(false);
          setContextAt({ x: e.clientX, y: e.clientY });
        }}
      >
        <button
          type="button"
          className="resource-row-grip"
          {...draggable.listeners}
          {...draggable.attributes}
          onClick={(e) => e.stopPropagation()}
          title="Drag to move"
        >
          <GripIcon />
        </button>
        <button
          type="button"
          className="tree-chevron"
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpanded(folder.id);
          }}
          style={{ visibility: hasChildren ? "visible" : "hidden" }}
        >
          {/* The icon points left; turned to point right when closed and down when open. */}
          <span className={`chevron ${isOpen ? "-rotate-90" : "rotate-180"}`}>
            <ChevronIcon />
          </span>
        </button>
        {folder.is_project ? <Package size={16} className="shrink-0 text-accent-strong" aria-label="Project" /> : isOpen ? <FolderOpenIcon /> : <FolderIcon />}
        {renaming ? (
          <input
            autoFocus
            className="resource-row-rename"
            value={renameValue}
            // The whole name selected, as in a file manager: typing replaces it, an arrow key keeps it.
            onFocus={(e) => e.target.select()}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setRenameValue(e.target.value)}
            onBlur={submitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitRename();
              if (e.key === "Escape") {
                setRenameValue(folder.name);
                setRenaming(false);
              }
            }}
          />
        ) : (
          <span className="resource-row-name">
            {folder.name}
            {folder.is_project && (
              <span className="ml-1.5 rounded-[4px] bg-accent-soft px-1 py-[1px] align-[1px] font-mono text-[0.6rem] font-semibold tracking-[0.06em] text-accent-strong uppercase">
                Project
              </span>
            )}
          </span>
        )}

        <RowMenu open={menuOpen} onOpenChange={setMenuOpen} actions={actions} label={folder.name} />
      </div>
      {contextAt && (
        <FloatingMenu x={contextAt.x} y={contextAt.y} label={folder.name} onClose={() => setContextAt(null)}>
          {(close) => <FolderMenuItems actions={actions} close={close} />}
        </FloatingMenu>
      )}

      {isOpen && (
        <div className="resource-tree-children">
          {children.map((child) => (
            <FolderRow
              key={child.id}
              folder={child}
              depth={depth + 1}
              childrenByParent={childrenByParent}
              selectedFolderId={selectedFolderId}
              expanded={expanded}
              canManageRoot={false}
              onSelect={onSelect}
              onToggleExpanded={onToggleExpanded}
              onCreateFolder={onCreateFolder}
              onRenameFolder={onRenameFolder}
              onDeleteFolder={onDeleteFolder}
              onManageAccess={onManageAccess}
              canTransfer={canTransfer}
              onSetProject={onSetProject}
              onExportProject={onExportProject}
              renameRequest={renameRequest}
            />
          ))}
          {creatingChild && (
            <NewFolderInput
              depth={depth + 1}
              onSubmit={(name) => {
                onCreateFolder(name, folder.id);
                setCreatingChild(false);
              }}
              onCancel={() => setCreatingChild(false)}
            />
          )}
        </div>
      )}
    </div>
  );
}

function NewFolderInput({ depth, onSubmit, onCancel }: { depth: number; onSubmit: (name: string) => void; onCancel: () => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="resource-row resource-row-new" style={{ paddingLeft: 12 + depth * 18 }}>
      <span className="resource-row-grip" aria-hidden="true" />
      <span className="tree-chevron" aria-hidden="true" />
      <FolderIcon />
      <input
        autoFocus
        className="resource-row-rename"
        placeholder="Folder name…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => (value.trim() ? onSubmit(value.trim()) : onCancel())}
        onKeyDown={(e) => {
          if (e.key === "Enter") (value.trim() ? onSubmit(value.trim()) : onCancel());
          if (e.key === "Escape") onCancel();
        }}
      />
    </div>
  );
}

type FolderActions = {
  onRename: () => void;
  onNewSubfolder: () => void;
  onManageAccess: () => void;
  onDelete: () => void;
  /** Only for a top-level folder -- a project is always one. */
  project: { is: boolean; canTransfer: boolean; onSet: (isProject: boolean) => void; onExport: () => void } | null;
};

/** A folder's actions -- the same list in its "…" menu and its right-click menu. */
function FolderMenuItems({ actions, close }: { actions: FolderActions; close: () => void }) {
  const item = (label: string, run: () => void, danger = false) => (
    <button
      type="button"
      role="menuitem"
      className={danger ? "account-item account-item-danger" : "account-item"}
      onClick={() => {
        close();
        run();
      }}
    >
      {label}
    </button>
  );
  const { project } = actions;
  return (
    <>
      {item("New subfolder", actions.onNewSubfolder)}
      {item("Rename", actions.onRename)}
      {item("Manage access", actions.onManageAccess)}
      {project && (
        <>
          <div className="account-divider" />
          {project.is && project.canTransfer && item("Export project…", project.onExport)}
          {item(project.is ? "Stop being a project" : "Make it a project", () => project.onSet(!project.is))}
        </>
      )}
      <div className="account-divider" />
      {item("Delete", actions.onDelete, true)}
    </>
  );
}

/** The row's "…" button: the same menu as a right-click, opened under the button. On top of the page (not inside the
 * tree), so the tree's scrolling box can't cut it off. */
function RowMenu({ open, onOpenChange, actions, label }: { open: boolean; onOpenChange: (open: boolean) => void; actions: FolderActions; label: string }) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <div className="resource-row-menu">
      <button
        ref={trigger}
        type="button"
        className="resource-row-menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          const r = e.currentTarget.getBoundingClientRect();
          setAt({ x: r.right - 200, y: r.bottom + 4 });
          onOpenChange(!open);
        }}
        title="More (or right-click the folder)"
      >
        <MoreIcon />
      </button>
      {open && at && (
        <FloatingMenu x={at.x} y={at.y} label={label} onClose={() => onOpenChange(false)} ignore={trigger.current}>
          {(close) => <FolderMenuItems actions={actions} close={close} />}
        </FloatingMenu>
      )}
    </div>
  );
}
