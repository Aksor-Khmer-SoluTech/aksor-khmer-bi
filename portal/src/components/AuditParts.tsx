import { useState, type ReactNode } from "react";
import { Download, Lock, Pencil, Plus, ShieldAlert, Trash2, type LucideIcon } from "lucide-react";
import type { AuditChange, AuditEvent } from "../types";
import { useCopy } from "../hooks";

/** Shared building blocks for everything that shows the change audit trail
 * -- a template's History tab (HistoryTab.tsx) and the admin Audit log page
 * (admin/audit/AuditLogPage.tsx) -- so a change reads the same wherever an
 * investigator meets it. */

// --- formatting ---------------------------------------------------------------

/** Absolute, locale-aware, with the year only when it isn't this one -- an
 * investigation needs exact times, not "3 hours ago". The full ISO instant
 * goes in a tooltip via `stampTitle`. */
export function fmtStamp(iso: string): string {
  const d = new Date(iso);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
  });
}

export const stampTitle = (iso: string) => new Date(iso).toISOString();

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export function fmtDelta(n: number): string {
  if (n === 0) return "±0";
  return `${n > 0 ? "+" : "−"}${fmtBytes(Math.abs(n))}`;
}

// --- what kind of change an action is -------------------------------------------

export type ActionTone = "add" | "remove" | "edit" | "read" | "security";

/** Bucket an action code ("report.file_replace", "user.totp_reset") by what
 * it does to the thing, so every feed can colour and mark it the same way.
 * Credential resets are their own tone: they're the rows an investigator
 * scans for first. */
export function actionTone(action: string): ActionTone {
  const verb = action.slice(action.indexOf(".") + 1);
  if (/password_reset|totp_reset|totp_disable|password_change/.test(verb)) return "security";
  if (/download|^test$/.test(verb)) return "read";
  if (/delete|revoke|remove/.test(verb)) return "remove";
  if (/create|upload|grant|add|enable/.test(verb)) return "add";
  return "edit";
}

const TONES: Record<ActionTone, { icon: LucideIcon; box: string; label: string }> = {
  add: { icon: Plus, box: "bg-success-soft text-success-strong border-success/30", label: "Added" },
  remove: { icon: Trash2, box: "bg-danger-soft text-danger-strong border-danger/30", label: "Removed" },
  edit: { icon: Pencil, box: "bg-accent-soft text-accent-strong border-accent-border", label: "Changed" },
  read: { icon: Download, box: "bg-info-soft text-info-strong border-info/30", label: "Accessed" },
  security: { icon: ShieldAlert, box: "bg-highlight-soft text-highlight border-highlight/30", label: "Credential" },
};

