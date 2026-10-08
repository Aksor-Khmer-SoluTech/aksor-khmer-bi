import { useState, type CSSProperties, type ReactNode } from "react";
import { ChevronRight, Folder, FolderOpen } from "lucide-react";
import type { ReportTree, TreeEntry, TreeFolder } from "../reportTree";

/** The Reports page's tree layout: reports under the Resources folders they're filed in, nested as deep as the
 * folders are. Which folders are collapsed is remembered per account in this browser; while a search is active
 * every branch that still has a match is open, whatever was collapsed. */
const keyFor = (username: string, scope: string) => `portal_${scope}_tree_collapsed:${username}`;

function readCollapsed(username: string, scope: string): Set<string> {
  try {
    const value = JSON.parse(localStorage.getItem(keyFor(username, scope)) ?? "[]");
    return new Set(Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : []);
  } catch {
    return new Set();
  }
}

export function useTreeCollapsed(username: string, scope = "reports") {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => readCollapsed(username, scope));
  const save = (next: Set<string>) => {
    setCollapsed(next);
    try {
      localStorage.setItem(keyFor(username, scope), JSON.stringify([...next]));
    } catch {
      // best-effort only -- the folders just open again next time
    }
  };
  return {
    collapsed,
    toggle: (id: string) => {
      const next = new Set(collapsed);
      if (!next.delete(id)) next.add(id);
      save(next);
    },
    collapseAll: (ids: string[]) => save(new Set(ids)),
    expandAll: () => save(new Set()),
  };
}

export default function ReportsTree<T>({
  tree,
  collapsed,
  forceOpen,
  onToggle,
  renderReport,
  idOf,
}: {
  tree: ReportTree<T>;
  collapsed: Set<string>;
  forceOpen: boolean;
  onToggle: (id: string) => void;
  renderReport: (item: T, index: number, entry?: TreeEntry<T>) => ReactNode;
  idOf: (item: T) => string;
}) {
  let counter = 0;
  const next = () => counter++;

  const renderFolder = (folder: TreeFolder<T>, depth: number): ReactNode => {
    const open = forceOpen || !collapsed.has(folder.id);
    const bodyId = `rtree-${folder.id}`;
    return (
      <div key={folder.id} className={`rtree-node${open ? " open" : ""}`} role="treeitem" aria-expanded={open} aria-level={depth + 1}>
        <button type="button" className="rtree-folder" aria-expanded={open} aria-controls={bodyId} onClick={() => onToggle(folder.id)} disabled={forceOpen}>
          <ChevronRight size={15} className="rtree-chevron" aria-hidden="true" />
          {open ? <FolderOpen size={17} strokeWidth={1.7} aria-hidden="true" /> : <Folder size={17} strokeWidth={1.7} aria-hidden="true" />}
          <span className="rtree-name">{folder.name}</span>
          <span className="rtree-count" title={`${folder.total} item${folder.total === 1 ? "" : "s"} in this folder and the ones inside it`}>
            {folder.total}
          </span>
        </button>
        <div className="rtree-body" id={bodyId}>
          <div className="rtree-children" role="group" inert={!open}>
            {folder.folders.map((child) => renderFolder(child, depth + 1))}
            {folder.entries.map((entry) => (
              <div key={entry.key} className="rtree-leaf" role="treeitem" aria-level={depth + 2} style={{ "--i": next() } as CSSProperties}>
                {renderReport(entry.item, counter, entry)}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="rtree" role="tree" aria-label="Reports by folder">
      {tree.folders.map((folder) => renderFolder(folder, 0))}
      {tree.loose.length > 0 && (
        <>
          {tree.folders.length > 0 && <div className="rtree-divider">Root</div>}
          {tree.loose.map((report) => (
            <div key={idOf(report)} className="rtree-leaf rtree-leaf-root" role="treeitem" aria-level={1}>
              {renderReport(report, next())}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
