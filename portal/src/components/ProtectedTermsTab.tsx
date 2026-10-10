import { useEffect, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { api, ApiError } from "../api";
import { LinesSkeleton } from "./Skeletons";
import TermChips from "./TermChips";
import TermsInput from "./TermsInput";
import type { DeploymentTerms, ProtectedTermSet, ReportMeta } from "../types";

/** The template page's "Protected Terms" tab (managers only): the words the
 * Khmer word-breaker must keep whole in *this* report's output -- brand
 * names, proper nouns. Three layers, added together:
 *
 *   1. the deployment-wide list (built-ins + the server's config files) --
 *      always on, shown here read-only for context;
 *   2. shared sets from the organization's library, selected by reference,
 *      so editing a set later updates every report that uses it;
 *   3. this report's own extra terms.
 *
 * "Never protect" wins over all three -- a term listed there is handed back
 * to the default word-breaker, whichever layer asked for it. */
export default function ProtectedTermsTab({ report, canManageSets }: { report: ReportMeta; canManageSets: boolean }) {
  const [loaded, setLoaded] = useState(false);
  const [sets, setSets] = useState<ProtectedTermSet[]>([]);
  const [floor, setFloor] = useState<DeploymentTerms | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [terms, setTerms] = useState<string[]>([]);
  const [excludeTerms, setExcludeTerms] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoaded(false);
    setError(null);
    // The deployment list is context only -- if it's unavailable (not synced
    // yet, or not visible to this caller) the tab is still fully usable.
    api.protectedTerms.deploymentFloor().then(setFloor).catch(() => setFloor(null));
    Promise.all([api.getProtectedTermsConfig(report.report_id), api.protectedTerms.listSets(report.org_id ?? undefined)])
      .then(([config, available]) => {
        setSets(available);
        setSelected(config.set_ids);
        setTerms(config.terms);
        setExcludeTerms(config.exclude_terms);
        setLoaded(true);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load this report's protected terms"));
  }, [report.report_id, report.org_id]);

  const known = useMemo(() => new Set(sets.map((s) => s.id)), [sets]);
  // A selected set that has since been deleted: the server ignores it at
  // render time but rejects it on save, so it's dropped from what we send.
  const staleCount = selected.filter((id) => !known.has(id)).length;

  function touch() {
    setSaved(false);
  }

  function toggle(id: string) {
    touch();
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const config = await api.putProtectedTermsConfig(report.report_id, {
        set_ids: selected.filter((id) => known.has(id)),
        terms,
        exclude_terms: excludeTerms,
      });
      setSelected(config.set_ids);
      setTerms(config.terms);
      setExcludeTerms(config.exclude_terms);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  if (!loaded && !error) {
    return (
      <div className="panel">
        <h2 className="panel-title">Protected Terms</h2>
        <LinesSkeleton count={4} />
      </div>
    );
  }

  return (
    <div className="panel">
      <h2 className="panel-title">Protected Terms</h2>
      <p className="panel-subtitle">
        Words the Khmer word-breaker keeps whole in this report — brand names, proper nouns — instead of splitting them at
        the wrong place.
      </p>

      {floor && (
        <p className="terms-floor-note field-hint">
          Always applied: the built-in list
          {floor.terms.length > 0 && (
            <>
              {" "}
              and <strong>{floor.terms.length}</strong> deployment-wide {floor.terms.length === 1 ? "term" : "terms"} from the
              server's config files
            </>
          )}
          . Everything below adds to it.
        </p>
      )}

      {error && <p className="alert alert-error">{error}</p>}

      <section className="data-config-section">
        <h3 className="data-config-heading">Shared sets</h3>
        <p className="field-hint data-config-hint">
          Lists your organization keeps in one place. A set is <strong>linked</strong>, not copied — when it's edited, this
          report follows.
        </p>

        {sets.length === 0 ? (
          <p className="terms-empty">
            No shared sets in this organization yet.{" "}
            {canManageSets && <a href="#/admin/protected-terms">Create one in Manage → Protected Terms</a>}
          </p>
        ) : (
          <ul className="terms-set-list">
            {sets.map((s) => {
              const isOpen = open === s.id;
              return (
                <li key={s.id} className={`terms-set${selected.includes(s.id) ? " selected" : ""}`}>
                  <div className="terms-set-row">
                    <label className="checkbox-label terms-set-check">
                      <input type="checkbox" checked={selected.includes(s.id)} onChange={() => toggle(s.id)} />
                      <span className="terms-set-name">
                        {s.name}
                        {s.description && <span className="terms-set-desc">{s.description}</span>}
                      </span>
                    </label>
                    <span className="terms-set-counts">
                      <span>{s.terms.length} protected</span>
                      {s.exclude_terms.length > 0 && <span>{s.exclude_terms.length} excluded</span>}
                    </span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm icon-only"
                      aria-expanded={isOpen}
                      aria-label={`${isOpen ? "Hide" : "Show"} the terms in ${s.name}`}
                      title={isOpen ? "Hide terms" : "Show terms"}
                      onClick={() => setOpen(isOpen ? null : s.id)}
                    >
                      <ChevronRight size={15} className={`terms-set-chevron${isOpen ? " open" : ""}`} aria-hidden="true" />
                    </button>
                  </div>
                  {isOpen && (
                    <div className="terms-set-body">
                      <TermChips terms={s.terms} empty="No protected terms" />
                      {s.exclude_terms.length > 0 && (
                        <>
                          <div className="terms-chip-label">Never protected</div>
                          <TermChips terms={s.exclude_terms} muted />
                        </>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {staleCount > 0 && (
          <p className="field-hint terms-stale">
            {staleCount === 1 ? "A set this report used has" : `${staleCount} sets this report used have`} been deleted and will be
            removed when you save.
          </p>
        )}
      </section>

      <section className="data-config-section">
        <h3 className="data-config-heading">This report's own terms</h3>
        <p className="field-hint data-config-hint">
          Type a term and press <kbd>Enter</kbd>. Paste a list — one per line — to add many at once. Click a term to edit it.
        </p>
        <div className="terms-pair">
          <TermsInput
            label="Protect"
            hint="Kept whole in this report only."
            terms={terms}
            onChange={(next) => {
              touch();
              setTerms(next);
            }}
          />
          <TermsInput
            label="Never protect"
            variant="exclude"
            hint="Overrides every list above."
            placeholder="Type a term to hand back to the normal word-breaker"
            terms={excludeTerms}
            onChange={(next) => {
              touch();
              setExcludeTerms(next);
            }}
          />
        </div>
      </section>

      <div className="data-config-actions">
        <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
          {saving && <span className="spinner" />}
          Save changes
        </button>
        {saved && <span className="alert alert-success data-config-saved">Saved.</span>}
      </div>
    </div>
  );
}
