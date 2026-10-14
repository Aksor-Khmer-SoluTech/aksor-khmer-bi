import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowRight, Download, FileCode2, FileSpreadsheet, FileText, Image as ImageIcon, Package, Palette, Type, Upload } from "lucide-react";
import { api, ApiError } from "../api";
import { downloadBlob } from "../download";
import { useDialogRef } from "../hooks";
import type { Folder, ImportChoice, ImportPlan, ImportSummary, ProjectContents, TemplateExt } from "../types";
import ModalClose from "./ModalClose";

/** Moving a project between environments (api/app/projects.py): Export packs it -- the deployer decides which shared
 * resources travel along -- and Import reads a package, shows what would happen to every item like a packing list
 * checked against the shelves (new, already here, differs, missing), and applies the deployer's choices. */

const CHOICE_LABEL: Record<ImportChoice, string> = {
  create: "Create",
  create_shared: "Add as shared",
  create_in_project: "Add inside the project",
  link: "Use the one already here",
  copy_into_project: "Copy into the project",
  overwrite: "Overwrite the one here",
  keep_both: "Keep both",
  use_existing: "Keep the one here",
  update: "Update — add a version",
  skip: "Skip",
  install: "Add the font",
  replace: "Replace the font here",
};

const STATUS: Record<string, { label: string; cls: string; hint: string }> = {
  new: { label: "New", cls: "bg-accent-soft text-accent-strong", hint: "Not on this server yet" },
  identical: { label: "Already here", cls: "bg-success-soft text-success-strong", hint: "The exact same file is here -- it's linked, not copied" },
  identical_elsewhere: { label: "Same file elsewhere", cls: "bg-success-soft text-success-strong", hint: "The exact same file is here, outside this project" },
  differs: { label: "Differs", cls: "bg-highlight-soft text-highlight-strong", hint: "One with this name is here, with other content" },
  missing: { label: "Missing", cls: "bg-danger-soft text-danger-strong", hint: "Left out of the package and not on this server" },
  exists: { label: "Exists", cls: "bg-highlight-soft text-highlight-strong", hint: "This template is already in the project" },
};

const EXT_ICON: Record<TemplateExt, typeof FileText> = { docx: FileText, xlsx: FileSpreadsheet, html: FileCode2 };

function Stamp({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, cls: "bg-bg-panel text-text-dim", hint: "" };
  return (
    <span title={s.hint} className={`inline-flex shrink-0 items-center rounded-[4px] px-1.5 py-[1px] font-mono text-[0.66rem] font-semibold tracking-[0.06em] uppercase ${s.cls}`}>
      {s.label}
    </span>
  );
}

function Section({ title, count, children, aside }: { title: string; count?: number; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="grid gap-1.5">
      <div className="flex items-baseline gap-2 border-b border-border-soft pb-1">
        <h3 className="m-0 font-mono text-[0.7rem] font-semibold tracking-[0.08em] text-text-faint uppercase">{title}</h3>
        {count !== undefined && <span className="font-mono text-[0.7rem] text-text-faint">{count}</span>}
        <span className="flex-1" />
        {aside}
      </div>
      {children}
    </section>
  );
}

const kb = (n: number) => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

// --- Export ------------------------------------------------------------------------------------------------------------

