import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { Folder, Info, Lock, Mail, Send, X } from "lucide-react";
import { api } from "../../api";
import type { ConnectionSummary, RunForm } from "../../types";
import type { ReportJobConfig } from "./ReportJobFields";

/** Where a Render-report job's file goes, and splitting it into one file per value of a filter ("bursting"). Edits
 * the same config as ReportJobFields; the API checks it all again on save (app/job_delivery.py):
 *
 *   destination_path?                    -- save to a folder on the server
 *   email?: {connection, to, cc, subject, body}
 *   burst?: {by, values: [{value, to, cc}], skip_empty}
 */

export interface EmailSettings {
  connection: string;
  to: string[];
  cc: string[];
  subject: string;
  body: string;
}

export interface BurstSettings {
  by: string;
  values: { value: string; to: string[]; cc: string[] }[];
  skip_empty: boolean;
}

const EMAIL_RE = /^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$/;

/** Addresses as chips: type one and press Enter, comma or space (or leave the field); paste a list; Backspace removes
 * the last. Anything that doesn't look like an address stays in the box, marked, instead of vanishing. */
function AddressInput({ value, onChange, label, placeholder }: { value: string[]; onChange: (next: string[]) => void; label: string; placeholder?: string }) {
  const [text, setText] = useState("");
  const invalid = text.trim() !== "" && !EMAIL_RE.test(text.trim());

  function commit(raw: string) {
    const parts = raw.split(/[\s,;]+/).map((p) => p.trim()).filter(Boolean);
    const good = parts.filter((p) => EMAIL_RE.test(p) && !value.some((v) => v.toLowerCase() === p.toLowerCase()));
    const bad = parts.filter((p) => !EMAIL_RE.test(p));
    if (good.length) onChange([...value, ...good]);
    setText(bad.join(" "));
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === "," || e.key === " " || e.key === ";") {
      if (text.trim()) {
        e.preventDefault();
        commit(text);
      } else if (e.key === "Enter") {
        e.preventDefault();
      }
    } else if (e.key === "Backspace" && !text && value.length) {
      onChange(value.slice(0, -1));
    }
  }

  return (
    <div
      className={`flex min-h-[40px] flex-wrap items-center gap-1.5 rounded-sm border bg-bg-input px-2 py-1.5 ${invalid ? "border-danger" : "border-border"}`}
      onClick={(e) => (e.currentTarget.querySelector("input") as HTMLInputElement | null)?.focus()}
    >
      {value.map((address) => (
        <span key={address} className="inline-flex items-center gap-1 rounded-full bg-bg-panel py-0.5 pr-1 pl-2.5 text-[0.8rem] text-text">
          {address}
          <button
            type="button"
            className="grid h-[18px] w-[18px] place-items-center rounded-full text-text-faint hover:bg-border-soft hover:text-text"
            aria-label={`Remove ${address}`}
            onClick={() => onChange(value.filter((v) => v !== address))}
          >
            <X size={12} aria-hidden="true" />
          </button>
        </span>
      ))}
      <input
        type="text"
        className="min-w-[5rem] flex-1 border-0 bg-transparent p-1 text-[0.9rem] outline-none"
        style={{ boxShadow: "none" }}
        aria-label={label}
        aria-invalid={invalid}
        placeholder={value.length ? "" : (placeholder ?? "Add an address")}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => text.trim() && commit(text)}
        onPaste={(e) => {
          const pasted = e.clipboardData.getData("text");
          if (/[\s,;]/.test(pasted.trim())) {
            e.preventDefault();
            commit(text + pasted);
          }
        }}
      />
    </div>
  );
}

function Channel({ on, onToggle, icon, title, note, disabled, badge }: {
  on: boolean;
  onToggle?: () => void;
  icon: React.ReactNode;
  title: string;
  note: string;
  disabled?: boolean;
  badge?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={disabled}
      onClick={onToggle}
      className={`grid content-start gap-1.5 rounded-[12px] border p-3 text-left transition-colors ${
        on ? "border-accent bg-accent-soft" : "border-border bg-bg-raised hover:border-border-strong"
      } ${disabled ? "cursor-default opacity-60" : "cursor-pointer"}`}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[0.9rem] font-semibold text-text">
          {icon}
          {title}
        </span>
        {badge ? (
          <span className="rounded-full bg-highlight-soft px-1.5 py-0.5 text-[0.62rem] font-semibold tracking-wide text-highlight uppercase">{badge}</span>
        ) : (
          <span
            aria-hidden="true"
            className={`grid h-[18px] w-[18px] place-items-center rounded-[5px] border-[1.5px] ${on ? "border-accent bg-accent text-white" : "border-border"}`}
          >
            {on && <span className="h-[5px] w-[9px] translate-y-[-1px] -rotate-45 border-b-2 border-l-2 border-white" />}
          </span>
        )}
      </span>
      <span className="text-[0.8rem] leading-snug text-text-dim">{note}</span>
    </button>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <h3 className="mb-2.5 text-[0.72rem] font-bold tracking-[0.08em] text-text-faint uppercase">{title}</h3>
      {children}
    </section>
  );
}

