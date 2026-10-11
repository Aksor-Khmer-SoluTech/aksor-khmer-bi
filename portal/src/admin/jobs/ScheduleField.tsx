import { useEffect, useState } from "react";
import { CalendarClock } from "lucide-react";
import { api, ApiError } from "../../api";
import type { SchedulePreview } from "../../types";

/** A cron schedule picked the way people say it -- "every weekday at 08:30" -- and stored as the 5-field crontab
 * expression the API keeps (`cron_expression`). Anything the presets can't express opens as Custom, the expression
 * itself. Below it, the next few runs as the scheduler itself reads them (POST /jobs/schedule-preview), in the time
 * zone it runs in -- the one thing a cron expression never says. */

type Repeat = "hourly" | "daily" | "weekdays" | "weekly" | "monthly" | "custom";

interface Parts {
  repeat: Repeat;
  minute: number;
  hour: number;
  /** Crontab numbering: 0 = Sunday. */
  days: number[];
  dayOfMonth: number;
}

const REPEAT_LABEL: Record<Repeat, string> = {
  hourly: "Every hour",
  daily: "Every day",
  weekdays: "Every weekday (Mon–Fri)",
  weekly: "Every week, on…",
  monthly: "Every month, on day…",
  custom: "Custom (cron expression)",
};

// Monday first, the way a working week reads; values stay crontab's.
const WEEK = [
  { value: 1, short: "Mon" },
  { value: 2, short: "Tue" },
  { value: 3, short: "Wed" },
  { value: 4, short: "Thu" },
  { value: 5, short: "Fri" },
  { value: 6, short: "Sat" },
  { value: 0, short: "Sun" },
];

const int = (s: string, max: number) => (/^\d{1,2}$/.test(s) && Number(s) <= max ? Number(s) : null);

export function parseCron(expression: string): Parts {
  const fallback: Parts = { repeat: "custom", minute: 0, hour: 8, days: [1], dayOfMonth: 1 };
  const f = expression.trim().split(/\s+/);
  if (f.length !== 5) return fallback;
  const [mi, ho, dom, mon, dow] = f;
  const minute = int(mi, 59);
  if (minute === null || mon !== "*") return fallback;
  if (ho === "*" && dom === "*" && dow === "*") return { ...fallback, repeat: "hourly", minute };
  const hour = int(ho, 23);
  if (hour === null) return fallback;
  const base = { ...fallback, minute, hour };
  if (dom === "*" && dow === "*") return { ...base, repeat: "daily" };
  if (dom === "*" && dow === "1-5") return { ...base, repeat: "weekdays" };
  if (dom === "*" && /^[0-7](,[0-7])*$/.test(dow)) {
    return { ...base, repeat: "weekly", days: [...new Set(dow.split(",").map((d) => Number(d) % 7))] };
  }
  const day = int(dom, 31);
  if (day !== null && day >= 1 && dow === "*") return { ...base, repeat: "monthly", dayOfMonth: day };
  return fallback;
}

function buildCron(p: Parts): string {
  switch (p.repeat) {
    case "hourly":
      return `${p.minute} * * * *`;
    case "daily":
      return `${p.minute} ${p.hour} * * *`;
    case "weekdays":
      return `${p.minute} ${p.hour} * * 1-5`;
    case "weekly":
      return `${p.minute} ${p.hour} * * ${[...p.days].sort((a, b) => a - b).join(",") || "1"}`;
    case "monthly":
      return `${p.minute} ${p.hour} ${p.dayOfMonth} * *`;
    default:
      return "";
  }
}

const pad = (n: number) => String(n).padStart(2, "0");

/** "Mon 13 Oct, 08:30" -- the wall-clock time the ISO string carries (its own offset, the scheduler's zone), not
 * converted to the viewer's: the schedule is set in that zone, so that is the time that should read back. */
function wallClock(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return iso;
  const [, y, mo, d, h, mi] = m;
  const date = new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d)));
  const day = date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  return `${day}, ${h}:${mi}`;
}

