import { useEffect, useMemo, useState } from "react";
import { Check, Minus, RotateCcw, ShieldCheck } from "lucide-react";
import { api, ApiError } from "../../api";
import { LinesSkeleton } from "../../components/Skeletons";
import type { Permission, Role } from "../../types";
import { PERMISSION_AREAS } from "../users/UserOverview";

/** The catalog in the same areas, order and names the user window's permission map uses. */
function groupByArea(permissions: Permission[]): { key: string; label: string; perms: Permission[] }[] {
  const byArea = new Map<string, Permission[]>();
  for (const p of permissions) {
    const area = p.code.split(":")[0];
    byArea.set(area, [...(byArea.get(area) ?? []), p]);
  }
  const known = PERMISSION_AREAS.filter(([key]) => byArea.has(key));
  const extra = [...byArea.keys()].filter((k) => !PERMISSION_AREAS.some(([a]) => a === k)).map((k): [string, string] => [k, k]);
  return [...known, ...extra].map(([key, label]) => ({ key, label, perms: byArea.get(key)! }));
}

/** A role's permission set, edited in place: area cards with an all/none switch each, changed rows marked, and a
 * save bar that counts what changed. `onDirtyChange` lets the window holding it ask before closing on unsaved work. */
export default function PermissionMatrix({
  role,
  onSaved,
  onDirtyChange,
}: {
  role: Role;
  onSaved: (r: Role) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [catalog, setCatalog] = useState<Permission[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set(role.permissions));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.permissions.list().then(setCatalog).catch(() => setError("Couldn't load the permission catalog"));
  }, []);

  useEffect(() => {
    setSelected(new Set(role.permissions));
  }, [role.id, role.permissions]);

  const groups = useMemo(() => groupByArea(catalog ?? []), [catalog]);
  const original = useMemo(() => new Set(role.permissions), [role.permissions]);
  const added = [...selected].filter((c) => !original.has(c));
  const removed = [...original].filter((c) => !selected.has(c));
  const dirty = added.length + removed.length > 0;
  const readOnly = role.org_id === null;

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  function change(update: (next: Set<string>) => void) {
    setSaved(false);
    setSelected((prev) => {
      const next = new Set(prev);
      update(next);
      return next;
    });
  }

  async function save() {
    setPending(true);
    setError(null);
    try {
      const updated = await api.roles.setPermissions(role.id, Array.from(selected));
      onSaved(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save permissions");
    } finally {
      setPending(false);
    }
  }

  if (readOnly) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-accent-border bg-accent-soft/50 px-4 py-3.5">
        <ShieldCheck size={18} className="mt-0.5 shrink-0 text-accent-strong" />
        <p className="m-0 text-[0.86rem] text-text">
          <span className="font-mono">{role.name}</span> is the system-wide administrator role: it always holds every
          permission, in every organization — including ones added in later versions — so there is nothing to edit here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {!catalog && !error && <LinesSkeleton count={6} />}
      {catalog && (
        <>
          <div className="flex items-baseline gap-3">
            <span className="field-label m-0">Permissions</span>
            <span className="font-mono text-[0.74rem] text-text-faint tabular-nums">
              {selected.size} of {catalog.length}
            </span>
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-2.5">
            {groups.map((group) => {
              const on = group.perms.filter((p) => selected.has(p.code)).length;
              const all = on === group.perms.length;
              return (
                <section
                  key={group.key}
                  className={`rounded-[10px] border px-3 py-2.5 transition-colors ${on > 0 ? "border-accent-border bg-accent-soft/25" : "border-border-soft bg-bg-raised/60"}`}
                >
                  <header className="mb-1.5 flex items-center gap-2">
                    <span className="text-[0.82rem] font-semibold text-text">{group.label}</span>
                    <span className="font-mono text-[0.66rem] text-text-faint tabular-nums">
                      {on}/{group.perms.length}
                    </span>
                    {group.perms.length > 1 && (
                      <button
                        type="button"
                        className="link-btn ml-auto text-[0.7rem]"
                        onClick={() =>
                          change((next) => group.perms.forEach((p) => (all ? next.delete(p.code) : next.add(p.code))))
                        }
                      >
                        {all ? "none" : "all"}
                      </button>
                    )}
                  </header>
                  <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                    {group.perms.map((p) => {
                      const checked = selected.has(p.code);
                      const wasAdded = checked && !original.has(p.code);
                      const wasRemoved = !checked && original.has(p.code);
                      return (
                        <li key={p.code}>
                          <label className="-mx-1.5 !mb-0 flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 hover:bg-bg-panel/60">
                            <input
                              type="checkbox"
                              className="mt-[3px] !w-auto"
                              checked={checked}
                              onChange={() => change((next) => (checked ? next.delete(p.code) : next.add(p.code)))}
                            />
                            <span className="!mb-0 min-w-0 flex-1 !font-normal">
                              <span className="flex items-center gap-1.5">
                                <span className={`font-mono text-[0.78rem] ${wasRemoved ? "text-text-faint line-through" : "text-text"}`}>
                                  {p.code.split(":").slice(1).join(":")}
                                </span>
                                {wasAdded && <span className="rounded bg-accent px-1 text-[0.6rem] font-semibold text-accent-ink">added</span>}
                                {wasRemoved && <span className="rounded bg-danger-soft px-1 text-[0.6rem] font-semibold text-danger-strong">removed</span>}
                              </span>
                              <span className="block text-[0.72rem] leading-snug text-text-dim">{p.description}</span>
                            </span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
        </>
      )}

      {catalog && (
        <div
          className={`sticky bottom-0 -mx-6 -mb-7 flex flex-wrap items-center gap-3 border-t px-6 py-3 backdrop-blur transition-colors ${
            dirty ? "border-accent-border bg-[color-mix(in_srgb,var(--accent-soft)_70%,var(--bg))]" : "border-border-soft bg-bg/90"
          }`}
        >
          {dirty ? (
            <span className="flex flex-wrap items-center gap-2 text-[0.8rem] text-text">
              Unsaved:
              {added.length > 0 && (
                <span className="inline-flex items-center gap-0.5 font-medium text-accent-strong">
                  <Check size={12} strokeWidth={3} /> {added.length} added
                </span>
              )}
              {removed.length > 0 && (
                <span className="inline-flex items-center gap-0.5 font-medium text-danger-strong">
                  <Minus size={12} strokeWidth={3} /> {removed.length} removed
                </span>
              )}
              <span className="text-text-faint">— everyone holding this role gets the change on their next request.</span>
            </span>
          ) : saved ? (
            <span className="text-[0.8rem] text-success-strong">Saved.</span>
          ) : (
            <span className="text-[0.8rem] text-text-faint">Tick what this role may do; nothing changes until you save.</span>
          )}
          <span className="ml-auto flex gap-2">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                setSelected(new Set(role.permissions));
                setSaved(false);
              }}
              disabled={!dirty || pending}
            >
              <RotateCcw size={13} /> Reset
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => void save()} disabled={!dirty || pending}>
              {pending && <span className="spinner" />}
              Save permissions
            </button>
          </span>
        </div>
      )}
      {error && <p className="alert alert-error m-0">{error}</p>}
    </div>
  );
}
