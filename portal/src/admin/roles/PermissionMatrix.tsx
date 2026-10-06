import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api";
import { LinesSkeleton } from "../../components/Skeletons";
import type { Permission, Role } from "../../types";

function groupByResource(permissions: Permission[]): Map<string, Permission[]> {
  const groups = new Map<string, Permission[]>();
  for (const p of permissions) {
    const [resource] = p.code.split(":");
    const list = groups.get(resource) ?? [];
    list.push(p);
    groups.set(resource, list);
  }
  return groups;
}

export default function PermissionMatrix({ role, onSaved }: { role: Role; onSaved: (r: Role) => void }) {
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

  const groups = useMemo(() => groupByResource(catalog ?? []), [catalog]);
  const readOnly = role.org_id === null;

  function toggle(code: string) {
    setSaved(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
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
      <p className="muted">
        <code className="mono">{role.name}</code> is the system-wide administrator role — it always holds every
        permission and isn't editable.
      </p>
    );
  }

  return (
    <div>
      {!catalog && !error && <LinesSkeleton count={6} />}
      {error && <p className="alert alert-error">{error}</p>}
      {catalog && (
        <div className="permission-matrix">
          {Array.from(groups.entries()).map(([resource, perms]) => (
            <div key={resource} className="permission-group">
              <div className="permission-group-title">{resource}</div>
              {perms.map((p) => (
                <label key={p.code} className="permission-row">
                  <input type="checkbox" checked={selected.has(p.code)} onChange={() => toggle(p.code)} />
                  <span>
                    <span className="mono">{p.code}</span>
                    <span className="muted permission-desc">{p.description}</span>
                  </span>
                </label>
              ))}
            </div>
          ))}
        </div>
      )}
      {saved && <p className="alert alert-success">Saved.</p>}
      <button type="button" className="btn btn-primary btn-sm" onClick={save} disabled={pending || !catalog}>
        {pending && <span className="spinner" />}
        Save permissions
      </button>
    </div>
  );
}