/** The simple {{ name }} filling the preview shows -- the server's Jinja is the real one. */
function fill(template: string, values: Record<string, string>) {
  return template.replace(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g, (all, name: string) => (name in values ? values[name] : all));
}

const today = () => {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
};

export default function DeliveryFields({
  config,
  onChange,
  form,
  reportName,
}: {
  config: ReportJobConfig;
  onChange: (next: ReportJobConfig) => void;
  /** The chosen report's run form: its filters and their choices. Null until a report is chosen. */
  form: RunForm | null;
  reportName: string;
}) {
  const [mailServers, setMailServers] = useState<ConnectionSummary[] | null>(null);
  useEffect(() => {
    api.connections
      .list()
      .then((all) => setMailServers(all.filter((c) => c.kind === "smtp")))
      .catch(() => setMailServers([]));
  }, []);

  const email = config.email as EmailSettings | undefined;
  const burst = config.burst as BurstSettings | undefined;
  const folderOn = typeof config.destination_path === "string";
  const splittable = useMemo(() => (form?.parameters ?? []).filter((p) => p.options && p.options.length > 0), [form]);
  const burstParam = burst ? splittable.find((p) => p.name === burst.by) : undefined;

  const set = (patch: Partial<ReportJobConfig>) => onChange({ ...config, ...patch });
  const without = (key: string) => {
    const next = { ...config };
    delete next[key];
    return next;
  };

  function toggleFolder() {
    if (folderOn) onChange(without("destination_path"));
    else set({ destination_path: `/data/output/${(reportName || "report").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "report"}-${burst ? "{value}-" : ""}{timestamp}.${config.format ?? "pdf"}` });
  }

  function toggleEmail() {
    if (email) onChange(without("email"));
    else
      set({
        email: {
          connection: mailServers?.[0]?.name ?? "",
          to: [],
          cc: [],
          subject: burst ? "{{ report }} · {{ value_label }} · {{ date }}" : "{{ report }} · {{ date }}",
          body: "Hello,\n\nThe {{ report }} is attached.",
        } satisfies EmailSettings,
      });
  }

  function setEmail(patch: Partial<EmailSettings>) {
    set({ email: { ...(email as EmailSettings), ...patch } });
  }

  function chooseSplit(by: string) {
    const param = splittable.find((p) => p.name === by);
    if (!param) return;
    const kept = new Map((burst?.by === by ? burst.values : []).map((v) => [v.value, v]));
    const values = (param.options ?? []).map((o) => kept.get(o.value) ?? { value: o.value, to: [], cc: [] });
    const parameters = { ...(config.parameters ?? {}) };
    delete parameters[by]; // each value takes its turn, so the filter can't also be fixed
    set({ parameters, burst: { by, values, skip_empty: burst?.skip_empty ?? true } satisfies BurstSettings });
  }

  function toggleBurst() {
    if (burst) onChange(without("burst"));
    else if (splittable[0]) chooseSplit(splittable[0].name);
  }

  function setValue(value: string, patch: { to?: string[]; cc?: string[] }) {
    if (!burst) return;
    set({ burst: { ...burst, values: burst.values.map((v) => (v.value === value ? { ...v, ...patch } : v)) } });
  }

  const labelOf = (value: string) => burstParam?.options?.find((o) => o.value === value)?.label ?? value;
  const names = ["report", "date", ...(burst ? ["value", "value_label"] : []), ...(form?.parameters ?? []).flatMap((p) => [p.name, `${p.name}_label`])];

  const first = burst?.values[0];
  const previewValues: Record<string, string> = {
    report: reportName || "Report",
    date: today(),
    value: first?.value ?? "",
    value_label: first ? labelOf(first.value) : "",
    ...(burst && first ? { [burst.by]: first.value, [`${burst.by}_label`]: labelOf(first.value) } : {}),
    ...Object.fromEntries(Object.entries(config.parameters ?? {}).flatMap(([k, v]) => [[k, v], [`${k}_label`, v]])),
  };

  const sendCount = burst ? burst.values.length : 1;
  const everyone = email ? email.to.length + email.cc.length : 0;
  const unassigned = burst?.values.filter((v) => !v.to.length && !v.cc.length) ?? [];

  return (
    <>
      <Section title="Where it goes">
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
          <Channel on={folderOn} onToggle={toggleFolder} icon={<Folder size={16} aria-hidden="true" />} title="Save to a folder" note="A path on the server." />
          <Channel on={!!email} onToggle={toggleEmail} icon={<Mail size={16} aria-hidden="true" />} title="Email" note="Through a mail server set up under Connections." />
          <Channel on={false} disabled badge="Next" icon={<Send size={16} aria-hidden="true" />} title="Telegram" note="A bot posts the file to a chat or group." />
        </div>
        {!folderOn && !email && <p className="field-hint mt-2 text-danger">Choose at least one: save it to a folder, email it, or both.</p>}

        {folderOn && (
          <label className="mt-3.5">
            <span>Save to</span>
            <input
              type="text"
              className="mono"
              required
              value={config.destination_path as string}
              onChange={(e) => set({ destination_path: e.target.value })}
            />
            <span className="field-hint">
              A path on the server. <span className="mono">{"{timestamp}"}</span>
              {burst && (
                <>
                  , <span className="mono">{"{value}"}</span>
                </>
              )}{" "}
              and <span className="mono">{"{job_id}"}</span> are filled in on each run, so files don't overwrite each other.
            </span>
          </label>
        )}

        {email && (
          <div className="mt-3.5 grid gap-3 rounded-[12px] border border-border-soft p-3.5">
            <label className="mb-0">
              <span>Mail server</span>
              <select value={email.connection} required onChange={(e) => setEmail({ connection: e.target.value })}>
                <option value="" disabled>
                  {mailServers === null ? "Loading…" : mailServers.length ? "Choose a mail server…" : "No mail server yet"}
                </option>
                {mailServers?.map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name} · {c.base_url.split(" · ")[1] ?? c.base_url}
                  </option>
                ))}
              </select>
              {mailServers !== null && mailServers.length === 0 && (
                <span className="field-hint">
                  Add one under <a href="#/admin/connections">Manage → Connections → New Mail Server</a>.
                </span>
              )}
            </label>
            <div className="field-block">
              <span className="field-label">
                To {burst && <span className="muted">(gets every {burstParam?.label?.toLowerCase() ?? "value"}'s file)</span>}
              </span>
              <AddressInput label="To" value={email.to} onChange={(to) => setEmail({ to })} />
            </div>
            <div className="field-block">
              <span className="field-label">
                CC <span className="muted">(optional)</span>
              </span>
              <AddressInput label="CC" value={email.cc} onChange={(cc) => setEmail({ cc })} />
            </div>
            <label className="mb-0">
              <span>Subject</span>
              <input type="text" required maxLength={300} value={email.subject} onChange={(e) => setEmail({ subject: e.target.value })} />
            </label>
            <label className="mb-0">
              <span>Message</span>
              <textarea rows={4} maxLength={10000} value={email.body} onChange={(e) => setEmail({ body: e.target.value })} />
            </label>
            <p className="field-hint -mt-1.5">
              Fill in with {names.map((n, i) => (
                <span key={n}>
                  {i > 0 && " "}
                  <code className="mono">{`{{ ${n} }}`}</code>
                </span>
              ))}
              . The report is attached (up to 10 MB).
            </p>
            <div className="grid gap-1 rounded-sm bg-bg-panel px-3 py-2.5 text-[0.82rem]" aria-live="polite">
              <span className="text-[0.66rem] font-semibold tracking-[0.06em] text-text-faint uppercase">
                How {burst && first ? `the ${labelOf(first.value)}` : "the"} email will look
              </span>
              <b className="font-semibold text-text">{fill(email.subject, previewValues) || "(no subject)"}</b>
              <span className="whitespace-pre-line text-text-dim">{fill(email.body, previewValues)}</span>
            </div>
          </div>
        )}
      </Section>

      {form && (
        <Section title="One file per value">
          {splittable.length === 0 ? (
            <p className="field-hint">This report has no filter with a list of choices, so it can't be split into one file per value.</p>
          ) : (
            <>
              <label className="checkbox-label mb-0">
                <input type="checkbox" checked={!!burst} onChange={toggleBurst} />
                <span>
                  <b className="font-semibold text-text">Split the report by a filter</b>
                  <span className="block text-[0.8rem] text-text-dim">Each value gets its own run, its own file and its own recipients, with only that value's data.</span>
                </span>
              </label>

              {burst && (
                <div className="mt-3.5 grid gap-3 rounded-[12px] border border-border-soft p-3.5">
                  <label className="mb-0 sm:max-w-[50%]">
                    <span>Split by</span>
                    <select value={burst.by} onChange={(e) => chooseSplit(e.target.value)}>
                      {splittable.map((p) => (
                        <option key={p.name} value={p.name}>
                          {p.label ?? p.name} · {p.options?.length} value{p.options?.length === 1 ? "" : "s"}
                        </option>
                      ))}
                    </select>
                  </label>

                  {email && (
                    <div className="grid gap-0 overflow-hidden rounded-sm border border-border-soft" role="table" aria-label="Who gets each file">
                      <div
                        role="row"
                        className="hidden grid-cols-[minmax(9rem,1fr)_minmax(0,2fr)_minmax(0,2fr)] gap-3 bg-bg-panel px-3 py-2 text-[0.68rem] font-semibold tracking-[0.05em] text-text-faint uppercase sm:grid"
                      >
                        <span role="columnheader">{burstParam?.label ?? burst.by}</span>
                        <span role="columnheader">To</span>
                        <span role="columnheader">
                          CC <span className="normal-case">(optional)</span>
                        </span>
                      </div>
                      {burst.values.map((v) => (
                        <div
                          key={v.value}
                          role="row"
                          className="grid grid-cols-1 items-start gap-2 border-t border-border-soft px-3 py-2.5 first:border-t-0 sm:grid-cols-[minmax(9rem,1fr)_minmax(0,2fr)_minmax(0,2fr)] sm:gap-3 sm:[&:nth-child(2)]:border-t-0"
                        >
                          <span role="cell" className="pt-2 text-[0.88rem]">
                            <span className="text-text">{labelOf(v.value)}</span> <span className="mono text-[0.75rem] text-text-faint">{v.value}</span>
                          </span>
                          <span role="cell" className="min-w-0">
                            <AddressInput label={`To for ${labelOf(v.value)}`} value={v.to} onChange={(to) => setValue(v.value, { to })} placeholder="No one yet" />
                          </span>
                          <span role="cell" className="min-w-0">
                            <AddressInput label={`CC for ${labelOf(v.value)}`} value={v.cc} onChange={(cc) => setValue(v.value, { cc })} placeholder="—" />
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  <label className="checkbox-label mb-0">
                    <input type="checkbox" checked={burst.skip_empty} onChange={(e) => set({ burst: { ...burst, skip_empty: e.target.checked } })} />
                    Skip a {burstParam?.label?.toLowerCase() ?? "value"} with no data, rather than send an empty report
                  </label>

                  <div className="flex items-start gap-2.5 rounded-sm bg-accent-soft px-3 py-2.5 text-[0.82rem] text-accent-strong">
                    <Info size={16} className="mt-px shrink-0" aria-hidden="true" />
                    <span>
                      Each run makes <b>{sendCount} file{sendCount === 1 ? "" : "s"}</b>
                      {email && (
                        <>
                          {" "}
                          and sends up to <b>{sendCount} email{sendCount === 1 ? "" : "s"}</b>, one per {burstParam?.label?.toLowerCase() ?? "value"}
                          {everyone > 0 && <>. The To and CC above get every one</>}
                          {unassigned.length > 0 && everyone === 0 && (
                            <>
                              . {unassigned.length} {unassigned.length === 1 ? "has" : "have"} no one to send to, so {unassigned.length === 1 ? "it's" : "they're"}{" "}
                              {folderOn ? "only saved" : "skipped"}
                            </>
                          )}
                        </>
                      )}
                      .
                    </span>
                  </div>
                  <div className="flex items-start gap-2.5 rounded-sm border border-border-soft px-3 py-2.5 text-[0.8rem] text-text-dim">
                    <Lock size={15} className="mt-px shrink-0" aria-hidden="true" />
                    <span>
                      <b className="text-text">Checked against your access when you save.</b> You can only split by values you're allowed to run yourself, so a
                      job can never send out data its creator couldn't see.
                    </span>
                  </div>
                </div>
              )}
            </>
          )}
        </Section>
      )}
    </>
  );
}