export default function ScheduleField({
  value,
  onChange,
  startDate,
  endDate,
}: {
  value: string;
  onChange: (cron: string) => void;
  /** The job's validity window, ISO -- so the preview skips runs outside it, as the scheduler will. */
  startDate?: string | null;
  endDate?: string | null;
}) {
  const [parts, setParts] = useState<Parts>(() => parseCron(value));
  const [preview, setPreview] = useState<SchedulePreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  function update(next: Partial<Parts>) {
    const merged = { ...parts, ...next };
    setParts(merged);
    if (merged.repeat !== "custom") onChange(buildCron(merged));
  }

  useEffect(() => {
    if (!value.trim()) {
      setPreview(null);
      setPreviewError(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api.jobs
        .previewSchedule({ cron_expression: value, start_date: startDate || null, end_date: endDate || null, count: 3 })
        .then((p) => {
          if (cancelled) return;
          setPreview(p);
          setPreviewError(null);
        })
        .catch((err) => {
          if (cancelled) return;
          setPreview(null);
          setPreviewError(err instanceof ApiError ? err.message.replace(/^Invalid cron_expression: /, "") : "Couldn't check the schedule");
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [value, startDate, endDate]);

  const time = `${pad(parts.hour)}:${pad(parts.minute)}`;
  const setTime = (t: string) => {
    const [h, m] = t.split(":").map(Number);
    if (!Number.isNaN(h) && !Number.isNaN(m)) update({ hour: h, minute: m });
  };

  return (
    <div className="mb-3.5">
      <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
        <label>
          <span>Repeat</span>
          <select
            value={parts.repeat}
            onChange={(e) => {
              const repeat = e.target.value as Repeat;
              if (repeat === "custom") {
                setParts({ ...parts, repeat });
                return;
              }
              update({ repeat });
            }}
          >
            {(Object.keys(REPEAT_LABEL) as Repeat[]).map((r) => (
              <option key={r} value={r}>
                {REPEAT_LABEL[r]}
              </option>
            ))}
          </select>
        </label>

        {parts.repeat === "hourly" && (
          <label>
            <span>At minute</span>
            <input type="number" min={0} max={59} required value={parts.minute} onChange={(e) => update({ minute: Math.min(59, Math.max(0, Number(e.target.value) || 0)) })} />
          </label>
        )}
        {(parts.repeat === "daily" || parts.repeat === "weekdays" || parts.repeat === "weekly" || parts.repeat === "monthly") && (
          <label>
            <span>At</span>
            <input type="time" required value={time} onChange={(e) => setTime(e.target.value)} />
          </label>
        )}
        {parts.repeat === "custom" && (
          <label>
            <span>Cron expression</span>
            <input type="text" required className="mono" value={value} placeholder="30 8 * * 1-5" onChange={(e) => onChange(e.target.value)} />
          </label>
        )}
      </div>

      {parts.repeat === "weekly" && (
        <div className="-mt-1 mb-3.5 flex flex-wrap gap-1.5" role="group" aria-label="Days of the week">
          {WEEK.map((d) => {
            const on = parts.days.includes(d.value);
            return (
              <button
                key={d.value}
                type="button"
                aria-pressed={on}
                className={`btn btn-sm min-w-[3.25rem] ${on ? "btn-primary" : ""}`}
                onClick={() => {
                  const days = on ? parts.days.filter((x) => x !== d.value) : [...parts.days, d.value];
                  if (days.length > 0) update({ days });
                }}
              >
                {d.short}
              </button>
            );
          })}
        </div>
      )}
      {parts.repeat === "monthly" && (
        <label className="max-w-[12rem]">
          <span>Day of the month</span>
          <input
            type="number"
            min={1}
            max={31}
            required
            value={parts.dayOfMonth}
            onChange={(e) => update({ dayOfMonth: Math.min(31, Math.max(1, Number(e.target.value) || 1)) })}
          />
        </label>
      )}
      {parts.repeat === "monthly" && parts.dayOfMonth > 28 && (
        <p className="field-hint -mt-2 mb-3">Months without a day {parts.dayOfMonth} are skipped.</p>
      )}
      {parts.repeat === "custom" && (
        <p className="field-hint -mt-2 mb-3">
          Five fields: minute, hour, day of month, month, day of week (0 or 7 = Sunday). <span className="mono">30 8 * * 1-5</span> is 08:30 on
          weekdays; <span className="mono">0 */6 * * *</span> is every six hours.
        </p>
      )}

      <div
        className={`flex items-start gap-2.5 rounded-sm border px-3 py-2.5 text-[0.8rem] ${
          previewError ? "border-danger/40 bg-danger/5 text-danger" : "border-border-soft bg-bg-panel text-text-dim"
        }`}
        aria-live="polite"
      >
        <CalendarClock size={16} className="mt-px shrink-0" aria-hidden="true" />
        {previewError ? (
          <span>{previewError}</span>
        ) : preview ? (
          preview.next_runs.length === 0 ? (
            <span>It won't run again — the end of its validity window comes first.</span>
          ) : (
            <span>
              <span className="font-medium text-text">Next runs:</span> {preview.next_runs.map(wallClock).join(" · ")}
              <span className="block text-[0.74rem] text-text-faint">
                Times are {preview.timezone} time{parts.repeat !== "custom" && <> · cron <span className="mono">{value}</span></>}
              </span>
            </span>
          )
        ) : (
          <span className="text-text-faint">Checking the schedule…</span>
        )}
      </div>
    </div>
  );
}
