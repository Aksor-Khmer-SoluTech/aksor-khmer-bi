import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuthInfo, Organization, ProtectedTermSet } from "../../types";
import { has } from "../sections";
import DeploymentTermsPanel from "./DeploymentTermsPanel";
import TermSetDialog from "./TermSetDialog";

/** Admin → Protected Terms. Khmer word-breaking never splits a "protected
 * term" (a brand name, a proper noun); this is where the organization keeps
 * its shared lists of them, so a report selects a set rather than every
 * author retyping the same names. Anyone who can manage reports can *see*
 * the sets (to choose one); creating, editing and deleting needs the
 * narrower `protected_terms:manage`, since one edit reaches every report
 * that uses the set. The deployment-wide list, which comes from files on the
 * server, is shown read-only above. */
export default function ProtectedTermsPage({ auth }: { auth: AuthInfo }) {
  const canEdit = has(auth, "protected_terms:manage");
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [orgFilter, setOrgFilter] = useState("");
  const [sets, setSets] = useState<ProtectedTermSet[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProtectedTermSet | null>(null);
  // Bumped on every open so TermSetDialog remounts with fresh fields.
  const [dialogSession, setDialogSession] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<ProtectedTermSet | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    api.organizations.list().then(setOrganizations).catch(() => {});
  }, []);

  useEffect(() => {
    setSets(null);
    setError(null);
    api.protectedTerms
      .listSets(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then((rows) => setSets([...rows].sort((a, b) => a.name.localeCompare(b.name))))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load protected term sets — is the API reachable?"));
  }, [orgFilter, auth.isSuperuser]);

  const orgName = useMemo(() => new Map(organizations.map((o) => [o.id, o.name])), [organizations]);

  // Matches a set by name, description, *or any term in it* -- "is this
  // brand already in one of our lists?" is the question this search is for.
  const filtered = useMemo(() => {
    if (!sets) return [];
    const q = query.trim().toLowerCase();
    if (!q) return sets;
    return sets.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.description ?? "").toLowerCase().includes(q) ||
        s.terms.some((t) => t.toLowerCase().includes(q)) ||
        s.exclude_terms.some((t) => t.toLowerCase().includes(q)),
    );
  }, [sets, query]);

  function openSet(set: ProtectedTermSet | null) {
    setEditing(set);
    setDialogSession((n) => n + 1);
    setDialogOpen(true);
  }

  function onSaved(saved: ProtectedTermSet, created: boolean) {
    setSets((prev) => {
      const next = created ? [...(prev ?? []), saved] : (prev ?? []).map((s) => (s.id === saved.id ? saved : s));
      return next.sort((a, b) => a.name.localeCompare(b.name));
    });
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await api.protectedTerms.deleteSet(deleteTarget.id);
      setSets((prev) => prev?.filter((s) => s.id !== deleteTarget.id) ?? null);
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "Couldn't delete the set");
      setDeleteTarget(null);
    }
  }

  // Superusers see sets across organizations, so the org is worth a column;
  // an org admin only ever sees their own, where it would be noise.
  const showOrg = auth.isSuperuser;
  const columns = ["Name", ...(showOrg ? ["Organization"] : []), "Protected", "Excluded", "Updated", ""];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Protected Terms</h1>
          <p className="page-subtitle">
            Words the Khmer word-breaker must never split — brand names, proper nouns. Keep shared lists here and select them
            into any report.
          </p>
        </div>
        {canEdit && (
          <button type="button" className="btn btn-primary" onClick={() => openSet(null)}>
            + New set
          </button>
        )}
      </div>

      <DeploymentTermsPanel />

      <div className="gallery-toolbar">
        <div className="search">
          <input
            type="text"
            placeholder="Search sets or terms…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {auth.isSuperuser && (
          <select value={orgFilter} onChange={(e) => setOrgFilter(e.target.value)} style={{ maxWidth: 220 }}>
            <option value="">All organizations</option>
            {organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {deleteError && <p className="alert alert-error">{deleteError}</p>}
      {sets === null && !error && <TableSkeleton columns={columns} />}

      {sets !== null && filtered.length === 0 && (
        <div className="empty-state">
          <p>
            {sets.length === 0
              ? canEdit
                ? "No protected term sets yet — create one to share a list of terms across reports."
                : "No protected term sets in this organization yet."
              : "No sets or terms match that search."}
          </p>
        </div>
      )}

      {filtered.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((c, i) => (
                <th key={i}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr key={s.id} onClick={() => openSet(s)}>
                <td>
                  <div className="terms-name-cell">
                    <span>{s.name}</span>
                    {s.description && <span className="muted terms-name-desc">{s.description}</span>}
                  </div>
                </td>
                {showOrg && <td className="muted">{orgName.get(s.org_id) ?? s.org_id}</td>}
                <td className="mono">{s.terms.length}</td>
                <td className="mono">{s.exclude_terms.length}</td>
                <td className="muted">{new Date(s.updated_at).toLocaleDateString()}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  <div className="terms-row-actions">
                    <button type="button" className="btn btn-sm" onClick={() => openSet(s)}>
                      {canEdit ? "Edit" : "View"}
                    </button>
                    {canEdit && (
                      <button type="button" className="btn-danger btn btn-sm" onClick={() => setDeleteTarget(s)}>
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <TermSetDialog
        key={dialogSession}
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        set={editing}
        canEdit={canEdit}
        organizations={
          organizations.length > 0
            ? organizations
            : [{ id: auth.orgId ?? "root", name: auth.orgId ?? "root", parent_org_id: null, is_active: true, created_at: "" }]
        }
        defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || "root"}
        onSaved={onSaved}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete protected term set"
        body={
          deleteTarget
            ? `Delete "${deleteTarget.name}"? Reports that select it stop getting its ${deleteTarget.terms.length} terms on their next render. This can't be undone.`
            : ""
        }
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
