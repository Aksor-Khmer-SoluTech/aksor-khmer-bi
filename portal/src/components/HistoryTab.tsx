import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Download, FileClock, Flag, History as HistoryIcon } from "lucide-react";
import { api, ApiError } from "../api";
import { labelInChangelog, versionName, type AuditEvent, type ChangelogEntry, type ReportChangelog, type ReportMeta, type ReportVersion } from "../types";
import {
  ActionGlyph,
  ActorLine,
  AuditChanges,
  ShortHash,
  fmtBytes,
  fmtDelta,
  fmtStamp,
  isReadEvent,
  stampTitle,
} from "./AuditParts";
import { LinesSkeleton } from "./Skeletons";
import { useTemplateDownload } from "./TemplateDownload";

type Filter = "all" | "files" | "settings" | "access" | "downloads";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "Everything" },
  { id: "files", label: "File versions" },
  { id: "settings", label: "Settings" },
  { id: "access", label: "Access Privilege" },
  { id: "downloads", label: "Downloads" },
];

function matches(entry: ChangelogEntry, filter: Filter): boolean {
  if (filter === "all") return true;
  if (entry.kind === "version") return filter === "files";
  const action = entry.event.action;
  if (filter === "downloads") return isReadEvent(action);
  if (filter === "access") return action.startsWith("report.access_");
  if (filter === "settings") return !isReadEvent(action) && !action.startsWith("report.access_");
  return false;
}

// One node on the spine. Versions are the backbone of the log, so they get a
// larger, solid marker; everything else hangs off it as a small outlined one.
function Node({ children, current = false, dashed = false }: { children: ReactNode; current?: boolean; dashed?: boolean }) {
  return (
    <span
      className={`absolute left-0 top-3 grid h-7 w-7 place-items-center rounded-full border ${
        current
          ? "border-accent bg-accent text-accent-ink shadow-accent"
          : dashed
            ? "border-dashed border-border-strong bg-bg text-text-faint"
            : "border-accent-border bg-accent-soft text-accent-strong"
      }`}
    >
      {children}
    </span>
  );
}

function Chip({ tone, children }: { tone: "add" | "remove" | "neutral"; children: ReactNode }) {
  const cls =
    tone === "add"
      ? "bg-success-soft text-success-strong"
      : tone === "remove"
        ? "bg-danger-soft text-danger-strong line-through decoration-danger/50"
        : "bg-bg-panel text-text-dim";
  return <span className={`inline-flex items-center rounded-sm px-1.5 py-px font-mono text-[0.76rem] leading-5 ${cls}`}>{children}</span>;
}

/** What this version did to the template's placeholders. A .docx/.xlsx can't
 * be shown as a text diff, but "added {{ branch }}, dropped {{ region }}" is
 * the change a person actually cares about -- and it's computed for real
 * (see report_store._version_to_dict), not written by hand. */
export function PlaceholderDiff({ v }: { v: ReportVersion }) {
  if (v.fields === null) {
    return <p className="m-0 text-[0.78rem] text-text-faint">Placeholders couldn't be read from this file.</p>;
  }
  if (v.fields_added === null || v.fields_removed === null) {
    // The oldest retained version has nothing before it to be compared with.
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[0.76rem] text-text-faint">
          {v.fields.length} placeholder{v.fields.length === 1 ? "" : "s"}
        </span>
        {v.fields.slice(0, 10).map((f) => (
          <Chip key={f} tone="neutral">
            {f}
          </Chip>
        ))}
        {v.fields.length > 10 && <span className="text-[0.74rem] text-text-faint">+{v.fields.length - 10} more</span>}
      </div>
    );
  }
  if (v.fields_added.length === 0 && v.fields_removed.length === 0) {
    return <p className="m-0 text-[0.78rem] text-text-faint">Placeholders unchanged.</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[0.76rem] text-text-faint">Placeholders</span>
      {v.fields_removed.map((f) => (
        <Chip key={`-${f}`} tone="remove">
          − {f}
        </Chip>
      ))}
      {v.fields_added.map((f) => (
        <Chip key={`+${f}`} tone="add">
          + {f}
        </Chip>
      ))}
    </div>
  );
}

