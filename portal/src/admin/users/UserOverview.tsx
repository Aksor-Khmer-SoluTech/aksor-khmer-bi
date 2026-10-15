import { useMemo, useState } from "react";
import { ArrowUpRight, Check, ChevronRight, FolderClosed, Package, ShieldCheck, TriangleAlert } from "lucide-react";
import { ago, plural, until } from "../../relativeTime";
import type { ReportAccessLevel, UserOverview } from "../../types";

/* The user detail panel's picture of one account (GET /users/{id}/overview): what they've put in, what they can
 * reach, and where every permission comes from. Three pieces: the strip above the tabs, the Templates tab, and the
 * permission map + "where they have access" on the Roles & permissions tab. */

/** ROLE_REPORT_ADMIN -> "Report Admin". A role someone named themselves is shown as they wrote it. */
export function roleLabel(name: string): string {
  if (!/^ROLE_[A-Z0-9_]+$/.test(name)) return name;
  return name
    .slice(5)
    .split("_")
    .map((w) => (w === "ORG" ? "Org" : w.charAt(0) + w.slice(1).toLowerCase()))
    .join(" ");
}

const LEVEL_STYLE: Record<ReportAccessLevel, string> = {
  manage: "bg-accent-soft text-accent-strong border-accent-border",
  render: "bg-info-soft text-info-strong border-transparent",
  view: "bg-bg-panel text-text-dim border-border-soft",
};

const TYPE_COLOR: Record<string, string> = { docx: "var(--info)", xlsx: "var(--success)", html: "var(--highlight)" };

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-[0.62rem] font-semibold tracking-[0.12em] text-text-faint uppercase">{children}</span>;
}

function LevelChip({ level }: { level: ReportAccessLevel | null }) {
  if (!level) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full border border-transparent bg-danger-soft px-2 py-[1px] text-[0.7rem] font-medium text-danger-strong"
        title="They uploaded it, but no role or grant lets them open it now"
      >
        <TriangleAlert size={11} /> no access now
      </span>
    );
  }
  return <span className={`rounded-full border px-2 py-[1px] text-[0.7rem] font-medium ${LEVEL_STYLE[level]}`}>{level}</span>;
}

function Expiry({ at }: { at: string | null }) {
  if (!at) return null;
  return (
    <span className="text-[0.68rem] font-medium text-[var(--highlight-strong)]" title={new Date(at).toLocaleString()}>
      ends {until(at).replace(/^on /, "")}
    </span>
  );
}

