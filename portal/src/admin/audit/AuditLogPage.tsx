import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, X } from "lucide-react";
import { api, ApiError } from "../../api";
import {
  ActionGlyph,
  ActorLine,
  AuditChanges,
  ENTITY_TYPES,
  EventDetails,
  fmtStamp,
  stampTitle,
} from "../../components/AuditParts";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuditEvent, AuthInfo, Organization } from "../../types";

const PAGE_SIZE = 50;

// Every action the API records, for the Action field's suggestions. It's a
// free-text box (the server matches an exact action or a prefix, so "user"
// finds every user.* change) -- this list is only the autocomplete.
const KNOWN_ACTIONS = [
  "report.create", "report.update", "report.file_replace", "report.template_download", "report.data_config_update", "report.run", "report.run_failed",
  "report.terms_config_update", "report.access_grant", "report.access_revoke", "report.delete", "report.shortcut_create", "report.shortcut_delete",
  "user.create", "user.update", "user.password_reset", "user.password_change", "user.totp_reset", "user.totp_enable",
  "user.totp_disable", "user.role_grant", "user.role_revoke", "user.permission_grant", "user.permission_revoke",
  "role.create", "role.permissions_update", "role.delete", "organization.create",
  "ldap_config.create", "ldap_config.update", "ldap_config.delete", "ldap_config.test", "ldap_config.mapping_add",
  "ldap_config.mapping_remove", "protected_term_set.create", "protected_term_set.update", "protected_term_set.delete",
  "deployment_terms.change", "job.create", "job.update", "job.delete",
  "folder.create", "folder.update", "folder.move", "folder.delete", "folder.access_grant", "folder.access_revoke",
  "image.upload", "image.delete", "stylesheet.upload", "stylesheet.delete",
];

const startOfDay = (d: string) => (d ? new Date(`${d}T00:00:00`).toISOString() : undefined);
const endOfDay = (d: string) => (d ? new Date(`${d}T23:59:59.999`).toISOString() : undefined);

