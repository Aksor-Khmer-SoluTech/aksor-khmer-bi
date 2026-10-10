import { useEffect, useMemo, useState } from "react";
import { Download, ExternalLink, Trash2 } from "lucide-react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import DbEngineIcon from "../../components/DbEngineIcon";
import { TableSkeleton } from "../../components/Skeletons";
import { downloadBlob } from "../../download";
import type { AuthInfo, JdbcDriver, JdbcEngine, Organization } from "../../types";
import { has } from "../sections";
import DriverUploadDialog from "./DriverUploadDialog";

const formatSize = (bytes: number) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

/** Admin > JDBC Drivers: the vendor driver files (.jar) database connections run on, for engines
 * the server has no built-in driver for (api/app/jdbc_drivers.py). Anyone who can manage
 * connections sees the list (to pick one); `driver:manage` -- a deploy-level permission, since a
 * driver is code the driver service runs -- uploads, downloads and deletes. */
export default function DriversPage({ auth }: { auth: AuthInfo }) {
  const canManage = has(auth, "driver:manage");
  const [engines, setEngines] = useState<JdbcEngine[] | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [orgFilter, setOrgFilter] = useState("");
  const [query, setQuery] = useState("");
  const [drivers, setDrivers] = useState<JdbcDriver[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [uploadKey, setUploadKey] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<JdbcDriver | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.jdbc.engines().then(setEngines).catch(() => setError("Couldn't load the database engines"));
    api.organizations.list().then(setOrganizations).catch(() => {});
  }, []);

  function load() {
    api.jdbc.drivers
      .list(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then((list) => {
        setError(null);
        setDrivers(list);
      })
      .catch(() => setError("Couldn't load the drivers — is the API reachable?"));
  }
  useEffect(load, [orgFilter]);

  const labels = useMemo(() => Object.fromEntries((engines ?? []).map((e) => [e.id, e.label])), [engines]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !drivers) return drivers;
    return drivers.filter((d) =>
      [d.name, d.filename, d.driver_class, labels[d.engine] ?? d.engine].some((v) => v.toLowerCase().includes(q)),
    );
  }, [drivers, query, labels]);

  async function download(d: JdbcDriver) {
    setActionError(null);
    setBusy(d.id);
    try {
      const { blob, filename } = await api.jdbc.drivers.download(d.id);
      downloadBlob(blob, filename);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Couldn't download the driver");
    } finally {
      setBusy(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setActionError(null);
    try {
      await api.jdbc.drivers.delete(deleteTarget.id);
      setDrivers((prev) => prev?.filter((d) => d.id !== deleteTarget.id) ?? null);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Couldn't delete the driver");
    }
    setDeleteTarget(null);
  }

  const orgList = organizations.length > 0 ? organizations : [{ id: auth.orgId ?? "root", name: auth.orgId ?? "root", parent_org_id: null, is_active: true, created_at: "" }];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">JDBC Drivers</h1>
          <p className="page-subtitle">
            PostgreSQL, MySQL and MariaDB connections work out of the box. For any other database — Oracle, SQL Server, Db2 — upload the
            vendor's JDBC driver here, then choose it on a database connection. Drivers run in an isolated service, never inside the API.
          </p>
        </div>
        {canManage && (
          <button type="button" className="btn btn-primary" disabled={!engines} onClick={() => setUploadKey(Date.now())}>
            + Upload driver
          </button>
        )}
      </div>

      {/* Kept while an organization filter is on, even with nothing in that organization -- it's the way back. */}
      {drivers !== null && (drivers.length > 0 || orgFilter !== "") && (
        <div className="gallery-toolbar">
          <div className="search">
            <input type="text" placeholder="Search drivers…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          {auth.isSuperuser && organizations.length > 1 && (
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
      )}

      {error && <p className="alert alert-error">{error}</p>}
      {actionError && <p className="alert alert-error">{actionError}</p>}
      {drivers === null && !error && <TableSkeleton columns={["Driver", "Class", "SHA-256", "Size", "Used by", ""]} />}

      {drivers !== null && drivers.length === 0 && (
        <div className="empty-state conn-empty">
          <DbEngineIcon engine="oracle" size={40} />
          <p>No drivers uploaded yet.</p>
          <p className="muted">Get the vendor's driver, then upload it here:</p>
          <ul className="jdbc-vendor-list">
            {(engines ?? [])
              .filter((e) => !e.built_in)
              .map((e) => (
                <li key={e.id}>
                  <DbEngineIcon engine={e.id} size={22} />
                  <a href={e.driver_url} target="_blank" rel="noopener noreferrer">
                    {e.label} <ExternalLink size={12} aria-hidden="true" />
                  </a>
                </li>
              ))}
          </ul>
        </div>
      )}

      {shown !== null && drivers !== null && drivers.length > 0 && shown.length === 0 && (
        <div className="empty-state">
          <p>No drivers match that search.</p>
        </div>
      )}

      {shown !== null && shown.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Driver</th>
              <th>Class</th>
              <th>SHA-256</th>
              <th>Size</th>
              <th>Used by</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((d) => (
              <tr key={d.id}>
                <td>
                  <span className="jdbc-driver-name">
                    <DbEngineIcon engine={d.engine} size={26} />
                    <span>
                      {d.name}
                      <span className="muted jdbc-driver-sub">
                        {labels[d.engine] ?? d.engine} · {d.filename}
                      </span>
                    </span>
                  </span>
                </td>
                <td className="mono">{d.driver_class}</td>
                <td className="mono" title={d.sha256}>
                  {d.sha256.slice(0, 12)}…
                </td>
                <td className="muted">{formatSize(d.size_bytes)}</td>
                <td>{d.used_by.length === 0 ? <span className="muted">none</span> : <span className="mono">{d.used_by.join(", ")}</span>}</td>
                <td>
                  {canManage && (
                    <div className="row-actions">
                      <button type="button" className="btn btn-sm" onClick={() => download(d)} disabled={busy === d.id}>
                        {busy === d.id ? <span className="spinner" /> : <Download size={13} aria-hidden="true" />}
                        Download
                      </button>
                      <button
                        type="button"
                        className="btn-danger btn btn-sm"
                        onClick={() => setDeleteTarget(d)}
                        disabled={d.used_by.length > 0}
                        title={d.used_by.length > 0 ? "A connection still uses it — point that connection elsewhere first" : undefined}
                      >
                        <Trash2 size={13} aria-hidden="true" />
                        Delete
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {uploadKey !== null && engines && (
        <DriverUploadDialog
          key={uploadKey}
          open
          onClose={() => setUploadKey(null)}
          engines={engines}
          organizations={orgList}
          defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || "root"}
          onUploaded={load}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete driver"
        body={deleteTarget ? `Delete “${deleteTarget.name}”? No connection uses it. The file is removed from the server.` : ""}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