function Source({ kind, name, expiresAt }: { kind: "role" | "direct"; name: string | null; expiresAt: string | null }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-[5px] border px-1.5 py-[1px] text-[0.68rem] leading-[1.35] ${
        kind === "direct" ? "border-highlight/40 bg-highlight-soft text-text" : "border-border-soft bg-bg-raised text-text-dim"
      }`}
      title={kind === "direct" ? "Granted to this user directly" : `From the role ${name}`}
    >
      {kind === "direct" ? "direct" : roleLabel(name ?? "")}
      {expiresAt && <Expiry at={expiresAt} />}
    </span>
  );
}

/* ---------------------------------------------------------------- the strip */

export type StripTarget = "templates" | "reach" | "permissions";

export function OverviewStrip({
  overview,
  onOpen,
}: {
  overview: UserOverview | null;
  /** Where a card leads: its tab, scrolled to its section. */
  onOpen: (target: StripTarget) => void;
}) {
  const figure = "font-display text-[1.65rem] leading-none font-semibold tracking-tight tabular-nums text-text";
  const cell =
    "group flex min-w-0 cursor-pointer flex-col gap-2 rounded-[10px] px-3.5 py-3 text-left transition-colors hover:bg-bg-raised/70 focus-visible:bg-bg-raised/70 focus-visible:outline-none";

  if (!overview) {
    return (
      <div className="mb-4 grid grid-cols-1 gap-1 rounded-xl border border-border-soft bg-bg-raised/40 p-1 sm:grid-cols-3" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex flex-col gap-2.5 px-3.5 py-3">
            <span className="h-2 w-20 animate-pulse rounded bg-bg-panel" />
            <span className="h-6 w-14 animate-pulse rounded bg-bg-panel" />
            <span className="h-1.5 w-full animate-pulse rounded bg-bg-panel" />
          </div>
        ))}
      </div>
    );
  }

  const t = overview.templates;
  const r = overview.reach;
  const reachable = r.manage + r.render + r.view;
  const types = Object.entries(t.by_type).sort((a, b) => b[1] - a[1]);

  return (
    <div className="mb-4 grid grid-cols-1 gap-1 rounded-xl border border-border-soft bg-bg-raised/40 p-1 sm:grid-cols-3">
      <button type="button" className={cell} onClick={() => onOpen("templates")}>
        <span className="flex items-center justify-between">
          <Eyebrow>Templates uploaded</Eyebrow>
          <ArrowUpRight size={13} className="text-text-faint opacity-0 transition-opacity group-hover:opacity-100" />
        </span>
        <span className="flex items-baseline gap-2">
          <span className={figure}>{t.contributed}</span>
          <span className="truncate text-[0.74rem] text-text-dim">
            {t.contributed === 0 ? "none yet" : `${t.started} started · ${plural(t.versions, "version")}`}
          </span>
        </span>
        <span className="flex h-1.5 overflow-hidden rounded-full bg-bg-panel" aria-hidden="true">
          {types.map(([ext, n]) => (
            <span key={ext} style={{ width: `${(n / Math.max(1, t.contributed)) * 100}%`, background: TYPE_COLOR[ext] ?? "var(--text-faint)" }} />
          ))}
        </span>
        {types.length > 0 && (
          <span className="flex flex-wrap gap-x-2.5 text-[0.68rem] text-text-faint">
            {types.map(([ext, n]) => (
              <span key={ext} className="inline-flex items-center gap-1">
                <span className="size-1.5 rounded-full" style={{ background: TYPE_COLOR[ext] ?? "var(--text-faint)" }} />
                {ext} {n}
              </span>
            ))}
          </span>
        )}
      </button>

      <button type="button" className={cell} onClick={() => onOpen("reach")}>
        <span className="flex items-center justify-between">
          <Eyebrow>Can open</Eyebrow>
          <ArrowUpRight size={13} className="text-text-faint opacity-0 transition-opacity group-hover:opacity-100" />
        </span>
        <span className="flex items-baseline gap-2">
          <span className={figure}>{reachable}</span>
          <span className="min-w-0 text-[0.74rem] leading-snug text-text-dim">
            of {plural(r.total, "template")}
            {r.org_wide && <> · all via <span className="font-mono">{r.org_wide}</span></>}
          </span>
        </span>
        <span className="flex h-1.5 overflow-hidden rounded-full bg-bg-panel" aria-hidden="true">
          <span style={{ width: `${(r.manage / Math.max(1, r.total)) * 100}%` }} className="bg-accent" />
          <span style={{ width: `${(r.render / Math.max(1, r.total)) * 100}%` }} className="bg-info" />
          <span style={{ width: `${(r.view / Math.max(1, r.total)) * 100}%` }} className="bg-text-faint/60" />
        </span>
        <span className="flex flex-wrap gap-x-2.5 text-[0.68rem] text-text-faint">
          <span className="inline-flex items-center gap-1"><span className="size-1.5 rounded-full bg-accent" />manage {r.manage}</span>
          <span className="inline-flex items-center gap-1"><span className="size-1.5 rounded-full bg-info" />render {r.render}</span>
          <span className="inline-flex items-center gap-1"><span className="size-1.5 rounded-full bg-text-faint/60" />view {r.view}</span>
        </span>
      </button>

      <button type="button" className={cell} onClick={() => onOpen("permissions")}>
        <span className="flex items-center justify-between">
          <Eyebrow>Roles &amp; permissions</Eyebrow>
          <ArrowUpRight size={13} className="text-text-faint opacity-0 transition-opacity group-hover:opacity-100" />
        </span>
        <span className="flex items-baseline gap-2">
          <span className={figure}>{overview.permissions.length}</span>
          <span className="truncate text-[0.74rem] text-text-dim">
            {overview.is_system_admin ? "system administrator" : plural(overview.permissions.length, "permission").replace(/^\d+ /, "")}
          </span>
        </span>
        <span className="flex flex-wrap gap-1">
          {overview.is_system_admin && (
            <span className="inline-flex items-center gap-1 rounded-[5px] bg-accent-soft px-1.5 py-[1px] text-[0.68rem] font-medium text-accent-strong">
              <ShieldCheck size={11} /> every permission
            </span>
          )}
          {overview.roles.length === 0 && !overview.is_system_admin && <span className="text-[0.72rem] text-text-faint">No roles</span>}
          {overview.roles.map((role) => (
            <Source key={role.name} kind="role" name={role.name} expiresAt={role.expires_at} />
          ))}
        </span>
      </button>
    </div>
  );
}

/* ------------------------------------------------------------ templates tab */

export function TemplatesTab({ overview }: { overview: UserOverview | null }) {
  const [type, setType] = useState<string>("all");
  if (!overview) return <p className="muted">Loading…</p>;
  const t = overview.templates;
  if (t.contributed === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border px-5 py-8 text-center">
        <p className="m-0 text-[0.9rem] text-text">No templates uploaded yet</p>
        <p className="muted m-0 mt-1 text-[0.78rem]">
          Templates they register, or new versions they upload, show up here.
          {overview.reach.manage > 0 && ` They can manage ${plural(overview.reach.manage, "template")} already.`}
        </p>
      </div>
    );
  }
  const items = type === "all" ? t.items : t.items.filter((i) => i.template_ext === type);
  const lost = t.items.filter((i) => i.access_level === null).length;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {["all", ...Object.keys(t.by_type).sort()].map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setType(key)}
            className={`cursor-pointer rounded-full border px-2.5 py-[3px] text-[0.74rem] transition-colors ${
              type === key ? "border-accent-border bg-accent-soft font-medium text-accent-strong" : "border-border-soft text-text-dim hover:bg-bg-raised"
            }`}
          >
            {key === "all" ? `All ${t.contributed}` : `${key} ${t.by_type[key]}`}
          </button>
        ))}
        {lost > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 text-[0.74rem] text-danger-strong">
            <TriangleAlert size={12} /> {plural(lost, "template")} they can no longer open
          </span>
        )}
      </div>

      <ul className="m-0 list-none overflow-hidden rounded-xl border border-border-soft bg-bg-raised/50 p-0">
        {items.map((item, i) => (
          <li
            key={item.report_id}
            className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 border-b border-border-soft px-3.5 py-2.5 last:border-b-0 motion-safe:animate-[rise_280ms_ease-out_both] sm:grid-cols-[auto_minmax(0,1fr)_7rem_6.5rem_auto]"
            style={{ animationDelay: `${Math.min(i, 12) * 22}ms` }}
          >
            <span className={`badge badge-${item.template_ext}`}>{item.template_ext}</span>
            <span className="min-w-0">
              <a href={`#/reports/${encodeURIComponent(item.report_id)}`} className="block truncate text-[0.86rem] font-medium text-text hover:text-accent-strong">
                {item.name}
                {item.is_draft && <span className="ml-1.5 text-[0.68rem] font-normal text-text-faint">draft</span>}
              </a>
              <span className="flex min-w-0 items-center gap-0.5 truncate text-[0.7rem] text-text-faint">
                {item.folder_path.length === 0 ? (
                  "Root"
                ) : (
                  item.folder_path.map((seg, n) => (
                    <span key={n} className="inline-flex items-center gap-0.5">
                      {n > 0 && <ChevronRight size={10} />}
                      {seg}
                    </span>
                  ))
                )}
              </span>
            </span>
            <span className="hidden text-[0.74rem] text-text-dim sm:block">
              {item.started ? "started it" : "added versions"}
              <span className="block font-mono text-[0.68rem] text-text-faint">{plural(item.versions, "version")}</span>
            </span>
            <span className="hidden text-[0.74rem] text-text-dim sm:block" title={item.last_upload_at ? new Date(item.last_upload_at).toLocaleString() : undefined}>
              {item.last_upload_at ? ago(item.last_upload_at) : "—"}
            </span>
            <LevelChip level={item.access_level} />
          </li>
        ))}
      </ul>
      {t.contributed > t.items.length && (
        <p className="muted m-0 text-[0.74rem]">The {t.items.length} most recent of {t.contributed}.</p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ permission map */

export const PERMISSION_AREAS: [string, string][] = [
  ["report", "Templates"],
  ["folder", "Folders"],
  ["project", "Projects"],
  ["dataset", "Datasets"],
  ["analyze", "Analyze"],
  ["job", "Jobs"],
  ["connection", "Connections"],
  ["secret", "Secrets"],
  ["driver", "JDBC drivers"],
  ["font", "Fonts"],
  ["protected_terms", "Protected terms"],
  ["client", "API clients"],
  ["user", "Users"],
  ["role", "Roles"],
  ["audit", "Audit"],
  ["settings", "Settings"],
  ["org", "Organizations"],
];

export function PermissionMap({
  overview,
  catalog,
}: {
  overview: UserOverview | null;
  catalog: { code: string; description: string }[] | null;
}) {
  const [heldOnly, setHeldOnly] = useState(false);
  const held = useMemo(() => new Map((overview?.permissions ?? []).map((p) => [p.code, p])), [overview]);

  const groups = useMemo(() => {
    const all = new Map<string, { code: string; description: string }>();
    for (const p of catalog ?? []) all.set(p.code, p);
    for (const p of overview?.permissions ?? []) if (!all.has(p.code)) all.set(p.code, p);
    const byArea = new Map<string, { code: string; description: string }[]>();
    for (const p of all.values()) {
      const area = p.code.split(":")[0];
      byArea.set(area, [...(byArea.get(area) ?? []), p]);
    }
    const known = PERMISSION_AREAS.filter(([key]) => byArea.has(key));
    const extra = [...byArea.keys()].filter((k) => !PERMISSION_AREAS.some(([a]) => a === k)).map((k): [string, string] => [k, k]);
    return [...known, ...extra].map(([key, label]) => ({ key, label, perms: byArea.get(key)! }));
  }, [catalog, overview]);

  if (!overview) return <p className="muted">Loading…</p>;

  return (
    <div id="user-section-permissions" className="flex scroll-mt-4 flex-col gap-2.5 rounded-xl">
      <div className="flex items-center gap-3">
        <span className="field-label m-0">Permissions</span>
        <span className="text-[0.74rem] text-text-faint">
          {overview.is_system_admin ? "System administrator: every permission, in every organization" : `${overview.permissions.length} held`}
        </span>
        <label className="checkbox-label ml-auto text-[0.76rem]">
          <input type="checkbox" checked={heldOnly} onChange={(e) => setHeldOnly(e.target.checked)} /> Held only
        </label>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(232px,1fr))] gap-2">
        {groups.map((group) => {
          const perms = heldOnly && !overview.is_system_admin ? group.perms.filter((p) => held.has(p.code)) : group.perms;
          if (perms.length === 0) return null;
          const count = overview.is_system_admin ? group.perms.length : group.perms.filter((p) => held.has(p.code)).length;
          return (
            <section key={group.key} className="rounded-[10px] border border-border-soft bg-bg-raised/60 px-3 py-2.5">
              <header className="mb-1.5 flex items-baseline justify-between">
                <span className="text-[0.8rem] font-semibold text-text">{group.label}</span>
                <span className="font-mono text-[0.66rem] text-text-faint tabular-nums">
                  {count}/{group.perms.length}
                </span>
              </header>
              <ul className="m-0 flex list-none flex-col gap-1 p-0">
                {perms.map((p) => {
                  const mine = held.get(p.code);
                  const on = overview.is_system_admin || !!mine;
                  return (
                    <li key={p.code} className={`flex flex-wrap items-center gap-1.5 ${on ? "" : "opacity-45"}`} title={p.description}>
                      <span
                        className={`grid size-3.5 shrink-0 place-items-center rounded-[4px] ${on ? "bg-accent text-accent-ink" : "border border-border-strong"}`}
                        aria-label={on ? "held" : "not held"}
                      >
                        {on && <Check size={10} strokeWidth={3} />}
                      </span>
                      <span className="font-mono text-[0.74rem] text-text">{p.code.split(":").slice(1).join(":")}</span>
                      {mine?.sources.map((s, n) => <Source key={n} kind={s.kind} name={s.name} expiresAt={s.expires_at} />)}
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}

export function WhereTheyHaveAccess({
  overview,
  onRevokeReport,
  onGrantTemplate,
}: {
  overview: UserOverview | null;
  /** Given when the viewer may revoke a template grant made to this user directly (report:manage). */
  onRevokeReport?: (grantId: string) => void;
  /** Opens the grant dialog on "A template". */
  onGrantTemplate?: () => void;
}) {
  if (!overview) return null;
  const { folder_grants: folders, report_grants: reports, reach } = overview;
  const none = folders.length === 0 && reports.length === 0;
  return (
    <div id="user-section-reach" className="flex scroll-mt-4 flex-col gap-2 rounded-xl">
      <div className="flex items-baseline gap-3">
        <span className="field-label m-0">Where they have access</span>
        <span className="text-[0.74rem] text-text-faint">
          {reach.org_wide
            ? `Every template, through ${reach.org_wide}${none ? "" : " — and these grants on top"}`
            : none
              ? "No folder or template grants — only what their permissions allow"
              : "Folder grants reach everything below them"}
        </span>
        {onGrantTemplate && (
          <button type="button" className="link-btn ml-auto text-[0.78rem]" onClick={onGrantTemplate}>
            + Grant a template
          </button>
        )}
      </div>
      {!none && (
        <ul className="m-0 list-none overflow-hidden rounded-xl border border-border-soft bg-bg-raised/50 p-0">
          {folders.map((g) => (
            <li key={`f${g.folder_id}${g.via_role ?? ""}`} className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-border-soft px-3.5 py-2 last:border-b-0">
              {g.is_project ? <Package size={14} className="text-accent-strong" /> : <FolderClosed size={14} className="text-text-faint" />}
              <span className="flex min-w-0 items-center gap-0.5 text-[0.84rem] text-text">
                {g.path.map((seg, n) => (
                  <span key={n} className="inline-flex items-center gap-0.5">
                    {n > 0 && <ChevronRight size={11} className="text-text-faint" />}
                    {seg}
                  </span>
                ))}
              </span>
              <span className="text-[0.72rem] text-text-faint">{plural(g.templates, "template")}</span>
              <span className="ml-auto inline-flex items-center gap-1.5">
                <Source kind={g.via_role ? "role" : "direct"} name={g.via_role} expiresAt={g.expires_at} />
                <LevelChip level={g.level} />
              </span>
            </li>
          ))}
          {reports.map((g) => (
            <li key={`r${g.report_id}${g.via_role ?? ""}`} className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-border-soft px-3.5 py-2 last:border-b-0">
              <span className={`badge badge-${g.template_ext}`}>{g.template_ext}</span>
              <a href={`#/reports/${encodeURIComponent(g.report_id)}`} className="text-[0.84rem] text-text hover:text-accent-strong">
                {g.name}
              </a>
              <span className="ml-auto inline-flex items-center gap-1.5">
                <Source kind={g.via_role ? "role" : "direct"} name={g.via_role} expiresAt={g.expires_at} />
                <LevelChip level={g.level} />
                {onRevokeReport && !g.via_role && (
                  <button type="button" className="link-btn ml-1 text-[0.74rem]" onClick={() => onRevokeReport(g.grant_id)}>
                    revoke
                  </button>
                )}
              </span>
              {g.parameter_limits && (
                <span className="basis-full pl-[3.1rem] text-[0.7rem] text-text-faint">
                  only{" "}
                  {Object.entries(g.parameter_limits)
                    .map(([name, values]) => `${name}: ${values.join(", ")}`)
                    .join(" · ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
