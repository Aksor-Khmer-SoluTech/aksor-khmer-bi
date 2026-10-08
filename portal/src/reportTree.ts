import type { Folder } from "./types";

export interface FolderRef {
  id: string;
  name: string;
}

/** What the tree needs to know about an item: the folders it is filed in (outermost first, only ones the viewer
 * may open) and the folders where a shortcut lists it again. */
export interface Placed {
  folder_path: FolderRef[];
  shortcuts?: { id: string; folder_path: FolderRef[] }[];
}

/** One line in a folder: an item filed there, or a shortcut to an item filed elsewhere. */
export interface TreeEntry<T> {
  item: T;
  /** Set for a shortcut: where the original is filed ("Root" when it is at the top level). */
  shortcutFrom?: string;
  key: string;
}

/** A Resources folder with the entries listed directly in it and the folders nested inside it. */
export interface TreeFolder<T> {
  id: string;
  name: string;
  folders: TreeFolder<T>[];
  entries: TreeEntry<T>[];
  /** Entries in this folder and everything beneath it. */
  total: number;
}

export interface ReportTree<T> {
  folders: TreeFolder<T>[];
  /** Items not in a folder the viewer can see. */
  loose: T[];
}

/** Group items into their folder hierarchy, from each one's `folder_path`, and list an item again in every
 * folder one of its shortcuts is in. Entries keep the order they arrive in; folders are sorted by name. A folder
 * only exists while it holds something, so a search that leaves no matches in a branch drops the branch. */
export function buildReportTree<T extends Placed>(items: T[], idOf: (item: T) => string): ReportTree<T> {
  const roots: TreeFolder<T>[] = [];
  const loose: T[] = [];
  const byId = new Map<string, TreeFolder<T>>();

  const place = (path: FolderRef[], entry: TreeEntry<T>) => {
    let siblings = roots;
    let node: TreeFolder<T> | undefined;
    for (const ref of path) {
      node = byId.get(ref.id);
      if (!node) {
        node = { id: ref.id, name: ref.name, folders: [], entries: [], total: 0 };
        byId.set(ref.id, node);
        siblings.push(node);
      }
      node.total += 1;
      siblings = node.folders;
    }
    node!.entries.push(entry);
  };

  for (const item of items) {
    const id = idOf(item);
    if (item.folder_path.length === 0) loose.push(item);
    else place(item.folder_path, { item, key: id });
    const home = item.folder_path.map((f) => f.name).join(" / ") || "Root";
    for (const shortcut of item.shortcuts ?? []) {
      if (shortcut.folder_path.length === 0) continue;
      place(shortcut.folder_path, { item, shortcutFrom: home, key: `${id}:${shortcut.id}` });
    }
  }

  const sort = (nodes: TreeFolder<T>[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    nodes.forEach((n) => sort(n.folders));
  };
  sort(roots);
  return { folders: roots, loose };
}

/** Every folder id in the tree, for "expand all". */
export function folderIds<T>(nodes: TreeFolder<T>[]): string[] {
  return nodes.flatMap((n) => [n.id, ...folderIds(n.folders)]);
}

/** The folders `folderId` sits in, outermost first, from a folder list the viewer is allowed to see -- for a
 * screen whose own data carries only a `folder_id`. Stops at the first folder that isn't in the list, so a
 * folder the viewer can't open never has its name shown. */
export function pathFromFolders(folders: Folder[], folderId: string | null): FolderRef[] {
  const byId = new Map(folders.map((f) => [f.id, f]));
  const path: FolderRef[] = [];
  let current = folderId ? byId.get(folderId) : undefined;
  while (current) {
    path.unshift({ id: current.id, name: current.name });
    current = current.parent_folder_id ? byId.get(current.parent_folder_id) : undefined;
  }
  return path;
}