/** "Today" / "Yesterday" / "Thu, Sep 25" -- the day heading a group of rows sits under. */
function dayLabel(iso: string): string {
  const d = new Date(iso);
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function Row({
  event,
  open,
  onToggle,
  onFocusEntity,
}: {
  event: AuditEvent;
  open: boolean;
  onToggle: () => void;
  onFocusEntity: (e: AuditEvent) => void;
}) {
  const expandable = Boolean(event.changes?.length) || Boolean(event.details && Object.keys(event.details).length);
  return (
    <article className="rounded-md border border-border-soft bg-bg-raised transition-shadow hover:shadow-card">
      <button
        type="button"
        className="flex w-full cursor-pointer items-start gap-3 rounded-md border-0 bg-transparent px-4 py-3 text-left"
        onClick={onToggle}
        aria-expanded={open}
        disabled={!expandable}
        style={{ cursor: expandable ? "pointer" : "default" }}
      >
        <ActionGlyph action={event.action} />
        <span className="min-w-0 flex-1">
          <span className="block text-[0.9rem] font-medium text-text">{event.summary}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="rounded-sm bg-bg-panel px-1.5 py-px font-mono text-[0.7rem] text-text-dim">{event.action}</span>
            <ActorLine event={event} />
          </span>
        </span>
        <time className="shrink-0 pt-0.5 text-[0.78rem] text-text-faint" dateTime={event.created_at} title={stampTitle(event.created_at)}>
          {fmtStamp(event.created_at)}
        </time>
        <ChevronRight
          size={15}
          aria-hidden
          className={`mt-1 shrink-0 text-text-faint transition-transform ${open ? "rotate-90" : ""} ${expandable ? "" : "opacity-0"}`}
        />
      </button>

      {open && (
        <div className="border-t border-border-soft px-4 pb-4 pt-1 pl-[3.75rem]">
          <AuditChanges changes={event.changes} max={12} />
          <EventDetails event={event} />
          <p className="mb-0 mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.76rem] text-text-faint">
            <button type="button" className="link-btn" onClick={() => onFocusEntity(event)}>
              Everything that happened to {event.entity_label ?? event.entity_id}
            </button>
            <span className="font-mono">
              {event.entity_type}/{event.entity_id}
            </span>
            {event.org_id && <span className="font-mono">org {event.org_id}</span>}
            <span className="font-mono">event {event.id}</span>
          </p>
        </div>
      )}
    </article>
  );
}

/** Admin's answer to "who changed that, and what was it before?" -- the whole
 * change audit trail (api/app/audit.py), searchable. Sits beside the security
 * feed on the Dashboard, which covers the other two questions an
 * investigation asks (who signed in, who was refused). Read-only: nothing
 * anywhere in the API edits or deletes an audit row. */
export default function AuditLogPage({ auth }: { auth: AuthInfo }) {
  const [q, setQ] = useState("");
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [entityId, setEntityId] = useState<{ id: string; label: string } | null>(null);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [orgId, setOrgId] = useState("");
  const [organizations, setOrganizations] = useState<Organization[]>([]);

  const [items, setItems] = useState<AuditEvent[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());

  const dq = useDebounced(q.trim());
  const dactor = useDebounced(actor.trim());
  const daction = useDebounced(action.trim());
  // Only the latest request may write results -- typing fast fires several.
  const requestSeq = useRef(0);

  useEffect(() => {
    if (auth.isSuperuser) api.organizations.list().then(setOrganizations).catch(() => {});
  }, [auth.isSuperuser]);

  const query = useMemo(
    () => ({
      q: dq || undefined,
      actor: dactor || undefined,
      action: daction || undefined,
      entityType: entityType || undefined,
      entityId: entityId?.id,
      since: startOfDay(since),
      until: endOfDay(until),
      orgId: orgId || undefined,
    }),
    [dq, dactor, daction, entityType, entityId, since, until, orgId],
  );

  useEffect(() => {
    const seq = ++requestSeq.current;
    setError(null);
    api.audit
      .list({ ...query, limit: PAGE_SIZE, offset: 0 })
      .then((page) => {
        if (seq !== requestSeq.current) return;
        setItems(page.items);
        setTotal(page.total);
        setOpen(new Set());
      })
      .catch((err) => {
        if (seq === requestSeq.current) setError(err instanceof ApiError ? err.message : "Couldn't load the audit log");
      });
  }, [query]);

  async function loadMore() {
    if (!items) return;
    setLoadingMore(true);
    try {
      const page = await api.audit.list({ ...query, limit: PAGE_SIZE, offset: items.length });
      setItems((prev) => [...(prev ?? []), ...page.items]);
      setTotal(page.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load more");
    } finally {
      setLoadingMore(false);
    }
  }

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  function focusEntity(e: AuditEvent) {
    setEntityType(e.entity_type);
    setEntityId({ id: e.entity_id, label: e.entity_label ?? e.entity_id });
  }

  const filtersActive = Boolean(q || actor || action || entityType || entityId || since || until || orgId);
  function clearFilters() {
    setQ("");
    setActor("");
    setAction("");
    setEntityType("");
    setEntityId(null);
    setSince("");
    setUntil("");
    setOrgId("");
  }

  const groups = useMemo(() => {
    const out: { day: string; rows: AuditEvent[] }[] = [];
    for (const e of items ?? []) {
      const day = dayLabel(e.created_at);
      const last = out[out.length - 1];
      if (last && last.day === day) last.rows.push(e);
      else out.push({ day, rows: [e] });
    }
    return out;
  }, [items]);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Audit Log</h1>
          <p className="page-subtitle">
            Who changed what, when, from where — and what it was before. Passwords and other secrets are never recorded.
          </p>
        </div>
      </div>

      <div className="gallery-toolbar" style={{ flexWrap: "wrap" }}>
        <div className="search" style={{ minWidth: 220 }}>
          <input type="text" placeholder="Search summaries, names, ids…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the audit log" />
        </div>
        <select value={entityType} onChange={(e) => (setEntityType(e.target.value), setEntityId(null))} style={{ maxWidth: 180 }} aria-label="Type of thing changed">
          <option value="">Everything</option>
          {ENTITY_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <input type="text" list="audit-actions" placeholder="Action (e.g. user, report.delete)" value={action} onChange={(e) => setAction(e.target.value)} style={{ maxWidth: 240 }} aria-label="Action" />
        <datalist id="audit-actions">
          {KNOWN_ACTIONS.map((a) => (
            <option key={a} value={a} />
          ))}
        </datalist>
        <input type="text" placeholder="Changed by…" value={actor} onChange={(e) => setActor(e.target.value)} style={{ maxWidth: 160 }} aria-label="Changed by" />
        <input type="date" value={since} max={until || undefined} onChange={(e) => setSince(e.target.value)} style={{ maxWidth: 158 }} aria-label="From date" title="From" />
        <input type="date" value={until} min={since || undefined} onChange={(e) => setUntil(e.target.value)} style={{ maxWidth: 158 }} aria-label="To date" title="To" />
        {auth.isSuperuser && (
          <select value={orgId} onChange={(e) => setOrgId(e.target.value)} style={{ maxWidth: 200 }} aria-label="Organization">
            <option value="">All organizations</option>
            {organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {(entityId || filtersActive) && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-[0.8rem]">
          {entityId && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-accent-border bg-accent-soft py-0.5 pl-3 pr-1 text-accent-strong">
              History of <strong className="font-semibold">{entityId.label}</strong>
              <button type="button" className="grid h-5 w-5 place-items-center rounded-full border-0 bg-transparent text-accent-strong hover:bg-accent/15" onClick={() => setEntityId(null)} aria-label="Stop filtering to this item">
                <X size={12} />
              </button>
            </span>
          )}
          <button type="button" className="link-btn" onClick={clearFilters}>
            Clear all filters
          </button>
        </div>
      )}

      {error && <p className="alert alert-error">{error}</p>}
      {items === null && !error && <TableSkeleton columns={["Change", "By", "When"]} />}

      {items !== null && items.length === 0 && (
        <div className="empty-state">
          <p>{filtersActive ? "No recorded changes match those filters." : "Nothing has been recorded yet."}</p>
          {!filtersActive && <p className="empty-state-hint">Changes made from now on — templates, access, users, settings — will appear here.</p>}
        </div>
      )}

      {items !== null && items.length > 0 && (
        <>
          <p className="mb-3 mt-0 text-[0.8rem] text-text-faint">
            Showing {items.length.toLocaleString()} of {total.toLocaleString()} recorded change{total === 1 ? "" : "s"}, newest first.
          </p>
          {groups.map(({ day, rows }) => (
            <section key={day} className="mb-5">
              <h2 className="mb-2 mt-0 text-[0.72rem] font-semibold uppercase tracking-wider text-text-faint">{day}</h2>
              <div className="grid gap-2">
                {rows.map((e) => (
                  <Row key={e.id} event={e} open={open.has(e.id)} onToggle={() => toggle(e.id)} onFocusEntity={focusEntity} />
                ))}
              </div>
            </section>
          ))}
          {items.length < total && (
            <div className="flex justify-center py-2">
              <button type="button" className="btn" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : `Load ${Math.min(PAGE_SIZE, total - items.length)} more`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
