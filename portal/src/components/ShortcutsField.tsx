import { useEffect, useMemo, useState } from "react";
import { Link2, X } from "lucide-react";
import { api, ApiError } from "../api";
import type { Folder, ReportMeta, ReportShortcut } from "../types";
import FolderPicker from "./FolderPicker";

/** The other folders a report is listed in. A shortcut is only a second place to find the report: it opens the
 * original and has exactly the original's access -- nothing is granted by it, and access given on the folder
 * that holds it doesn't reach the report. Added and removed straight away (not with "Save changes"); removing
 * one never touches the report. */
export default function ShortcutsField({ report }: { report: ReportMeta }) {
  const [shortcuts, setShortcuts] = useState<ReportShortcut[] | null>(null);
  const [folders, setFolders] = useState<Folder[] | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listReportShortcuts(report.report_id).then(setShortcuts).catch(() => setShortcuts([]));
    api.folders.list(report.org_id ?? undefined).then(setFolders).catch(() => setFolders([]));
  }, [report.report_id, report.org_id]);

  const pathOf = useMemo(() => {
    const byId = new Map((folders ?? []).map((f) => [f.id, f]));
    const path = (id: string): string => {
      const f = byId.get(id);
      return f ? (f.parent_folder_id ? `${path(f.parent_folder_id)} / ${f.name}` : f.name) : "A folder you can't see";
    };
    return path;
  }, [folders]);

  const taken = [report.folder_id, ...(shortcuts ?? []).map((s) => s.folder_id)].filter((id): id is string => Boolean(id));

  async function add() {
    if (!pick) return;
    setBusy(true);
    setError(null);
    try {
      const made = await api.createShortcut(report.report_id, pick);
      setShortcuts((prev) => [...(prev ?? []), made]);
      setPick(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add the shortcut");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await api.deleteShortcut(id);
      setShortcuts((prev) => (prev ?? []).filter((s) => s.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the shortcut");
    }
  }

  return (
    <div className="shortcuts-field">
      {(shortcuts ?? []).length > 0 && (
        <ul className="shortcut-list">
          {(shortcuts ?? []).map((s) => (
            <li key={s.id}>
              <Link2 size={14} aria-hidden="true" />
              <span className="shortcut-path">{pathOf(s.folder_id)}</span>
              <button type="button" className="btn btn-ghost btn-sm icon-only" onClick={() => remove(s.id)} aria-label={`Remove the shortcut in ${pathOf(s.folder_id)}`} data-tip="Remove shortcut">
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="shortcut-add">
        <FolderPicker label="Add a shortcut in" placeholder="Choose a folder…" hint={null} value={pick} onChange={setPick} folders={folders} exclude={taken} />
        <button type="button" className="btn" disabled={!pick || busy} onClick={add}>
          Add shortcut
        </button>
      </div>
      {error && <p className="alert alert-error">{error}</p>}
    </div>
  );
}
