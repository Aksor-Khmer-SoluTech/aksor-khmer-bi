import { useEffect, useMemo, useRef, useState } from "react";
import { Check, FileText, KeyRound, Plus, Search, ShieldAlert, Users, X } from "lucide-react";
import { api, ApiError } from "../../api";
import ModalClose from "../../components/ModalClose";
import { useDialogRef } from "../../hooks";
import type { ReportAccessLevel, ReportMeta, Role, User } from "../../types";
import { roleLabel } from "./UserOverview";

/* Granting, from a user's window: one "Grant access" dialog with three kinds -- a role (cards that say what each
 * would add before you grant it), one template, or one permission. The user's window itself only lists what they
 * hold. */

/** <input type="date"> gives a bare "2026-01-01" -- which, as a plain string, sorts *before* any same-day timestamp
 * (rbac.py's expiry check compares strings against an ISO instant), so a bare date would read as already expired the
 * moment it's granted. Pin it to the end of that day instead. */
const endOfDay = (date: string) => (date ? `${date}T23:59:59Z` : null);

function ExpiryInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center gap-2 text-[0.78rem] text-text-dim">
      Ends
      <input
        type="date"
        value={value}
        min={new Date().toISOString().slice(0, 10)}
        onChange={(e) => onChange(e.target.value)}
        className="!w-auto"
        title="Optional: the grant ends at the end of this day"
      />
      {value ? (
        <button type="button" className="link-btn" onClick={() => onChange("")}>
          no end
        </button>
      ) : (
        <span className="text-text-faint">never</span>
      )}
    </label>
  );
}

/* ----------------------------------------------------------------- roles */

/** What the built-in roles are for, in a line (api/app/rbac.py seeds them with "Standard role: ROLE_…" as their
 * description, which says nothing a person picking one needs). A role someone created keeps its own description. */
const STANDARD_ROLE_HINTS: Record<string, string> = {
  ROLE_ORG_ADMIN: "Runs the organization: people, roles, templates, jobs, connections and settings.",
  ROLE_REPORT_ADMIN: "Builds and shares templates, with their folders, datasets and projects.",
  ROLE_REPORT_VIEWER: "Opens and renders templates.",
  ROLE_JOB_OPERATOR: "Runs scheduled jobs and watches their history.",
  ROLE_USER: "Sees the templates; can't render or change them.",
};

export function roleHint(role: Role): string {
  if (role.org_id === null) return "Every permission, in every organization — including ones added later.";
  if (role.description && !/^Standard role:/i.test(role.description)) return role.description;
  return STANDARD_ROLE_HINTS[role.name] ?? role.description ?? "No description.";
}