export function ExportProjectDialog({ folderId, onClose }: { folderId: string; onClose: () => void }) {
  const ref = useDialogRef(true);
  const [info, setInfo] = useState<ProjectContents | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leaveOut, setLeaveOut] = useState<Set<string>>(new Set());
  const [opts, setOpts] = useState({ versions: true, data_sources: true, fonts: true, term_sets: true });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.projects
      .contents(folderId)
      .then(setInfo)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't read the project"));
  }, [folderId]);

  const own = info?.resources.filter((r) => r.scope === "project") ?? [];
  const shared = info?.resources.filter((r) => r.scope === "shared") ?? [];
  const refs = info ? [...info.references.connections.map((n) => ["Connection", n]), ...info.references.secrets.map((n) => ["Secret", n]), ...info.references.datasets.map((n) => ["Dataset", n])] : [];

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await api.projects.export(folderId, { leave_out: [...leaveOut], ...opts });
      downloadBlob(blob, filename);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Export failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog ref={ref} className="modal modal-wide" onCancel={onClose} onClose={onClose}>
      <ModalClose />
      <div className="mb-3 flex items-center gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-strong">
          <Package size={20} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 className="panel-title m-0">Export project{info ? ` — ${info.project.name}` : ""}</h2>
          <p className="muted m-0 text-[0.84rem]">One package to import on another server: its templates, their files, and what you choose below.</p>
        </div>
      </div>
      {error && <p className="alert alert-error">{error}</p>}
      {!info && !error && <p className="muted">Reading the project…</p>}
      {info && (
        <div className="grid gap-4">
          <Section title="In the package" count={info.templates.length + own.length}>
            <ul className="m-0 grid list-none gap-1 p-0">
              {info.templates.map((t) => {
                const Icon = EXT_ICON[t.template_ext] ?? FileText;
                return (
                  <li key={t.id} className="flex items-center gap-2 text-[0.88rem]">
                    <Icon size={15} className="shrink-0 text-text-faint" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate">
                      {t.folder && <span className="text-text-faint">{t.folder}/</span>}
                      {t.name}
                    </span>
                    {t.code && <span className="mono text-[0.75rem] text-text-faint">{t.code}</span>}
                    <span className="mono text-[0.75rem] text-text-faint">v{t.version}</span>
                  </li>
                );
              })}
              {own.map((r) => (
                <li key={r.id} className="flex items-center gap-2 text-[0.88rem] text-text-dim">
                  {r.kind === "image" ? <ImageIcon size={15} className="shrink-0 text-text-faint" aria-hidden="true" /> : <Palette size={15} className="shrink-0 text-text-faint" aria-hidden="true" />}
                  <span className="min-w-0 flex-1 truncate">
                    {r.folder && <span className="text-text-faint">{r.folder}/</span>}
                    {r.name}
                  </span>
                  <span className="mono text-[0.75rem] text-text-faint">{kb(r.size_bytes)}</span>
                </li>
              ))}
              {info.templates.length === 0 && <li className="muted text-[0.86rem]">No templates in this project yet.</li>}
            </ul>
          </Section>

          {shared.length > 0 && (
            <Section
              title="Shared files it uses"
              count={shared.length}
              aside={
                <button type="button" className="link-btn text-[0.78rem]" onClick={() => setLeaveOut(leaveOut.size ? new Set() : new Set(shared.map((r) => `${r.kind}:${r.id}`)))}>
                  {leaveOut.size ? "Include all" : "Leave all out"}
                </button>
              }
            >
              <p className="field-hint m-0">
                These live outside the project. Untick one the other server already has: the package records it by name and fingerprint, and the import finds it there
                — or says it's missing.
              </p>
              {shared.map((r) => {
                const key = `${r.kind}:${r.id}`;
                const included = !leaveOut.has(key);
                return (
                  <label key={key} className="checkbox-label mb-0 flex items-start gap-2 rounded-md px-1.5 py-1 hover:bg-bg-panel">
                    <input
                      type="checkbox"
                      checked={included}
                      onChange={() =>
                        setLeaveOut((prev) => {
                          const next = new Set(prev);
                          if (next.has(key)) next.delete(key);
                          else next.add(key);
                          return next;
                        })
                      }
                    />
                    <span className="min-w-0 flex-1 leading-tight">
                      <span className="flex items-center gap-1.5">
                        {r.kind === "image" ? <ImageIcon size={14} aria-hidden="true" /> : <Palette size={14} aria-hidden="true" />}
                        <b className="font-medium">{r.name}</b>
                        <span className="text-[0.78rem] text-text-faint">in {r.where}</span>
                      </span>
                      <small className="block text-[0.74rem] text-text-faint">used by {r.used_by.join(", ") || "—"}</small>
                    </span>
                    <span className={`text-[0.74rem] ${included ? "text-text-dim" : "text-highlight-strong"}`}>{included ? "included" : "left out"}</span>
                  </label>
                );
              })}
            </Section>
          )}

          <Section title="Also include">
            <div className="grid gap-1 sm:grid-cols-2">
              {(
                [
                  ["versions", "Version history", "Every earlier version of each template, with its note"],
                  ["data_sources", "Data sources and sample data", "Connections and secrets by name only — never their values"],
                  ["fonts", `Fonts (${info.fonts.length})`, info.fonts.map((f) => `${f.family} ${f.subfamily}`).join(", ") || "None of the templates name an added font"],
                  ["term_sets", `Protected terms (${info.term_sets.length})`, info.term_sets.map((t) => t.name).join(", ") || "None used"],
                ] as const
              ).map(([key, label, hint]) => (
                <label key={key} className="checkbox-label mb-0 flex items-start gap-2 rounded-md px-1.5 py-1 hover:bg-bg-panel">
                  <input type="checkbox" checked={opts[key]} onChange={() => setOpts((o) => ({ ...o, [key]: !o[key] }))} />
                  <span className="leading-tight">
                    {label}
                    <small className="block text-[0.74rem] text-text-faint">{hint}</small>
                  </span>
                </label>
              ))}
            </div>
          </Section>

          {opts.data_sources && refs.length > 0 && (
            <Section title="The other server will need">
              <div className="flex flex-wrap gap-1.5">
                {refs.map(([kind, name]) => (
                  <span key={`${kind}-${name}`} className="inline-flex items-center gap-1 rounded-full border border-border-soft px-2 py-0.5 text-[0.78rem]">
                    <span className="text-text-faint">{kind}</span> <b className="mono font-medium">{name}</b>
                  </span>
                ))}
              </div>
              <p className="field-hint m-0">Named in the templates' data sources. Secrets never leave this server — create them there under Manage → Secrets.</p>
            </Section>
          )}

          {info.warnings.length > 0 && (
            <ul className="alert alert-warning m-0 grid list-none gap-0.5 pl-3">
              {info.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="btn btn-primary" onClick={() => void download()} disabled={!info || busy}>
          {busy ? <span className="spinner" /> : <Download size={14} aria-hidden="true" />} Download package
        </button>
      </div>
    </dialog>
  );
}

function Row({
  icon,
  name,
  detail,
  status,
  choices,
  value,
  onPick,
}: {
  icon: ReactNode;
  name: string;
  detail?: string;
  status: string;
  choices: ImportChoice[];
  value: ImportChoice | undefined;
  onPick: (choice: ImportChoice) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md px-1.5 py-1.5 hover:bg-bg-panel">
      <span className="shrink-0 text-text-faint">{icon}</span>
      <span className="min-w-0 flex-1 leading-tight">
        <span className="block truncate text-[0.88rem]">{name}</span>
        {detail && <small className="block text-[0.74rem] text-text-faint">{detail}</small>}
      </span>
      <Stamp status={status} />
      {choices.length > 1 ? (
        <select className="w-auto min-w-[11rem] py-1 text-[0.8rem]" aria-label={`What to do with ${name}`} value={value} onChange={(e) => onPick(e.target.value as ImportChoice)}>
          {choices.map((c) => (
            <option key={c} value={c}>
              {CHOICE_LABEL[c]}
            </option>
          ))}
        </select>
      ) : (
        <span className="min-w-[11rem] text-right text-[0.8rem] text-text-dim">{choices.length === 1 ? CHOICE_LABEL[choices[0]] : status === "missing" ? "Needs adding here" : "Linked"}</span>
      )}
    </div>
  );
}

// --- Import ------------------------------------------------------------------------------------------------------------

export function ImportProjectDialog({
  orgId,
  projects,
  initialInto,
  onClose,
  onImported,
}: {
  orgId: string;
  projects: Folder[];
  initialInto?: string | null;
  onClose: () => void;
  onImported: (summary: ImportSummary) => void;
}) {
  const ref = useDialogRef(true);
  const [file, setFile] = useState<File | null>(null);
  const [into, setInto] = useState<string>(initialInto ?? "");
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [picks, setPicks] = useState<Record<string, ImportChoice>>({});
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  async function check() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.projects.preview(file, into || null, orgId);
      setPlan(p);
      setPicks({});
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't read the package");
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      const done = await api.projects.apply(plan.token, picks);
      setSummary(done);
      onImported(done);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The import failed — nothing was changed");
    } finally {
      setBusy(false);
    }
  }

  function close() {
    if (plan && !summary) void api.projects.cancel(plan.token).catch(() => {});
    onClose();
  }

  const counts = useMemo(() => {
    if (!plan) return null;
    const all = [...plan.templates, ...plan.resources, ...plan.term_sets, ...plan.fonts];
    const by = (s: string) => all.filter((i) => i.status === s).length;
    return { new: by("new"), here: by("identical") + by("identical_elsewhere"), differ: by("differs") + by("exists"), missing: by("missing") };
  }, [plan]);

  return (
    <dialog ref={ref} className="modal modal-wide" onCancel={close} onClose={close}>
      <ModalClose />
      <div className="mb-3 flex items-center gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-strong">
          <Upload size={20} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 className="panel-title m-0">{summary ? "Imported" : plan ? `Import “${plan.project.name}”` : "Import a project"}</h2>
          <p className="muted m-0 text-[0.84rem]">
            {summary
              ? "Done — here's what changed."
              : plan
                ? `Packed ${plan.project.exported_at ? new Date(plan.project.exported_at).toLocaleString() : ""}${plan.project.exported_by ? ` by ${plan.project.exported_by}` : ""}. Nothing has changed yet — check each item, then import.`
                : "A package exported from another server: its templates, their files, and what they use."}
          </p>
        </div>
      </div>
      {error && <p className="alert alert-error">{error}</p>}

      {!plan && !summary && (
        <div className="grid gap-3">
          <label
            className={`grid cursor-pointer place-items-center gap-1 rounded-[12px] border-2 border-dashed px-4 py-7 text-center ${dragging ? "border-accent bg-accent-soft" : "border-border hover:border-accent-border"}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              setFile(e.dataTransfer.files?.[0] ?? null);
            }}
          >
            <Package size={26} className="text-text-faint" aria-hidden="true" />
            <span className="text-[0.92rem] font-medium">{file ? file.name : "Drop a .aksor-project.zip here, or choose one"}</span>
            {file && <span className="mono text-[0.75rem] text-text-faint">{kb(file.size)}</span>}
            <input type="file" accept=".zip" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <div className="grid gap-1.5">
            <span className="field-label">Import into</span>
            <label className="checkbox-label mb-0">
              <input type="radio" name="into" checked={!into} onChange={() => setInto("")} /> A new project, named as in the package
            </label>
            <label className="checkbox-label mb-0">
              <input type="radio" name="into" checked={!!into} onChange={() => setInto(projects[0]?.id ?? "")} disabled={projects.length === 0} /> An existing project — update it
            </label>
            {!!into && (
              <select className="ml-6 w-auto" value={into} onChange={(e) => setInto(e.target.value)} aria-label="Existing project">
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}
            <p className="field-hint m-0">Updating matches templates by their code, else by name, and adds a version to each — nothing is duplicated.</p>
          </div>
        </div>
      )}

      {plan && !summary && counts && (
        <div className="grid gap-4">
          <div className="flex flex-wrap gap-2 text-[0.8rem]">
            {(
              [
                ["new", counts.new, "new"],
                ["identical", counts.here, "already here"],
                ["differs", counts.differ, "to decide"],
                ["missing", counts.missing, "missing"],
              ] as const
            )
              .filter(([, n]) => n > 0)
              .map(([status, n, label]) => (
                <span key={status} className="inline-flex items-center gap-1.5">
                  <Stamp status={status} /> <span className="text-text-dim">{n} {label}</span>
                </span>
              ))}
          </div>

          <Section title="Templates" count={plan.templates.length}>
            {plan.templates.map((t) => {
              const Icon = EXT_ICON[t.template_ext] ?? FileText;
              return (
                <Row
                  key={t.key}
                  icon={<Icon size={15} aria-hidden="true" />}
                  name={`${t.folder ? `${t.folder}/` : ""}${t.name}`}
                  detail={t.match ? `here as v${t.match.version}${t.code ? ` · ${t.code}` : ""}` : t.code_note ?? (t.code ?? undefined)}
                  status={t.status}
                  choices={t.choices}
                  value={picks[t.key] ?? t.default ?? undefined} onPick={(c) => setPicks((p) => ({ ...p, [t.key]: c }))}
                />
              );
            })}
          </Section>

          {plan.resources.length > 0 && (
            <Section title="Images and stylesheets" count={plan.resources.length}>
              {plan.resources.map((r) => (
                <Row
                  key={r.key}
                  icon={r.kind === "image" ? <ImageIcon size={15} aria-hidden="true" /> : <Palette size={15} aria-hidden="true" />}
                  name={r.name}
                  detail={[r.scope === "shared" ? "shared" : "project's own", r.existing ? `here: ${r.existing.where}` : "", r.included ? "" : "not in the package"].filter(Boolean).join(" · ")}
                  status={r.status}
                  choices={r.choices}
                  value={picks[r.key] ?? r.default ?? undefined} onPick={(c) => setPicks((p) => ({ ...p, [r.key]: c }))}
                />
              ))}
              {plan.resources.some((r) => r.status === "differs") && (
                <p className="field-hint m-0">
                  <b>Overwrite</b> changes the file every template here uses. <b>Keep both</b> gives the imported templates their own copy, inside the project. <b>Keep the one here</b> leaves it as it is.
                </p>
              )}
            </Section>
          )}

          {(plan.fonts.length > 0 || plan.term_sets.length > 0) && (
            <Section title="Fonts and protected terms" count={plan.fonts.length + plan.term_sets.length}>
              {plan.fonts.map((f) => (
                <Row key={f.key} icon={<Type size={15} aria-hidden="true" />} name={`${f.family} ${f.subfamily}`} detail={f.note ?? "for the whole server"} status={f.status} choices={f.choices} value={picks[f.key] ?? f.default ?? undefined} onPick={(c) => setPicks((p) => ({ ...p, [f.key]: c }))} />
              ))}
              {plan.term_sets.map((t) => (
                <Row key={t.key} icon={<span className="font-mono text-[0.7rem]">ក</span>} name={t.name} detail={`${t.terms} terms`} status={t.status} choices={t.choices} value={picks[t.key] ?? t.default ?? undefined} onPick={(c) => setPicks((p) => ({ ...p, [t.key]: c }))} />
              ))}
            </Section>
          )}

          {plan.warnings.length > 0 && (
            <ul className="alert alert-warning m-0 grid list-none gap-0.5 pl-3">
              {plan.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {summary && (
        <div className="grid gap-3">
          {(
            [
              ["Created", summary.created],
              ["Updated", summary.updated],
              ["Already here — linked", summary.linked],
              ["Skipped", summary.skipped],
            ] as const
          )
            .filter(([, items]) => items.length)
            .map(([title, items]) => (
              <Section key={title} title={title} count={items.length}>
                <ul className="m-0 grid list-none gap-0.5 p-0 text-[0.86rem]">
                  {items.map((i) => (
                    <li key={i}>{i}</li>
                  ))}
                </ul>
              </Section>
            ))}
          {summary.warnings.length > 0 && (
            <ul className="alert alert-warning m-0 grid list-none gap-0.5 pl-3">
              {summary.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="dialog-actions">
        {summary ? (
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Close
          </button>
        ) : (
          <>
            {plan ? (
              <button type="button" className="btn" onClick={() => setPlan(null)} disabled={busy}>
                Back
              </button>
            ) : (
              <button type="button" className="btn" onClick={close}>
                Cancel
              </button>
            )}
            {plan ? (
              <button type="button" className="btn btn-primary" onClick={() => void run()} disabled={busy}>
                {busy ? <span className="spinner" /> : <ArrowRight size={14} aria-hidden="true" />} Import
              </button>
            ) : (
              <button type="button" className="btn btn-primary" onClick={() => void check()} disabled={!file || busy}>
                {busy ? <span className="spinner" /> : <ArrowRight size={14} aria-hidden="true" />} Check the package
              </button>
            )}
          </>
        )}
      </div>
    </dialog>
  );
}
