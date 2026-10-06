import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";
import { ChevronIcon, FolderIcon, FolderOpenIcon, GripIcon, MoreIcon } from "../admin/icons";
import type { Folder } from "../types";

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
  const rootDroppable = useDroppable({ id: "drop:root", data: { folderId: null } });

  return (
    <div className="resource-tree">
      <div className="resource-tree-header">
        <span className="sidebar-label" style={{ padding: "2px 0" }}>
          Folders
        </span>
        {canManageRoot && (
          <button type="button" className="btn btn-ghost btn-sm icon-only" title="New root folder" onClick={() => setCreatingRoot(true)}>
            +
          </button>
        )}
      </div>

      <div
        ref={rootDroppable.setNodeRef}
        className={`resource-row ${props.selectedFolderId === null ? "active" : ""} ${rootDroppable.isOver ? "drop-target" : ""}`}
        onClick={() => onSelect(null)}
      >
        <span className="resource-row-grip" aria-hidden="true" />
        <span className="tree-chevron" aria-hidden="true" />
        <FolderOpenIcon />
        <span className="resource-row-name">All Resources</span>
      </div>

      <div className="resource-tree-children">
        {(childrenByParent.get(null) ?? []).map((folder) => (
          <FolderRow key={folder.id} folder={folder} depth={0} {...props} />
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
}: Props & { folder: Folder; depth: number }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(folder.name);
  const [creatingChild, setCreatingChild] = useState(false);

  const isOpen = expanded.has(folder.id);
  const children = childrenByParent.get(folder.id) ?? [];
  const hasChildren = children.length > 0;

  const draggable = useDraggable({ id: `drag-folder:${folder.id}`, data: { kind: "folder", id: folder.id } });
  const droppable = useDroppable({ id: `drop-folder:${folder.id}`, data: { folderId: folder.id } });

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
        className={`resource-row ${selectedFolderId === folder.id ? "active" : ""} ${droppable.isOver ? "drop-target" : ""}`}
        style={{ paddingLeft: 12 + depth * 18, opacity: draggable.isDragging ? 0.4 : 1 }}
        onClick={() => onSelect(folder.id)}
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
          <span className={isOpen ? "chevron chevron-flipped" : "chevron"}>
            <ChevronIcon />
          </span>
        </button>
        {isOpen ? <FolderOpenIcon /> : <FolderIcon />}
        {renaming ? (
          <input
            autoFocus
            className="resource-row-rename"
            value={renameValue}
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
          <span className="resource-row-name">{folder.name}</span>
        )}

        <RowMenu
          open={menuOpen}
          onOpenChange={setMenuOpen}
          onRename={() => {
            setRenameValue(folder.name);
            setRenaming(true);
          }}
          onNewSubfolder={() => {
            setCreatingChild(true);
            if (!isOpen) onToggleExpanded(folder.id);
          }}
          onManageAccess={() => onManageAccess(folder.id)}
          onDelete={() => onDeleteFolder(folder.id)}
        />
      </div>

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

function RowMenu({
  open,
  onOpenChange,
  onRename,
  onNewSubfolder,
  onManageAccess,
  onDelete,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRename: () => void;
  onNewSubfolder: () => void;
  onManageAccess: () => void;
  onDelete: () => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) onOpenChange(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, onOpenChange]);

  return (
    <div className="resource-row-menu" ref={rootRef}>
      <button
        type="button"
        className="resource-row-menu-trigger"
        onClick={(e) => {
          e.stopPropagation();
          onOpenChange(!open);
        }}
        title="More"
      >
        <MoreIcon />
      </button>
      {open && (
        <div className="account-panel resource-row-panel" role="menu" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="account-item"
            onClick={() => {
              onOpenChange(false);
              onNewSubfolder();
            }}
          >
            New subfolder
          </button>
          <button
            type="button"
            className="account-item"
            onClick={() => {
              onOpenChange(false);
              onRename();
            }}
          >
            Rename
          </button>
          <button
            type="button"
            className="account-item"
            onClick={() => {
              onOpenChange(false);
              onManageAccess();
            }}
          >
            Manage access
          </button>
          <div className="account-divider" />
          <button
            type="button"
            className="account-item account-item-danger"
            onClick={() => {
              onOpenChange(false);
              onDelete();
            }}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
