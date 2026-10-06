import { useState } from "react";
import { Download } from "lucide-react";
import { api, ApiError } from "../api";
import { downloadBlob } from "../download";
import { labelInChangelog, versionName, type ReportChangelog, type ReportMeta } from "../types";

/** Fetch a template file (the current one, or one version) and hand it to the
 * browser. A plain <a href> can't do this: the API is Basic-auth'd with a
 * header the page attaches itself (api.ts), so the bytes come through fetch
 * and are saved from a Blob -- the same route render downloads take. Every
 * call is recorded server-side (who, which version, the file's checksum). */
export function useTemplateDownload(reportId: string) {
  // Which version is in flight (0 = "current"), so only that button spins.
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function download(version?: number) {
    setError(null);
    setBusy(version ?? 0);
    try {
      const { blob, filename } = await api.downloadTemplate(reportId, version);
      downloadBlob(blob, filename);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Download failed");
    } finally {
      setBusy(null);
    }
  }

  return { busy, error, download };
}

/** "Download current" and "Download original" -- the Overview tab's answer
 * to "can I get the template back out?". The original is only offered when
 * its file was actually kept: a template replaced before version history
 * existed lost it, and the button says so instead of failing on click. */
export default function TemplateDownloadButtons({
  report,
  changelog,
}: {
  report: ReportMeta;
  changelog: ReportChangelog | null;
}) {
  const { busy, error, download } = useTemplateDownload(report.report_id);
  // While the changelog is still loading, don't claim the original is gone.
  const originalKnownMissing = changelog !== null && !changelog.original_available;
  const originalIsCurrent = report.version === 1;

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => download()}>
          <Download size={15} aria-hidden />
          {busy === 0 ? "Downloading…" : `Download current (${versionName(report.version, report.version_label)})`}
        </button>
        {!originalIsCurrent && (
          <button
            type="button"
            className="btn"
            disabled={busy !== null || originalKnownMissing}
            title={
              originalKnownMissing
                ? "Not available — this template was replaced before version history was kept, so the first upload was overwritten."
                : "The file exactly as first uploaded"
            }
            onClick={() => download(1)}
          >
            <Download size={15} aria-hidden />
            {busy === 1 ? "Downloading…" : `Download original (${versionName(1, labelInChangelog(changelog, 1))})`}
          </button>
        )}
      </div>
      {originalKnownMissing && !originalIsCurrent && (
        <p className="field-hint" style={{ margin: "8px 0 0" }}>
          The original upload isn't available: this template was replaced before version history was kept.
          {changelog?.first_retained_version ? ` The oldest file still held is v${changelog.first_retained_version}.` : ""}
        </p>
      )}
      {error && (
        <p className="alert alert-error" style={{ marginTop: 10 }}>
          {error}
        </p>
      )}
    </div>
  );
}
