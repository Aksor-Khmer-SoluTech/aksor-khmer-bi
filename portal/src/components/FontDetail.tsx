import { useEffect, useMemo, useState } from "react";
import { Trash2, TriangleAlert, X } from "lucide-react";
import { api, ApiError } from "../api";
import type { FontBlock, FontResource } from "../types";
import ConfirmDialog from "./ConfirmDialog";
import { Coverage } from "./FontsPanel";

const SAMPLE = "ក្រសួងសេដ្ឋកិច្ច និងហិរញ្ញវត្ថុ ០១២៣៤៥៦៧៨៩ — Hello World 0123456789";

// Dependent vowels and signs need a base to sit on to be seen at all.
const needsBase = (cp: number) => (cp >= 0x17b4 && cp <= 0x17d3) || cp === 0x17dd;

/** Check a font before relying on it: what it is, whether it can really draw Khmer, and every character it has --
 * drawn with the font itself, loaded straight from the server (not from anything installed in your browser). */
export default function FontDetail({ font, canManage, onClose, onChanged }: { font: FontResource; canManage: boolean; onClose: () => void; onChanged: () => void }) {
  const alias = useMemo(() => `aksor-preview-${font.id}`, [font.id]);
  const [loaded, setLoaded] = useState<"loading" | "ready" | "failed">("loading");
  const [sample, setSample] = useState(SAMPLE);
  const [blocks, setBlocks] = useState<FontBlock[] | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let face: FontFace | null = null;
    setLoaded("loading");
    setBlocks(null);
    api.fonts
      .fileBlob(font.id)
      .then((blob) => blob.arrayBuffer())
      .then((bytes) => {
        face = new FontFace(alias, bytes, { weight: String(font.weight), style: font.italic ? "italic" : "normal" });
        return face.load();
      })
      .then((ready) => {
        if (cancelled) return;
        document.fonts.add(ready);
        setLoaded("ready");
      })
      .catch(() => !cancelled && setLoaded("failed"));
    api.fonts.coverage(font.id).then((b) => !cancelled && setBlocks(b)).catch(() => {});
    return () => {
      cancelled = true;
      if (face) document.fonts.delete(face);
    };
  }, [font.id, font.weight, font.italic, alias]);

  async function remove(force: boolean) {
    setError(null);
    try {
      await api.fonts.delete(font.id, force);
      onChanged();
    } catch (err) {
      setConfirm(false);
      setError(err instanceof ApiError ? err.message : "Couldn't remove the font");
    }
  }

  const styleFor = (size: number) => ({ fontFamily: `"${alias}", sans-serif`, fontSize: size, fontWeight: font.weight, fontStyle: font.italic ? "italic" : "normal" }) as const;

  return (
    <div className="panel font-detail">
      <div className="spread" style={{ alignItems: "flex-start", gap: 12 }}>
        <div>
          <h2 className="panel-title" style={{ marginBottom: 2 }}>{font.family} <span className="muted">{font.subfamily}</span></h2>
          <p className="panel-subtitle" style={{ marginBottom: 0 }}>
            A template asks for it as <code className="mono">{font.family}</code>
            {font.subfamily !== "Regular" && <> (the {font.subfamily.toLowerCase()} style is picked by the template's bold/italic setting)</>}.
          </p>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {canManage && (
            <button type="button" className="btn btn-danger btn-sm" onClick={() => setConfirm(true)}>
              <Trash2 size={14} aria-hidden="true" /> Remove
            </button>
          )}
          <button type="button" className="btn btn-sm icon-only" onClick={onClose} aria-label="Close"><X size={14} /></button>
        </div>
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {font.warnings.length > 0 && (
        <ul className="fonts-warnings alert alert-warning">
          {font.warnings.map((w) => (
            <li key={w}><TriangleAlert size={13} aria-hidden="true" /> {w}</li>
          ))}
        </ul>
      )}

      <div className="font-detail-grid">
        <section>
          <h3 className="font-detail-h">Identity</h3>
          <dl className="font-facts">
            <dt>Full name</dt><dd>{font.full_name}</dd>
            <dt>PostScript name</dt><dd className="mono">{font.postscript_name || "—"}</dd>
            <dt>Version</dt><dd>{font.version || "—"}</dd>
            <dt>Weight / style</dt><dd>{font.weight}{font.italic ? " · italic" : ""}</dd>
            <dt>Glyphs</dt><dd>{font.glyph_count}</dd>
            <dt>Khmer coverage</dt><dd><Coverage value={font.khmer_coverage} /></dd>
            <dt>Latin coverage</dt><dd className="mono">{font.latin_coverage}%</dd>
            <dt>Layout tables</dt><dd>{font.has_layout_tables ? "GSUB + GPOS present" : "none"}</dd>
            <dt>File</dt><dd className="mono">{font.filename} · {(font.size_bytes / 1024).toFixed(0)} KB · {font.file_ext}</dd>
            <dt>SHA-256</dt><dd className="mono" title={font.sha256}>{font.sha256.slice(0, 16)}…</dd>
          </dl>
        </section>
        <section>
          <h3 className="font-detail-h">License</h3>
          <dl className="font-facts">
            <dt>Embedding</dt><dd>{font.embedding || "—"}</dd>
            <dt>License</dt><dd>{font.license || <span className="muted">not stated in the font</span>}</dd>
            {font.license_url && (<><dt>License URL</dt><dd><a href={font.license_url} target="_blank" rel="noreferrer">{font.license_url}</a></dd></>)}
            <dt>Copyright</dt><dd>{font.copyright || "—"}</dd>
            {font.note && (<><dt>Note</dt><dd>{font.note}</dd></>)}
          </dl>
          <h3 className="font-detail-h" style={{ marginTop: 16 }}>Used by</h3>
          {font.used_by.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>No template names this font yet.</p>
          ) : (
            <ul className="font-used-by">{font.used_by.map((n) => <li key={n}>{n}</li>)}</ul>
          )}
        </section>
      </div>

      <h3 className="font-detail-h">Try it</h3>
      {loaded === "failed" && <p className="alert alert-error">Couldn't load the font into the page to preview it.</p>}
      <textarea className="font-sample-input" rows={2} value={sample} onChange={(e) => setSample(e.target.value)} aria-label="Sample text" />
      {loaded === "loading" && <p className="muted">Loading the font…</p>}
      {loaded === "ready" && (
        <div className="font-specimen">
          {[14, 22, 36].map((size) => (
            <div key={size} className="font-specimen-line">
              <span className="muted mono">{size}px</span>
              <span style={styleFor(size)}>{sample || " "}</span>
            </div>
          ))}
        </div>
      )}

      <h3 className="font-detail-h">Every character it has</h3>
      <p className="muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
        Each box is drawn with this font. A shaded box is a character that exists in Unicode and the font lacks.
      </p>
      {blocks === null ? (
        <p className="muted">Reading the character map…</p>
      ) : (
        blocks.map((b) => (
          <div key={b.name} className="font-block">
            <div className="font-block-head">
              <strong>{b.name}</strong>
              <span className="muted mono"> U+{b.start.toString(16).toUpperCase().padStart(4, "0")}–{b.end.toString(16).toUpperCase().padStart(4, "0")} · {b.present.length} of {b.present.length + b.missing.length}</span>
            </div>
            <div className="font-glyphs">
              {[...b.present.map((cp) => ({ cp, has: true })), ...b.missing.map((cp) => ({ cp, has: false }))]
                .sort((x, y) => x.cp - y.cp)
                .map(({ cp, has }) => (
                  <span key={cp} className={`font-glyph${has ? "" : " missing"}`} title={`U+${cp.toString(16).toUpperCase().padStart(4, "0")} · ${has ? "present" : "missing"}`}>
                    <span style={has && loaded === "ready" ? styleFor(22) : undefined}>{needsBase(cp) ? "◌" : ""}{String.fromCodePoint(cp)}</span>
                  </span>
                ))}
            </div>
          </div>
        ))
      )}

      <ConfirmDialog
        open={confirm}
        title={`Remove ${font.family} ${font.subfamily}?`}
        body={
          font.used_by.length
            ? `${font.used_by.slice(0, 5).join(", ")}${font.used_by.length > 5 ? " and more" : ""} name this font. They will render in a substitute font, and their layout can change.`
            : "No template names it. It disappears from the server at the next render."
        }
        confirmLabel={font.used_by.length ? "Remove anyway" : "Remove"}
        onConfirm={() => remove(font.used_by.length > 0)}
        onCancel={() => setConfirm(false)}
      />
    </div>
  );
}
