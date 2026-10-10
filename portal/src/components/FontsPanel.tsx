import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Check, FileType, Search, TriangleAlert, Type, Upload, X } from "lucide-react";
import { api, ApiError } from "../api";
import { useDialogRef } from "../hooks";
import type { FontResource, InstalledFont } from "../types";
import FontDetail from "./FontDetail";
import ModalClose from "./ModalClose";
import { TableSkeleton } from "./Skeletons";

/** Resources > Fonts: add a font to the whole server without redeploying anything, check it before a template
 * depends on it, and see which templates already name it. A font added here is used by the next render of every
 * template that names its family -- LibreOffice (docx), WeasyPrint (html) and charts alike. */
export default function FontsPanel({ canManage }: { canManage: boolean }) {
  const [fonts, setFonts] = useState<FontResource[] | null>(null);
  const [installed, setInstalled] = useState<InstalledFont[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // The file picked with "Add font", waiting in the dialog for its (optional) source / license note.
  const [picked, setPicked] = useState<File | null>(null);
  const [justAdded, setJustAdded] = useState<FontResource | null>(null);
  const [query, setQuery] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  function load() {
    api.fonts.list().then((list) => { setFonts(list); setError(null); }).catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the fonts"));
    api.fonts.installed().then(setInstalled).catch(() => setInstalled([]));
  }
  useEffect(load, []);

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (fileInput.current) fileInput.current.value = "";
    if (!file) return;
    setError(null);
    setJustAdded(null);
    setPicked(file);
  }

  function onAdded(added: FontResource) {
    setPicked(null);
    setJustAdded(added);
    setSelectedId(added.id);
    load();
  }

  const selected = fonts?.find((f) => f.id === selectedId) ?? null;
  const systemFamilies = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (installed ?? []).filter((f) => f.source === "system" && (!q || f.family.toLowerCase().includes(q)));
  }, [installed, query]);

  return (
    <div className="fonts-panel">
      <div className="panel">
        <div className="spread" style={{ gap: 16, alignItems: "flex-start" }}>
          <div style={{ flex: "1 1 420px", minWidth: 0 }}>
            <h2 className="panel-title">Fonts</h2>
            <p className="panel-subtitle" style={{ marginBottom: 0 }}>
              Added for the <strong>whole server</strong>: LibreOffice (<span className="mono">.docx</span>), WeasyPrint (<span className="mono">.html</span>) and charts
              draw with them from the next render — no restart. A template names a font by its <em>family</em> (the name shown here).
            </p>
          </div>
          {canManage && (
            <div className="fonts-upload">
              <input ref={fileInput} type="file" accept=".ttf,.otf" style={{ display: "none" }} onChange={onFile} />
              <button type="button" className="btn btn-primary" onClick={() => fileInput.current?.click()}>
                <Upload size={15} aria-hidden="true" /> Add font
              </button>
            </div>
          )}
        </div>

        {error && <p className="alert alert-error">{error}</p>}
        {justAdded && (
          <div className="alert alert-success">
            <Check size={14} aria-hidden="true" /> Added <strong>{justAdded.family} {justAdded.subfamily}</strong> ({justAdded.version || "no version"}). Check it below before relying on it.
            {justAdded.warnings.length > 0 && (
              <ul className="fonts-warnings">
                {justAdded.warnings.map((w) => (
                  <li key={w}><TriangleAlert size={13} aria-hidden="true" /> {w}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {fonts === null && !error ? (
          <TableSkeleton columns={["Font", "Version", "Khmer", "Layout", "Glyphs", "Used by", "Added"]} />
        ) : fonts && fonts.length === 0 ? (
          <div className="empty-state">
            <Type className="empty-state-icon" size={40} strokeWidth={1.4} aria-hidden="true" />
            <p>No fonts added yet.</p>
            <p className="empty-state-hint">The server already has its own (see below). Add one when a template needs a font it doesn't have.</p>
          </div>
        ) : (
          fonts && (
            <table className="data-table fonts-table">
              <thead>
                <tr>
                  <th>Font</th>
                  <th>Version</th>
                  <th>Khmer</th>
                  <th>Layout</th>
                  <th>Glyphs</th>
                  <th>Used by</th>
                  <th>Added</th>
                </tr>
              </thead>
              <tbody>
                {fonts.map((f) => (
                  <tr key={f.id} className={`fonts-row${f.id === selectedId ? " selected" : ""}`} onClick={() => setSelectedId(f.id === selectedId ? null : f.id)}>
                    <td>
                      <strong>{f.family}</strong> <span className="muted">{f.subfamily}</span>
                      {f.warnings.length > 0 && <TriangleAlert size={13} className="fonts-warn-icon" aria-label={`${f.warnings.length} warning(s)`} />}
                    </td>
                    <td className="mono muted">{f.version || "—"}</td>
                    <td><Coverage value={f.khmer_coverage} /></td>
                    <td>{f.has_layout_tables ? <Check size={14} aria-label="Has layout tables" /> : <X size={14} className="muted" aria-label="No layout tables" />}</td>
                    <td className="mono">{f.glyph_count}</td>
                    <td>{f.used_by.length ? `${f.used_by.length} template${f.used_by.length === 1 ? "" : "s"}` : <span className="muted">—</span>}</td>
                    <td className="muted">{new Date(f.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>

      <AddFontDialog file={picked} onClose={() => setPicked(null)} onAdded={onAdded} />

      {selected && <FontDetail font={selected} canManage={canManage} onClose={() => setSelectedId(null)} onChanged={() => { setSelectedId(null); load(); }} />}

      <details className="panel fonts-installed">
        <summary>
          <strong>Installed on the server</strong> <span className="muted">— {installed ? installed.filter((f) => f.source === "system").length : "…"} families the operating system provides</span>
        </summary>
        <div className="search search-icon-field" style={{ margin: "12px 0" }}>
          <Search size={16} className="search-icon" aria-hidden="true" />
          <input type="text" placeholder="Search installed fonts…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <p className="muted" style={{ fontSize: "0.82rem" }}>A template that names one of these needs nothing added. Names are matched case-insensitively.</p>
        <div className="fonts-chips">
          {systemFamilies.map((f) => (
            <span key={f.family} className="fonts-chip">{f.family}</span>
          ))}
          {installed && systemFamilies.length === 0 && <span className="muted">No match.</span>}
        </div>
      </details>
    </div>
  );
}

/** A small bar and the number: how much of the Khmer block the font has glyphs for. */
export function Coverage({ value }: { value: number }) {
  const tone = value >= 90 ? "good" : value >= 70 ? "ok" : "low";
  return (
    <span className={`fonts-coverage ${tone}`} title={`${value}% of the Khmer block`}>
      <span className="fonts-coverage-bar"><span style={{ width: `${Math.max(2, value)}%` }} /></span>
      <span className="mono">{value}%</span>
    </span>
  );
}

/** Step two of "Add font": the chosen file, and a note on where it came from and who cleared its license -- kept
 * with the font (shown in its details) so whoever looks later knows it may be used. */
function AddFontDialog({ file, onClose, onAdded }: { file: File | null; onClose: () => void; onAdded: (font: FontResource) => void }) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useDialogRef(file !== null, () => {
    setNote("");
    setError(null);
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setSaving(true);
    setError(null);
    try {
      onAdded(await api.fonts.upload(file, note.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add the font");
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog ref={ref} className="modal" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">Add font</h2>
      <form onSubmit={submit} className="stack">
        {file && (
          <div className="fonts-picked">
            <FileType size={20} aria-hidden="true" />
            <div style={{ minWidth: 0 }}>
              <div className="fonts-picked-name">{file.name}</div>
              <div className="muted" style={{ fontSize: "0.78rem" }}>
                {(file.size / 1024).toFixed(0)} KB · installed for the whole server, used from the next render
              </div>
            </div>
          </div>
        )}
        <label>
          <span>
            Source and license <span className="muted" style={{ fontWeight: 400 }}>(optional)</span>
          </span>
          <textarea
            rows={2}
            maxLength={300}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Google Fonts, SIL Open Font License — or: bought by Finance, licence #1234"
          />
        </label>
        <p className="field-hint" style={{ marginTop: -6 }}>
          Where the font came from and who cleared its license. Some fonts can't be used freely; this note stays with
          the font so whoever checks later knows it's allowed.
        </p>
        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? <span className="spinner" /> : <Upload size={15} aria-hidden="true" />} Add font
          </button>
        </div>
      </form>
    </dialog>
  );
}