export function RolePicker({
  orgRoles,
  systemRoles,
  heldRoleIds,
  heldPermissions,
  onGrant,
}: {
  orgRoles: Role[] | null;
  systemRoles: Role[];
  heldRoleIds: Set<string>;
  heldPermissions: Set<string>;
  /** Resolves once granted (or after the system-role confirmation); rejects with the API's message. */
  onGrant: (role: Role, expiresAt: string | null) => Promise<void>;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expiry, setExpiry] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!orgRoles) return <p className="muted m-0">Loading roles…</p>;
  const roles = [...orgRoles, ...systemRoles];
  const selected = roles.find((r) => r.id === selectedId) ?? null;
  const adds = (role: Role) => (role.org_id === null ? [] : role.permissions.filter((p) => !heldPermissions.has(p)));

  async function grant() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await onGrant(selected, endOfDay(expiry));
      setSelectedId(null);
      setExpiry("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't grant the role");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-2" role="radiogroup" aria-label="Role to grant">
        {roles.map((role) => {
          const held = heldRoleIds.has(role.id);
          const system = role.org_id === null;
          const extra = adds(role);
          const on = selectedId === role.id;
          return (
            <button
              key={role.id}
              type="button"
              role="radio"
              aria-checked={on}
              disabled={held}
              onClick={() => setSelectedId(on ? null : role.id)}
              className={`flex cursor-pointer flex-col gap-1 rounded-[10px] border px-3 py-2.5 text-left disabled:cursor-default transition-[border-color,background,box-shadow] ${
                on
                  ? system
                    ? "border-danger bg-danger-soft shadow-[0_0_0_3px_var(--danger-soft)]"
                    : "border-accent bg-accent-soft shadow-[0_0_0_3px_var(--accent-soft)]"
                  : held
                    ? "cursor-default border-border-soft bg-bg-panel/60 opacity-70"
                    : system
                      ? "border-danger/40 bg-bg-raised hover:border-danger hover:bg-danger-soft/50"
                      : "border-border-soft bg-bg-raised hover:border-border-strong hover:bg-bg-panel/50"
              }`}
            >
              <span className="flex items-center gap-1.5">
                {system && <ShieldAlert size={13} className="shrink-0 text-danger-strong" />}
                <span className="truncate text-[0.84rem] font-semibold text-text">{roleLabel(role.name)}</span>
                <span className="ml-auto shrink-0">
                  {held ? (
                    <span className="inline-flex items-center gap-0.5 text-[0.68rem] font-medium text-success-strong">
                      <Check size={11} strokeWidth={3} /> held
                    </span>
                  ) : (
                    <span
                      className={`grid size-3.5 place-items-center rounded-full border ${
                        on ? (system ? "border-danger bg-danger" : "border-accent bg-accent") : "border-border-strong"
                      }`}
                      aria-hidden="true"
                    >
                      {on && <span className="size-1.5 rounded-full bg-bg" />}
                    </span>
                  )}
                </span>
              </span>
              <span className="line-clamp-2 min-h-[2.2em] text-[0.72rem] leading-snug text-text-dim">
                {roleHint(role)}
              </span>
              <span className="flex items-center gap-2 font-mono text-[0.66rem] text-text-faint">
                {system ? (
                  <span className="text-danger-strong">all organizations</span>
                ) : (
                  <>
                    <span>{role.permissions.length} permissions</span>
                    {!held && (extra.length > 0 ? <span className="text-accent-strong">+{extra.length} new</span> : <span>nothing new</span>)}
                  </>
                )}
              </span>
            </button>
          );
        })}
      </div>

      {selected && (
        <div
          className={`flex flex-col gap-2.5 rounded-[10px] border px-3.5 py-3 motion-safe:animate-[rise_200ms_ease-out_both] ${
            selected.org_id === null ? "border-danger/40 bg-danger-soft/40" : "border-accent-border bg-accent-soft/40"
          }`}
        >
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[0.8rem] text-text">
            <span className="font-semibold">{roleLabel(selected.name)}</span>
            {selected.org_id === null ? (
              <span className="text-text-dim">makes them a system administrator.</span>
            ) : adds(selected).length > 0 ? (
              <>
                <span className="text-text-dim">adds</span>
                {adds(selected).map((code) => (
                  <span key={code} className="rounded-[5px] border border-accent-border bg-bg px-1.5 py-[1px] font-mono text-[0.7rem] text-accent-strong">
                    {code}
                  </span>
                ))}
              </>
            ) : (
              <span className="text-text-dim">adds no permission they don't already hold — useful when another grant is about to end.</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <ExpiryInput value={expiry} onChange={setExpiry} />
            <span className="ml-auto flex gap-2">
              <button type="button" className="btn btn-sm" onClick={() => setSelectedId(null)}>
                Cancel
              </button>
              <button
                type="button"
                className={`btn btn-sm ${selected.org_id === null ? "btn-danger" : "btn-primary"}`}
                onClick={() => void grant()}
                disabled={busy}
              >
                {busy ? <span className="spinner" /> : <Plus size={14} />} Grant {roleLabel(selected.name)}
              </button>
            </span>
          </div>
          {error && <p className="alert alert-error m-0">{error}</p>}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- templates */

const LEVELS: { level: ReportAccessLevel; label: string; hint: string }[] = [
  { level: "view", label: "View", hint: "see it and its details" },
  { level: "render", label: "Render", hint: "run it and download its documents" },
  { level: "manage", label: "Manage", hint: "edit, replace and share it" },
];

export function TemplateGrantForm({
  userId,
  orgId,
  granted,
  onGranted,
}: {
  userId: string;
  orgId: string;
  /** Their current template grants, report_id -> level, to say so when one is picked again. */
  granted: Map<string, ReportAccessLevel>;
  onGranted: () => void;
}) {
  const [reports, setReports] = useState<ReportMeta[] | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<ReportMeta | null>(null);
  const [level, setLevel] = useState<ReportAccessLevel>("render");
  const [expiry, setExpiry] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .listReports()
      .then((all) => setReports(all.filter((r) => r.org_id === orgId).sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => setReports([]));
  }, [orgId]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = reports ?? [];
    return (q ? list.filter((r) => r.name.toLowerCase().includes(q) || (r.code ?? "").toLowerCase().includes(q)) : list).slice(0, 8);
  }, [reports, query]);

  async function grant() {
    if (!picked) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await api.grants.reports.grant("user", userId, picked.report_id, level, endOfDay(expiry));
      setDone(`${level} on ${picked.name}`);
      setPicked(null);
      setQuery("");
      setExpiry("");
      onGranted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't grant access");
    } finally {
      setBusy(false);
    }
  }

  const already = picked ? granted.get(picked.report_id) : undefined;

  return (
    <div className="flex flex-col gap-2.5 rounded-[10px] border border-border-soft bg-bg-raised/60 px-3.5 py-3">
      <div ref={boxRef} className="relative">
        {picked ? (
          <div className="flex items-center gap-2 rounded-lg border border-accent-border bg-accent-soft/50 px-2.5 py-1.5">
            <span className={`badge badge-${picked.template_ext}`}>{picked.template_ext}</span>
            <span className="min-w-0 flex-1 truncate text-[0.86rem] font-medium text-text">{picked.name}</span>
            {picked.code && <span className="font-mono text-[0.7rem] text-text-faint">{picked.code}</span>}
            <button
              type="button"
              className="grid size-6 cursor-pointer place-items-center rounded text-text-dim hover:bg-bg-panel"
              onClick={() => setPicked(null)}
              aria-label="Choose another template"
            >
              <X size={14} />
            </button>
          </div>
        ) : (
          <label className="relative block">
            <Search size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-faint" />
            <input
              type="text"
              className="!pl-8"
              placeholder={reports === null ? "Loading templates…" : `Find a template (${reports.length})…`}
              value={query}
              onFocus={() => setOpen(true)}
              onChange={(e) => {
                setQuery(e.target.value);
                setOpen(true);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && matches[0]) {
                  e.preventDefault();
                  setPicked(matches[0]);
                  setOpen(false);
                }
              }}
            />
          </label>
        )}
        {open && !picked && (
          <ul className="absolute inset-x-0 top-full z-10 m-0 mt-1 max-h-72 list-none overflow-auto rounded-lg border border-border bg-bg p-1 shadow-[var(--shadow-pop)]">
            {matches.length === 0 && <li className="px-2.5 py-2 text-[0.8rem] text-text-faint">No template matches “{query}”.</li>}
            {matches.map((r) => (
              <li key={r.report_id}>
                <button
                  type="button"
                  className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-left hover:bg-bg-panel"
                  onClick={() => {
                    setPicked(r);
                    setOpen(false);
                  }}
                >
                  <span className={`badge badge-${r.template_ext}`}>{r.template_ext}</span>
                  <span className="min-w-0 flex-1 truncate text-[0.84rem] text-text">{r.name}</span>
                  {granted.has(r.report_id) && <span className="text-[0.68rem] text-text-faint">has {granted.get(r.report_id)}</span>}
                  {r.is_draft && <span className="text-[0.68rem] text-text-faint">draft</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="segmented segmented-sm" role="radiogroup" aria-label="Access level">
          {LEVELS.map((l) => (
            <button
              key={l.level}
              type="button"
              role="radio"
              aria-checked={level === l.level}
              className={level === l.level ? "segmented-btn active" : "segmented-btn"}
              onClick={() => setLevel(l.level)}
              title={l.hint}
            >
              {l.label}
            </button>
          ))}
        </div>
        <span className="text-[0.74rem] text-text-faint">They can {LEVELS.find((l) => l.level === level)!.hint}.</span>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <ExpiryInput value={expiry} onChange={setExpiry} />
        <button type="button" className="btn btn-primary btn-sm ml-auto" onClick={() => void grant()} disabled={!picked || busy}>
          {busy ? <span className="spinner" /> : <Plus size={14} />} Grant access
        </button>
      </div>
      {already && (
        <p className="m-0 text-[0.74rem] text-text-dim">
          They already hold <b>{already}</b> on this template; this adds another grant beside it (the higher one counts).
        </p>
      )}
      {picked?.is_draft && level !== "manage" && (
        <p className="m-0 text-[0.74rem] text-text-dim">It's a draft: only people who can manage it see it until it's published.</p>
      )}
      <p className="m-0 text-[0.72rem] text-text-faint">
        To narrow a grant to some filter values (one branch, one province…), grant it from the template's own Access Privilege tab.
      </p>
      {error && <p className="alert alert-error m-0">{error}</p>}
      {done && <p className="alert alert-success m-0">Granted {done}.</p>}
    </div>
  );
}

/* ----------------------------------------------------------- permissions */

function PermissionPicker({
  catalog,
  held,
  onGrant,
}: {
  catalog: { code: string; description: string }[] | null;
  held: Set<string>;
  onGrant: (code: string, expiresAt: string | null) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [expiry, setExpiry] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!catalog) return <p className="muted m-0">Loading permissions…</p>;
  const q = query.trim().toLowerCase();
  const list = q ? catalog.filter((p) => p.code.includes(q) || p.description.toLowerCase().includes(q)) : catalog;

  async function grant() {
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      await onGrant(picked, endOfDay(expiry));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't grant the permission");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2.5">
      <label className="relative block">
        <Search size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-faint" />
        <input type="text" className="!pl-8" placeholder="Find a permission…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <ul className="m-0 max-h-[340px] list-none overflow-auto rounded-[10px] border border-border-soft p-1" role="radiogroup" aria-label="Permission to grant">
        {list.length === 0 && <li className="px-2.5 py-2 text-[0.8rem] text-text-faint">No permission matches “{query}”.</li>}
        {list.map((p) => {
          const has = held.has(p.code);
          const on = picked === p.code;
          return (
            <li key={p.code}>
              <button
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => setPicked(on ? null : p.code)}
                className={`flex w-full cursor-pointer items-start gap-2.5 rounded-md px-2.5 py-1.5 text-left ${on ? "bg-accent-soft" : "hover:bg-bg-panel"}`}
              >
                <span
                  className={`mt-[3px] grid size-3.5 shrink-0 place-items-center rounded-full border ${on ? "border-accent bg-accent" : "border-border-strong"}`}
                  aria-hidden="true"
                >
                  {on && <span className="size-1.5 rounded-full bg-bg" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-[0.78rem] text-text">{p.code}</span>
                    {has && <span className="text-[0.66rem] font-medium text-success-strong">held</span>}
                  </span>
                  <span className="block text-[0.72rem] leading-snug text-text-dim">{p.description}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-center gap-3">
        <ExpiryInput value={expiry} onChange={setExpiry} />
        <button type="button" className="btn btn-primary btn-sm ml-auto" onClick={() => void grant()} disabled={!picked || busy}>
          {busy ? <span className="spinner" /> : <Plus size={14} />} Grant {picked ?? "permission"}
        </button>
      </div>
      {picked && held.has(picked) && (
        <p className="m-0 text-[0.74rem] text-text-dim">They hold it already (through a role or another grant); a direct grant keeps it when that one ends.</p>
      )}
      {error && <p className="alert alert-error m-0">{error}</p>}
    </div>
  );
}

/* ---------------------------------------------------------------- dialog */

export type GrantKind = "role" | "template" | "permission";

export function GrantAccessDialog({
  open,
  initialKind = "role",
  user,
  orgRoles,
  systemRoles,
  heldRoleIds,
  heldPermissions,
  catalog,
  templateGrants,
  canGrantTemplates,
  onGrantRole,
  onGrantPermission,
  onGrantedTemplate,
  onClose,
}: {
  open: boolean;
  initialKind?: GrantKind;
  user: User;
  orgRoles: Role[] | null;
  systemRoles: Role[];
  heldRoleIds: Set<string>;
  heldPermissions: Set<string>;
  catalog: { code: string; description: string }[] | null;
  templateGrants: Map<string, ReportAccessLevel>;
  canGrantTemplates: boolean;
  onGrantRole: (role: Role, expiresAt: string | null) => Promise<void>;
  onGrantPermission: (code: string, expiresAt: string | null) => Promise<void>;
  onGrantedTemplate: () => void;
  onClose: () => void;
}) {
  const [kind, setKind] = useState<GrantKind>(initialKind);
  const ref = useDialogRef(open, () => setKind(initialKind));
  const kinds: { id: GrantKind; label: string; hint: string; icon: typeof Users }[] = [
    { id: "role", label: "A role", hint: "a set of permissions", icon: Users },
    ...(canGrantTemplates ? [{ id: "template" as const, label: "A template", hint: "one template, nothing else", icon: FileText }] : []),
    { id: "permission", label: "A permission", hint: "one permission, directly", icon: KeyRound },
  ];

  return (
    <dialog ref={ref} className="modal grant-dialog" onCancel={onClose} onClose={onClose}>
      <ModalClose />
      <h2 className="panel-title m-0">Grant access</h2>
      <p className="muted m-0 mt-0.5 text-[0.82rem]">
        to <b className="text-text">{user.display_name || user.username}</b> <span className="font-mono">({user.username})</span>
      </p>

      <div className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2" role="tablist" aria-label="What to grant">
        {kinds.map((k) => {
          const Icon = k.icon;
          const on = kind === k.id;
          return (
            <button
              key={k.id}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => setKind(k.id)}
              className={`flex cursor-pointer items-center gap-2.5 rounded-[10px] border px-3 py-2 text-left transition-colors ${
                on ? "border-accent bg-accent-soft" : "border-border-soft hover:border-border-strong hover:bg-bg-panel/50"
              }`}
            >
              <span className={`grid size-8 shrink-0 place-items-center rounded-lg ${on ? "bg-accent text-accent-ink" : "bg-bg-panel text-text-dim"}`}>
                <Icon size={15} />
              </span>
              <span className="min-w-0">
                <span className="block text-[0.84rem] font-semibold text-text">{k.label}</span>
                <span className="block truncate text-[0.7rem] text-text-faint">{k.hint}</span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-4" role="tabpanel">
        {open && kind === "role" && (
          <RolePicker
            orgRoles={orgRoles}
            systemRoles={systemRoles}
            heldRoleIds={heldRoleIds}
            heldPermissions={heldPermissions}
            onGrant={async (role, expiresAt) => {
              await onGrantRole(role, expiresAt);
              onClose();
            }}
          />
        )}
        {open && kind === "template" && canGrantTemplates && (
          <TemplateGrantForm
            userId={user.id}
            orgId={user.org_id}
            granted={templateGrants}
            onGranted={() => {
              onGrantedTemplate();
              onClose();
            }}
          />
        )}
        {open && kind === "permission" && (
          <PermissionPicker
            catalog={catalog}
            held={heldPermissions}
            onGrant={async (code, expiresAt) => {
              await onGrantPermission(code, expiresAt);
              onClose();
            }}
          />
        )}
      </div>
    </dialog>
  );
}
