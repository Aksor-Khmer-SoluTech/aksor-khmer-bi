import { ChevronsDownUp, ChevronsUpDown, FolderTree, LayoutGrid, List } from "lucide-react";

export type LayoutView = "tree" | "grid" | "list";

/** The stored layout for `key`, if it is one of `allowed`; otherwise the first of `allowed`. Reports lists the tree
 * first (it is how the portal organises things -- Resources folders -- so it is what people see until they pick
 * another); Templates is a flat catalogue and offers grid and list only. */
export function readView(key: string, allowed: readonly LayoutView[] = ["tree", "grid", "list"]): LayoutView {
  try {
    const stored = localStorage.getItem(key);
    return allowed.find((v) => v === stored) ?? allowed[0];
  } catch {
    return allowed[0];
  }
}

export function saveView(key: string, view: LayoutView) {
  try {
    localStorage.setItem(key, view);
  } catch {
    // best-effort only -- the choice just won't be remembered
  }
}

const OPTIONS = [
  { view: "tree", label: "Tree view — by folder", aria: "Tree view", Icon: FolderTree },
  { view: "grid", label: "Grid view", aria: "Grid view", Icon: LayoutGrid },
  { view: "list", label: "List view", aria: "List view", Icon: List },
] as const;

export default function ViewSwitch({
  view,
  onChange,
  views = ["tree", "grid", "list"],
}: {
  view: LayoutView;
  onChange: (view: LayoutView) => void;
  views?: readonly LayoutView[];
}) {
  return (
    <div className="segmented" role="group" aria-label="Layout">
      {OPTIONS.filter((o) => views.includes(o.view)).map(({ view: v, label, aria, Icon }) => (
        <button
          key={v}
          type="button"
          className={`segmented-btn icon-only${view === v ? " active" : ""}`}
          onClick={() => onChange(v)}
          data-tip={label}
          aria-label={aria}
        >
          <Icon size={16} />
        </button>
      ))}
    </div>
  );
}

/** Expand / collapse every folder of a tree view. */
export function TreeCollapseButtons({ onExpandAll, onCollapseAll }: { onExpandAll: () => void; onCollapseAll: () => void }) {
  return (
    <div className="segmented" role="group" aria-label="Folders">
      <button type="button" className="segmented-btn icon-only" onClick={onExpandAll} data-tip="Expand all folders" aria-label="Expand all folders">
        <ChevronsUpDown size={16} />
      </button>
      <button type="button" className="segmented-btn icon-only" onClick={onCollapseAll} data-tip="Collapse all folders" aria-label="Collapse all folders">
        <ChevronsDownUp size={16} />
      </button>
    </div>
  );
}
