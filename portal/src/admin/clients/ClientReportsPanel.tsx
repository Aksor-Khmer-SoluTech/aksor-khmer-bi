import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api";
import ReportPicker from "../../components/ReportPicker";
import type { ApiClient, ReportMeta } from "../../types";

/** The reports a client may run, as a checklist of the reports in the client's own organization. */
export default function ClientReportsPanel({
  client,
  reports,
  onSaved,
}: {
  client: ApiClient;
  reports: ReportMeta[];
  onSaved: (client: ApiClient) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set(client.reports.map((r) => r.report_id)));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setSelected(new Set(client.reports.map((r) => r.report_id)));
  }, [client.id, client.reports]);

  const available = useMemo(
    () => reports.filter((r) => (r.org_id ?? "root") === client.org_id).sort((a, b) => a.name.localeCompare(b.name)),
    [reports, client.org_id]
  );

  function toggle(reportId: string) {
    setSaved(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(reportId)) next.delete(reportId);
      else next.add(reportId);
      return next;
    });
  }

  async function save() {
    setPending(true);
    setError(null);
    try {
      onSaved(await api.clients.setReports(client.id, Array.from(selected)));
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the reports");
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <p className="muted" style={{ fontSize: "0.85rem", marginBottom: 10 }}>
        This client can run only the reports ticked here — nothing else, and only by sending their parameters.
      </p>
      <ReportPicker reports={available} selected={selected} onToggle={toggle} onSelectMany={(ids) => { setSaved(false); setSelected(new Set(ids)); }} />
      {error && <p className="alert alert-error">{error}</p>}
      {saved && <p className="alert alert-success">Saved.</p>}
      <button type="button" className="btn btn-primary btn-sm" onClick={save} disabled={pending || available.length === 0}>
        {pending && <span className="spinner" />}
        Save reports
      </button>
    </div>
  );
}