export function ActionGlyph({ action, size = 28 }: { action: string; size?: number }) {
  const tone = actionTone(action);
  const { icon: Icon, box, label } = TONES[tone];
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-sm border ${box}`}
      style={{ width: size, height: size }}
      title={label}
    >
      <Icon size={Math.round(size * 0.52)} strokeWidth={1.8} aria-label={label} />
    </span>
  );
}

export function isReadEvent(action: string): boolean {
  return actionTone(action) === "read";
}

// --- a short, copyable checksum ---------------------------------------------------

/** A checksum, shortened but complete on hover and on copy. Deliberately not
 * CopyButton: that one is absolutely positioned into the corner of a code
 * block (`.copy-btn`), which here would float over the row's timestamp. */
export function ShortHash({ hash, label = "sha256", copyable = true }: { hash: string; label?: string; copyable?: boolean }) {
  const [copied, copy] = useCopy();
  return (
    <span className="inline-flex items-center gap-1.5 text-[0.72rem] text-text-faint" title={hash}>
      {label}
      <span className="font-mono text-text-dim">{hash.slice(0, 10)}</span>
      {copyable && (
        <button
          type="button"
          onClick={() => copy(hash)}
          className={`cursor-pointer rounded-sm border bg-transparent px-1.5 font-mono text-[0.68rem] leading-4 transition-colors ${
            copied ? "border-success/40 text-success" : "border-border-soft text-text-faint hover:border-accent-border hover:text-accent-strong"
          }`}
        >
          {copied ? "copied" : "copy"}
        </button>
      )}
    </span>
  );
}

// --- field-level diffs ----------------------------------------------------------------

function Empty() {
  return <span className="italic text-text-faint">empty</span>;
}

function show(value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") return <Empty />;
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

const CHIP = "inline-flex max-w-full items-center gap-1 rounded-sm px-1.5 py-px font-mono text-[0.76rem] leading-5 break-all";

function Chips({ items, sign, more }: { items: unknown[]; sign: "+" | "−" | "~"; more: number }) {
  if (items.length === 0 && more === 0) return null;
  const tone =
    sign === "+"
      ? "bg-success-soft text-success-strong"
      : sign === "−"
        ? "bg-danger-soft text-danger-strong line-through decoration-danger/50"
        : "bg-info-soft text-info-strong";
  return (
    <>
      {items.map((item, i) => (
        <span key={i} className={`${CHIP} ${tone}`}>
          <span className="no-underline">{sign}</span>
          {String(item)}
        </span>
      ))}
      {more > 0 && <span className="text-[0.74rem] text-text-faint">and {more} more {sign === "+" ? "added" : "removed"}</span>}
    </>
  );
}

function ChangeValue({ change }: { change: AuditChange }) {
  if (change.redacted) {
    return (
      <span className="inline-flex items-center gap-1.5 text-text-dim">
        <Lock size={12} aria-hidden /> changed — the value is never stored
      </span>
    );
  }
  if (change.opaque) return <span className="text-text-dim">changed — value not recorded</span>;

  if (change.added || change.removed || change.modified) {
    const added = change.added ?? [];
    const removed = change.removed ?? [];
    const modified = change.modified ?? [];
    return (
      <span className="flex flex-wrap items-center gap-1">
        <Chips items={removed} sign="−" more={(change.removed_count ?? removed.length) - removed.length} />
        <Chips items={added} sign="+" more={(change.added_count ?? added.length) - added.length} />
        <Chips items={modified} sign="~" more={0} />
      </span>
    );
  }

  return (
    <span className="flex flex-wrap items-baseline gap-x-1.5 gap-y-1">
      <span className="rounded-sm bg-danger-soft px-1.5 py-px text-danger-strong line-through decoration-danger/40 break-words">
        {show(change.before)}
      </span>
      <span className="text-text-faint" aria-label="became">
        →
      </span>
      <span className="rounded-sm bg-success-soft px-1.5 py-px text-success-strong break-words">{show(change.after)}</span>
    </span>
  );
}

/** The field-by-field "what changed" of one event. `max` rows show at once
 * (a 40-field config edit shouldn't own the screen); the rest are a click away. */
export function AuditChanges({ changes, max = 5 }: { changes: AuditChange[] | null; max?: number }) {
  const [all, setAll] = useState(false);
  if (!changes || changes.length === 0) return null;
  const shown = all ? changes : changes.slice(0, max);
  return (
    // One grid for every row, its label column sized to the longest field name
    // (up to 16rem), so the values line up and a name like
    // `data_source.headers.X-Portal-Auth` stays on one line.
    <div className="mt-2 grid grid-cols-[fit-content(16rem)_1fr] items-baseline gap-x-3 gap-y-1.5 rounded-sm border border-border-soft bg-bg-panel/50 px-3 py-2.5 text-[0.8rem] max-sm:grid-cols-1">
      {shown.map((c) => (
        <div key={c.field} className="contents">
          <span className="font-mono text-[0.76rem] text-text-faint [overflow-wrap:anywhere]">{c.field}</span>
          <ChangeValue change={c} />
        </div>
      ))}
      {changes.length > max && (
        <button type="button" className="link-btn col-span-full justify-self-start text-[0.76rem]" onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show ${changes.length - max} more field${changes.length - max === 1 ? "" : "s"}`}
        </button>
      )}
    </div>
  );
}

// --- the incidental facts of an event ---------------------------------------------------

function detailValue(key: string, value: unknown): ReactNode {
  if (key === "sha256" && typeof value === "string") return <ShortHash hash={value} label="" />;
  if (value === null || value === undefined || value === "") return <Empty />;
  if (typeof value === "object") return <span className="font-mono text-[0.76rem] break-all">{JSON.stringify(value)}</span>;
  return <span className="break-words">{String(value)}</span>;
}

/** `details` (version numbers, checksums, the role granted...) as a compact
 * key/value list. Skips keys the caller already shows elsewhere. */
export function EventDetails({ event, skip = [] }: { event: AuditEvent; skip?: string[] }) {
  const entries = Object.entries(event.details ?? {}).filter(([k, v]) => !skip.includes(k) && v !== undefined);
  if (entries.length === 0) return null;
  return (
    <dl className="mt-2 grid grid-cols-[fit-content(16rem)_1fr] gap-x-3 gap-y-1 text-[0.8rem] max-sm:grid-cols-1">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="font-mono text-[0.76rem] text-text-faint [overflow-wrap:anywhere]">{k}</dt>
          <dd className="m-0 text-text-dim">{detailValue(k, v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Who and from where -- the same line under every event. */
export function ActorLine({ event }: { event: AuditEvent }) {
  return (
    <span className="text-[0.78rem] text-text-faint">
      <span className="font-medium text-text-dim">{event.actor_username}</span>
      {event.ip_address && (
        <>
          {" · "}
          <span className="font-mono">{event.ip_address}</span>
        </>
      )}
    </span>
  );
}

export const ENTITY_TYPES: { value: string; label: string }[] = [
  { value: "report", label: "Templates" },
  { value: "user", label: "Users" },
  { value: "role", label: "Roles" },
  { value: "organization", label: "Organizations" },
  { value: "ldap_config", label: "AD / LDAP" },
  { value: "protected_term_set", label: "Protected term sets" },
  { value: "deployment_terms", label: "Deployment terms" },
  { value: "job", label: "Jobs" },
  { value: "folder", label: "Folders" },
  { value: "image", label: "Images" },
  { value: "stylesheet", label: "Stylesheets" },
];
