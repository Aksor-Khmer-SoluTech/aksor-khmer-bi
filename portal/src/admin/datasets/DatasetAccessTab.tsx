import { useEffect, useState } from "react";
import { Lock, LockOpen, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import type { Dataset, DatasetAccess, DatasetAccessMode, DatasetGrant, Role, User } from "../../types";

/** A dataset's row-level access (api/app/datasets.py effective_limits): open -- the reports built on it decide who
 * runs them -- or restricted to the people and roles below, each only with the filter values ticked for them. A
 * restricted dataset's limits apply on top of each report's own grants: both have to allow a value. */

/** `expires_at` is compared as an ISO string server-side, so a bare date would read as already past: end of day. */
const toExpiresAt = (date: string) => (date ? `${date}T23:59:59Z` : null);

const initials = (name: string) =>
  name
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("") || "?";

export default function DatasetAccessTab({ dataset, onModeChange }: { dataset: Dataset; onModeChange: (mode: DatasetAccessMode) => void }) {
  const [access, setAccess] = useState<DatasetAccess | null>(null);
  const [users, setUsers] = useState<User[] | null>(null);
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [revoke, setRevoke] = useState<DatasetGrant | null>(null);

  const [subjectType, setSubjectType] = useState<"user" | "role">("role");
  const [subjectId, setSubjectId] = useState("");
  const [level, setLevel] = useState<"run" | "build">("run");
  const [expiry, setExpiry] = useState("");
  const [limits, setLimits] = useState<Record<string, string[]>>({});

  // Only a filter with a fixed list of choices can be limited here (one fed by an API is checked at run time only).
  const limitable = dataset.parameters.filter((p) => p.options && p.options.length > 0);
  const labelOf = (name: string, value: string) => {
    const p = dataset.parameters.find((x) => x.name === name);
    const option = p?.options?.find((o) => o.value === value);
    return { filter: p?.label || name, value: option?.label ? `${option.label} (${value})` : value };
  };

  function load() {
    api.datasets.access
      .get(dataset.id)
      .then(setAccess)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load who has access"));
  }
  useEffect(() => {
    load();
    api.users.list(dataset.org_id).then(setUsers).catch(() => setUsers([]));
    api.roles.list(dataset.org_id).then(setRoles).catch(() => setRoles([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset.id]);

  async function setMode(mode: DatasetAccessMode) {
    setSaving(true);
    setError(null);
    try {
      const next = await api.datasets.access.setMode(dataset.id, mode);
      setAccess(next);
      onModeChange(next.mode);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change it");
    } finally {
      setSaving(false);
    }
  }

  async function grant() {
    setSaving(true);
    setError(null);
    try {
      await api.datasets.access.grant(dataset.id, {
        subject_type: subjectType,
        subject_id: subjectId,
        level,
        parameter_limits: Object.keys(limits).length ? limits : null,
        expires_at: toExpiresAt(expiry),
      });
      setSubjectId("");
      setExpiry("");
      setLimits({});
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add it");
    } finally {
      setSaving(false);
    }
  }

  async function confirmRevoke() {
    if (!revoke) return;
    const target = revoke;
    setRevoke(null);
    try {
      await api.datasets.access.revoke(dataset.id, target.id);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't revoke it");
    }
  }

  if (!access) return error ? <p className="alert alert-error">{error}</p> : <p className="muted">Loading…</p>;
  const restricted = access.mode === "restricted";

  const MODES: { mode: DatasetAccessMode; icon: typeof Lock; title: string; blurb: string }[] = [
    {
      mode: "open",
      icon: LockOpen,
      title: "Anyone who may run a report on it",
      blurb: "Each report's Access Privilege decides who runs it, and with which values.",
    },
    {
      mode: "restricted",
      icon: Lock,
      title: "Only the people and roles below",
      blurb: "Every report built on it, whoever made it, only gives them the values ticked here.",
    },
  ];

  return (
    <div className="grid gap-4">
      {error && <p className="alert alert-error m-0">{error}</p>}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Who can use this dataset">
        {MODES.map(({ mode, icon: Icon, title, blurb }) => {
          const on = access.mode === mode;
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={on}
              disabled={saving}
              onClick={() => (on ? undefined : mode === "open" ? setConfirmOpen(true) : setMode("restricted"))}
              className={`grid gap-1 rounded-[12px] border p-3.5 text-left transition-colors ${
                on ? "border-accent-border bg-accent-soft" : "border-border-soft bg-bg-raised hover:border-accent-border"
              }`}
            >
              <span className="flex items-center gap-2 font-semibold text-text">
                <Icon size={16} aria-hidden="true" className={on ? "text-accent-strong" : "text-text-dim"} /> {title}
              </span>
              <span className="text-[0.82rem] text-text-dim">{blurb}</span>
            </button>
          );
        })}
      </div>

      <div className={`overflow-hidden rounded-[12px] border border-border-soft ${restricted ? "" : "opacity-60"}`}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-soft bg-bg-panel px-3.5 py-2.5">
          <b className="font-semibold">Who can use “{dataset.title}”</b>
          {!restricted && <span className="text-[0.78rem] text-text-dim">Kept, and used only while it's restricted</span>}
        </div>
        {access.grants.length === 0 ? (
          <p className="m-0 px-3.5 py-3 text-[0.88rem] text-text-dim">
            {restricted
              ? "Nobody yet — until you add someone, only dataset managers can run the reports built on it."
              : "Nobody listed. Add people or roles here before you restrict it."}
          </p>
        ) : (
          access.grants.map((g) => {
            return (
              <div
                key={g.id}
                className="grid grid-cols-1 items-center gap-2 border-b border-border-soft px-3.5 py-2.5 last:border-b-0 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,0.8fr)_minmax(0,1.8fr)_auto]"
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent-soft text-[0.72rem] font-semibold text-accent-strong">
                    {initials(g.subject_name)}
                  </span>
                  <div className="min-w-0">
                    <b className="block truncate font-semibold">{g.subject_name}</b>
                    <span className="text-[0.75rem] text-text-faint">
                      {g.subject_type === "role" ? "Role" : "Person"}
                      {g.expires_at && ` · until ${new Date(g.expires_at).toLocaleDateString()}`}
                    </span>
                  </div>
                </div>
                <div className="text-[0.85rem]">{g.level === "build" ? "Build & run" : "Run"}</div>
                <div className="flex flex-wrap gap-1.5">
                  {!g.parameter_limits || Object.keys(g.parameter_limits).length === 0 ? (
                    <span className="limit-chip border-success/30 bg-success-soft text-success">All values</span>
                  ) : (
                    Object.entries(g.parameter_limits).flatMap(([name, values]) =>
                      values.map((v) => {
                        const l = labelOf(name, v);
                        return (
                          <span key={`${name}=${v}`} className="limit-chip">
                            {l.filter}: {l.value}
                          </span>
                        );
                      }),
                    )
                  )}
                </div>
                <button type="button" className="btn btn-ghost btn-sm icon-only justify-self-end" aria-label={`Revoke ${g.subject_name}`} onClick={() => setRevoke(g)}>
                  <Trash2 size={14} />
                </button>
              </div>
            );
          })
        )}
      </div>

      <div className="grid gap-3 rounded-[12px] border border-border-soft bg-bg-raised p-3.5">
        <b className="font-semibold">Add people or roles</b>
        <div className="grid grid-cols-1 gap-x-3 sm:grid-cols-[8rem_minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <label>
            <span>Who</span>
            <select
              value={subjectType}
              onChange={(e) => {
                setSubjectType(e.target.value as "user" | "role");
                setSubjectId("");
              }}
            >
              <option value="role">A role</option>
              <option value="user">A person</option>
            </select>
          </label>
          <label>
            <span>{subjectType === "role" ? "Role" : "Person"}</span>
            <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
              <option value="">{subjectType === "role" ? "Choose a role…" : "Choose a person…"}</option>
              {subjectType === "role"
                ? roles
                    ?.filter((r) => r.org_id === dataset.org_id)
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}
                      </option>
                    ))
                : users?.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.display_name ? `${u.display_name} (${u.username})` : u.username}
                    </option>
                  ))}
            </select>
          </label>
          <label>
            <span>May</span>
            <select value={level} onChange={(e) => setLevel(e.target.value as "run" | "build")}>
              <option value="run">Run its reports</option>
              <option value="build">Build &amp; run</option>
            </select>
          </label>
          <label>
            <span>
              Until <span className="muted">(optional)</span>
            </span>
            <input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
          </label>
        </div>
        {users !== null && users.length === 0 && subjectType === "user" && (
          <p className="field-hint m-0">No people to choose from — listing them needs the user:manage permission. A role works the same way.</p>
        )}

        {limitable.length > 0 && (
          <div className="grant-limits mt-0">
            <p className="field-hint grant-limits-hint">
              “All values” leaves a filter open to them; “Only these” lets them run every report on this dataset with just the ticked values.
            </p>
            {limitable.map((p) => {
              const selected = limits[p.name];
              return (
                <fieldset key={p.name} className="grant-limit">
                  <legend>{p.label || p.name}</legend>
                  <label className="checkbox-label">
                    <input
                      type="radio"
                      name={`ds-limit-${p.name}`}
                      checked={selected === undefined}
                      onChange={() =>
                        setLimits((prev) => {
                          const { [p.name]: _dropped, ...rest } = prev;
                          return rest;
                        })
                      }
                    />
                    All values
                  </label>
                  <label className="checkbox-label">
                    <input type="radio" name={`ds-limit-${p.name}`} checked={selected !== undefined} onChange={() => setLimits((prev) => ({ ...prev, [p.name]: prev[p.name] ?? [] }))} />
                    Only these
                  </label>
                  {selected !== undefined && (
                    <div className="grant-limit-options">
                      {p.options!.map((o) => (
                        <label key={o.value} className="checkbox-label">
                          <input
                            type="checkbox"
                            checked={selected.includes(o.value)}
                            onChange={(e) =>
                              setLimits((prev) => ({ ...prev, [p.name]: e.target.checked ? [...selected, o.value] : selected.filter((v) => v !== o.value) }))
                            }
                          />
                          {o.label ? `${o.label} (${o.value})` : o.value}
                        </label>
                      ))}
                      {selected.length === 0 && <span className="run-field-note run-field-note-warn">Tick at least one value.</span>}
                    </div>
                  )}
                </fieldset>
              );
            })}
          </div>
        )}

        <div>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={grant}
            disabled={saving || !subjectId || Object.values(limits).some((v) => v.length === 0)}
          >
            <Plus size={14} aria-hidden="true" /> Add
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="Open this dataset up?"
        body={`Everyone who may run a report built on “${dataset.title}” will get all of its data their report allows — the limits here stop applying. They're kept, for if you restrict it again.`}
        confirmLabel="Open it up"
        onConfirm={() => {
          setConfirmOpen(false);
          setMode("open");
        }}
        onCancel={() => setConfirmOpen(false)}
      />
      <ConfirmDialog
        open={revoke !== null}
        title="Revoke access"
        body={revoke ? `${revoke.subject_name} loses access to “${dataset.title}” right away, in every report built on it.` : ""}
        confirmLabel="Revoke"
        onConfirm={confirmRevoke}
        onCancel={() => setRevoke(null)}
      />
    </div>
  );
}
