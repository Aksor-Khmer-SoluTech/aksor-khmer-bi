import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Folder } from "../types";

/** Which Resources folder a report is filed in. Shows every folder the person can see, as its full path
 * ("Finance / Q2 2026 / Drafts"), and only lets them pick the ones they may file into -- the server checks
 * the same thing again, so this just saves them an error. "Root" puts the report at the top level, outside any folder.
 * Folders themselves are created and arranged in Manage → Resources. */
export default function FolderPicker({
  value,
  onChange,
  orgId,
  label = "Folder",
  placeholder,
  exclude = [],
  hint,
  folders: given,
}: {
  value: string | null;
  onChange: (folderId: string | null) => void;
  orgId?: string;
  label?: string;
  /** When set, the empty choice reads this instead of "Root" -- for a picker where Root isn't an option. */
  placeholder?: string;
  /** Folders to leave out (e.g. the one the report is already filed in). */
  exclude?: string[];
  /** Replaces the default hint; `null` shows none. */
  hint?: string | null;
  /** The folder list, when the caller already has it (saves a second request). */
  folders?: Folder[] | null;
}) {
  const [loaded, setLoaded] = useState<Folder[] | null>(null);
  const folders = given !== undefined ? given : loaded;

  useEffect(() => {
    if (given !== undefined) return;
    api.folders.list(orgId).then(setLoaded).catch(() => setLoaded([]));
  }, [orgId, given]);

  const options = useMemo(() => {
    const byId = new Map((folders ?? []).map((f) => [f.id, f]));
    const pathOf = (f: Folder): string => {
      const parent = f.parent_folder_id ? byId.get(f.parent_folder_id) : undefined;
      return parent ? `${pathOf(parent)} / ${f.name}` : f.name;
    };
    return (folders ?? [])
      .filter((f) => !exclude.includes(f.id))
      .map((f) => ({ folder: f, path: pathOf(f) }))
      .sort((a, b) => a.path.localeCompare(b.path));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `exclude` is a new array each render; its contents are what matter
  }, [folders, exclude.join(",")]);

  const known = value === null || options.some((o) => o.folder.id === value);
  const nothingToPick = folders !== null && !options.some((o) => o.folder.can_manage);

  return (
    <label>
      <span>{label}</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} disabled={folders === null}>
        <option value="">{placeholder ?? "Root"}</option>
        {!known && <option value={value!}>A folder you can't see</option>}
        {options.map(({ folder, path }) => (
          <option key={folder.id} value={folder.id} disabled={!folder.can_manage && folder.id !== value}>
            {path}
            {!folder.can_manage ? " — no access to file here" : ""}
          </option>
        ))}
      </select>
      {hint !== null && (
        <span className="field-hint">
          {hint ??
            (nothingToPick
              ? "You don't have manage access to any folder yet, so this stays in Root. Ask an administrator."
              : "Where this report appears in the Reports tree. Folders are created in Manage → Resources.")}
        </span>
      )}
    </label>
  );
}