function VersionCard({
  entry,
  isCurrent,
  busy,
  onDownload,
  reportId,
  onEdited,
}: {
  entry: Extract<ChangelogEntry, { kind: "version" }>;
  isCurrent: boolean;
  busy: number | null;
  onDownload: (version: number) => void;
  reportId: string;
  onEdited: () => void;
}) {
  const v = entry.version;
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function startEdit() {
    setLabel(v.version_label ?? "");
    setNote(v.note ?? "");
    setErr(null);
    setEditing(true);
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      await api.updateVersion(reportId, v.version, { version_label: label, note });
      setEditing(false);
      onEdited();
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }
  const upload = entry.upload_event;
  const isOriginal = v.version === 1;
  return (
    <div className="rounded-md border border-border-soft bg-bg-raised p-4 shadow-card">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="font-mono text-[1.05rem] font-semibold tracking-tight text-text">{versionName(v.version, v.version_label)}</span>
          {isCurrent && (
            <span className="rounded-sm bg-accent px-1.5 py-px text-[0.66rem] font-semibold uppercase tracking-wider text-accent-ink">
              Current
            </span>
          )}
          {isOriginal && (
            <span className="rounded-sm border border-highlight/40 bg-highlight-soft px-1.5 py-px text-[0.66rem] font-semibold uppercase tracking-wider text-highlight">
              Original upload
            </span>
          )}
          {v.original_filename && <span className="min-w-0 break-all font-mono text-[0.78rem] text-text-dim">{v.original_filename}</span>}
        </div>
        <time className="text-[0.78rem] text-text-faint" dateTime={v.created_at} title={stampTitle(v.created_at)}>
          {fmtStamp(v.created_at)}
        </time>
      </div>

      <p className="mb-0 mt-1 text-[0.8rem] text-text-faint">
        {v.backfilled ? (
          <>Recovered from the live file — who uploaded it wasn't recorded back then.</>
        ) : (
          <>
            {isOriginal ? "Registered" : "Uploaded"} by <span className="font-medium text-text-dim">{v.created_by ?? "unknown"}</span>
            {upload?.ip_address && (
              <>
                {" · "}
                <span className="font-mono">{upload.ip_address}</span>
              </>
            )}
          </>
        )}
      </p>

      {editing ? (
        <form onSubmit={save} className="mt-3 grid gap-2">
          <label className="text-[0.8rem] text-text-dim">
            Version
            <input type="text" className="font-mono" maxLength={33} value={label} placeholder={`v${v.version} (blank = numbered)`} disabled={saving} onChange={(e) => setLabel(e.target.value)} />
          </label>
          <label className="text-[0.8rem] text-text-dim">
            What changed?
            <input type="text" maxLength={300} value={note} disabled={saving} onChange={(e) => setNote(e.target.value)} />
          </label>
          {err && <p className="alert alert-error m-0" role="alert">{err}</p>}
          <div className="flex gap-2">
            <button type="submit" className="btn btn-sm btn-primary" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
            <button type="button" className="btn btn-sm btn-ghost" disabled={saving} onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </form>
      ) : (
        <>
          {v.note && (
        <blockquote className="mx-0 mb-0 mt-3 border-l-2 border-accent-border pl-3 text-[0.86rem] text-text">{v.note}</blockquote>
          )}
          <button type="button" className="link-btn mt-2 text-[0.78rem]" onClick={startEdit}>
            Edit version &amp; note
          </button>
        </>
      )}

      <div className="mt-3 grid gap-2">
        <PlaceholderDiff v={v} />
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.78rem] text-text-faint">
          <span>
            {fmtBytes(v.size_bytes)}
            {v.size_delta !== null && v.size_delta !== 0 && (
              <span className={v.size_delta > 0 ? "text-success-strong" : "text-danger-strong"}> ({fmtDelta(v.size_delta)})</span>
            )}
          </span>
          {v.identical_to_previous && (
            <span className="rounded-sm bg-bg-panel px-1.5 py-px text-[0.72rem] text-text-dim">Same file as the previous version</span>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border-soft pt-3">
        <ShortHash hash={v.sha256} />
        <button
          type="button"
          className="btn btn-sm"
          disabled={busy !== null || !v.available}
          title={v.available ? undefined : "This file is no longer on the server"}
          onClick={() => onDownload(v.version)}
        >
          <Download size={13} aria-hidden />
          {busy === v.version ? "Downloading…" : isOriginal ? "Download original" : `Download ${versionName(v.version, v.version_label)}`}
        </button>
      </div>
    </div>
  );
}

function EventRow({ event }: { event: AuditEvent }) {
  const read = isReadEvent(event.action);
  const sha = typeof event.details?.sha256 === "string" ? event.details.sha256 : null;
  return (
    <div className={read ? "py-2" : "rounded-md border border-border-soft bg-bg-raised px-4 py-3"}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <span className={`text-[0.88rem] ${read ? "text-text-dim" : "font-medium text-text"}`}>{event.summary}</span>
        <time className="text-[0.78rem] text-text-faint" dateTime={event.created_at} title={stampTitle(event.created_at)}>
          {fmtStamp(event.created_at)}
        </time>
      </div>
      <span className="flex flex-wrap items-center gap-x-3">
        <ActorLine event={event} />
        {/* A download is one quiet line: the checksum is what lets someone later
            match a file they found against the version that left. */}
        {read && sha && <ShortHash hash={sha} copyable={false} />}
      </span>
      <AuditChanges changes={event.changes} />
    </div>
  );
}

/** The template's change log -- a `git log` for a file that isn't text. Every
 * uploaded version is a card (who, when, their note, what it did to the
 * placeholders, a checksum, a download); every other recorded change to the
 * report hangs off the same spine. */
export default function HistoryTab({
  report,
  changelog,
  error,
  onReload,
  onChanged,
}: {
  report: ReportMeta;
  changelog: ReportChangelog | null;
  error: string | null;
  onReload: () => void;
  /** A version's label/note was edited: refresh the change log and the report header. */
  onChanged: () => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const { busy, error: downloadError, download } = useTemplateDownload(report.report_id);

  // Always show what's true now: tabs remount on switch (TemplateDetail keys
  // the pane), so this refetches each time the tab is opened.
  useEffect(() => {
    onReload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const entries = useMemo(() => (changelog?.entries ?? []).filter((e) => matches(e, filter)), [changelog, filter]);
  const versionCount = changelog?.entries.filter((e) => e.kind === "version").length ?? 0;
  const firstRetained = changelog?.first_retained_version ?? null;
  const gap = firstRetained !== null && firstRetained > 1;

  return (
    <div className="panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="panel-title">Change log</h2>
          <p className="panel-subtitle">
            Every version of this template's file and every recorded change to the report, newest first.
          </p>
        </div>
        {changelog && (
          <dl className="m-0 flex flex-wrap gap-x-5 gap-y-1 text-[0.78rem]">
            <div>
              <dt className="text-text-faint">Current</dt>
              <dd className="m-0 font-mono text-[0.95rem] font-semibold text-text">{versionName(changelog.current_version, labelInChangelog(changelog, changelog.current_version))}</dd>
            </div>
            <div>
              <dt className="text-text-faint">Files kept</dt>
              <dd className="m-0 font-mono text-[0.95rem] font-semibold text-text">{versionCount}</dd>
            </div>
            <div>
              <dt className="text-text-faint">Original</dt>
              <dd className={`m-0 text-[0.95rem] font-semibold ${changelog.original_available ? "text-success-strong" : "text-text-faint"}`}>
                {changelog.original_available ? "Kept" : "Not kept"}
              </dd>
            </div>
          </dl>
        )}
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {downloadError && <p className="alert alert-error">{downloadError}</p>}

      {!changelog && !error && <LinesSkeleton count={5} />}

      {changelog && (
        <>
          <div className="mb-4 mt-1 flex flex-wrap gap-1.5" role="group" aria-label="Filter the change log">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                aria-pressed={filter === f.id}
                onClick={() => setFilter(f.id)}
                className={`rounded-full border px-3 py-1 text-[0.78rem] font-medium transition-colors ${
                  filter === f.id
                    ? "border-accent-border bg-accent-soft text-accent-strong"
                    : "border-border-soft bg-bg-raised text-text-dim hover:border-border-strong hover:text-text"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          {entries.length === 0 ? (
            <div className="empty-state">
              <p>Nothing recorded under this filter.</p>
            </div>
          ) : (
            <ol className="relative m-0 list-none p-0 before:absolute before:bottom-6 before:left-[13px] before:top-6 before:w-px before:bg-border">
              {entries.map((entry, i) => {
                const isVersion = entry.kind === "version";
                const isCurrent = isVersion && entry.version.version === changelog.current_version;
                return (
                  <li key={isVersion ? `v${entry.version.version}` : entry.event.id} className="hist-enter relative pb-3 pl-11" style={{ ["--i" as string]: Math.min(i, 12) }}>
                    <Node current={isCurrent}>
                      {isVersion ? (
                        <FileClock size={14} strokeWidth={1.8} aria-hidden />
                      ) : (
                        <ActionGlyph action={entry.event.action} size={20} />
                      )}
                    </Node>
                    {isVersion ? (
                      <VersionCard
                        entry={entry}
                        isCurrent={isCurrent}
                        busy={busy}
                        onDownload={(v) => download(v)}
                        reportId={report.report_id}
                        onEdited={onChanged}
                      />
                    ) : (
                      <EventRow event={entry.event} />
                    )}
                  </li>
                );
              })}

              {gap && (filter === "all" || filter === "files") && (
                <li className="hist-enter relative pb-1 pl-11" style={{ ["--i" as string]: 13 }}>
                  <Node dashed>
                    <HistoryIcon size={13} strokeWidth={1.8} aria-hidden />
                  </Node>
                  <div className="rounded-md border border-dashed border-border-strong px-4 py-3 text-[0.82rem] text-text-dim">
                    <span className="font-medium text-text">
                      {firstRetained! > 2 ? `v1 – v${firstRetained! - 1}` : "v1"} weren't kept.
                    </span>{" "}
                    This template was replaced before version history existed, so those files were overwritten and can't be recovered.
                    Versions from v{firstRetained} on are all here.
                  </div>
                </li>
              )}
              {!gap && (filter === "all" || filter === "files") && versionCount > 0 && (
                <li className="hist-enter relative pl-11" style={{ ["--i" as string]: 13 }}>
                  <Node dashed>
                    <Flag size={13} strokeWidth={1.8} aria-hidden />
                  </Node>
                  <p className="m-0 pt-3 text-[0.78rem] text-text-faint">Beginning of the record — every version since the first upload is kept.</p>
                </li>
              )}
            </ol>
          )}
        </>
      )}
    </div>
  );
}
