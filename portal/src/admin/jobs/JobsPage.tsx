import { Fragment, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api";
import { TableSkeleton } from "../../components/Skeletons";
import type { AuthInfo, Job, Organization } from "../../types";
import JobDetailPanel from "./JobDetailPanel";
import JobFormDialog from "./JobFormDialog";

function triggerSummary(job: Job): string {
  if (job.trigger_type === "cron") return job.cron_expression ?? "—";
  if (job.trigger_type === "interval") return `every ${job.interval_seconds}s`;
  return job.run_at ? new Date(job.run_at).toLocaleString() : "—";
}

export default function JobsPage({ auth }: { auth: AuthInfo }) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [orgFilter, setOrgFilter] = useState<string>("");
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    api.organizations.list().then(setOrganizations).catch(() => {});
  }, []);

  function load() {
    api.jobs
      .list(auth.isSuperuser ? orgFilter || undefined : undefined)
      .then(setJobs)
      .catch(() => setError("Couldn't load jobs — is the API reachable?"));
  }

  useEffect(load, [orgFilter]);

  const filtered = useMemo(() => {
    if (!jobs) return [];
    const q = query.trim().toLowerCase();
    if (!q) return jobs;
    return jobs.filter((j) => j.name.toLowerCase().includes(q) || (j.description ?? "").toLowerCase().includes(q));
  }, [jobs, query]);

  const orgName = (id: string) => organizations.find((o) => o.id === id)?.name ?? id;

  async function runNow(job: Job) {
    setRunningId(job.id);
    setRunError(null);
    try {
      await api.jobs.run(job.id);
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : "Couldn't trigger the job");
    } finally {
      setRunningId(null);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Jobs</h1>
          <p className="page-subtitle">
            Schedule report renders, REST/SOAP calls, or file drops — triggered by cron, interval, once, manually, or via the API.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setCreateOpen(true)}>
          + New job
        </button>
      </div>

      <div className="gallery-toolbar">
        <div className="search">
          <input type="text" placeholder="Search by name or description…" value={query} onChange={(e) => setQuery(e.target.value)} />
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
      {runError && <p className="alert alert-error">{runError}</p>}
      {jobs === null && !error && (
        <TableSkeleton columns={["Name", "Type", "Trigger", ...(auth.isSuperuser ? ["Organization"] : []), "Status", ""]} />
      )}

      {jobs !== null && filtered.length === 0 && (
        <div className="empty-state">
          <p>{jobs.length === 0 ? "No jobs yet." : "No jobs match that search."}</p>
        </div>
      )}

      {filtered.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Trigger</th>
              {auth.isSuperuser && <th>Organization</th>}
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((j) => (
              <Fragment key={j.id}>
                <tr
                  className={expandedId === j.id ? "active-row" : ""}
                  onClick={() => setExpandedId(expandedId === j.id ? null : j.id)}
                >
                  <td>
                    <div>{j.name}</div>
                    {j.description && <span className="muted">{j.description}</span>}
                  </td>
                  <td className="mono">{j.job_type}</td>
                  <td className="mono">{triggerSummary(j)}</td>
                  {auth.isSuperuser && <td>{orgName(j.org_id)}</td>}
                  <td>
                    <span className={`badge badge-${j.is_enabled ? "enabled" : "disabled"}`}>
                      {j.is_enabled ? "enabled" : "disabled"}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={runningId === j.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        runNow(j);
                      }}
                    >
                      {runningId === j.id && <span className="spinner" />}
                      Run now
                    </button>
                  </td>
                </tr>
                {expandedId === j.id && (
                  <tr className="detail-row">
                    <td colSpan={auth.isSuperuser ? 6 : 5}>
                      <JobDetailPanel
                        job={j}
                        onUpdated={(updated) => setJobs((prev) => prev?.map((x) => (x.id === updated.id ? updated : x)) ?? null)}
                        onDeleted={(id) => {
                          setJobs((prev) => prev?.filter((x) => x.id !== id) ?? null);
                          setExpandedId(null);
                        }}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}

      <JobFormDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(job) => setJobs((prev) => [...(prev ?? []), job])}
        organizations={organizations.length > 0 ? organizations : [{ id: auth.orgId ?? "root", name: auth.orgId ?? "root", parent_org_id: null, is_active: true, created_at: "" }]}
        defaultOrgId={orgFilter || auth.orgId || organizations[0]?.id || "root"}
        isSuperuser={auth.isSuperuser}
      />
    </div>
  );
}
