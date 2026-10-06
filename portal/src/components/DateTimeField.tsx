import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ToggleEvent } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Clock } from "lucide-react";
import {
  daysInMonth,
  formatIso,
  formatMoment,
  formatPattern,
  momentOf,
  parseIso,
  toIso,
  typedToIso,
  type DateKind,
  type Moment,
} from "../dateFormat";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const KIND_NOUN: Record<DateKind, string> = { date: "date", time: "time", datetime: "date and time" };

const pad = (n: number) => String(n).padStart(2, "0");
const dayKey = (year: number, month: number, day: number) => `${year}-${pad(month)}-${pad(day)}`;

/** A date, time or date-time input that shows its value in the portal's
 * standard display format (PORTAL_DATE_FORMAT & co. in config.js -- see
 * dateFormat.ts) instead of whatever the browser's locale would pick, with a
 * calendar / clock popover beside it. The value it holds and reports is always
 * ISO (2026-09-30, 08:30, 2026-09-30T08:30): the shape the API validates.
 *
 * Typing is forgiving -- any punctuation separates the parts, and a plain ISO
 * paste works -- and what can't be read is flagged (natively, so the surrounding
 * <form> refuses to submit it) rather than quietly dropped. */
export default function DateTimeField({
  kind,
  value,
  onChange,
  required = false,
  id,
  labelledBy,
}: {
  kind: DateKind;
  /** ISO text, or "" for nothing chosen. */
  value: string;
  onChange: (iso: string) => void;
  required?: boolean;
  id?: string;
  /** id of the element that labels this field, when it isn't inside a <label>. */
  labelledBy?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const editing = useRef(false);
  const [text, setText] = useState(() => formatIso(value, kind));
  const [blurred, setBlurred] = useState(false);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const popId = useId();

  // Follow the value when something other than typing changes it (a default
  // arriving, the picker) -- never while the person is mid-keystroke.
  useEffect(() => {
    if (!editing.current) setText(formatIso(value, kind));
  }, [value, kind]);

  const invalid = text.trim() !== "" && typedToIso(text, kind) === null;
  const pattern = formatPattern(kind);

  useEffect(() => {
    inputRef.current?.setCustomValidity(invalid ? `Enter a ${KIND_NOUN[kind]} like ${pattern}` : "");
  }, [invalid, kind, pattern]);

  function type(next: string) {
    editing.current = true;
    setBlurred(false);
    setText(next);
    onChange(next.trim() === "" ? "" : (typedToIso(next, kind) ?? ""));
  }

  function commit() {
    editing.current = false;
    setBlurred(true);
    const iso = typedToIso(text, kind);
    if (iso) {
      setText(formatIso(iso, kind));
      onChange(iso);
    }
  }

  // Just under the field. Runs before the popover is shown, so it never
  // appears somewhere else first; the layout effect below then corrects it
  // once its real size is known.
  function placeBelow() {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (rect) setPos({ top: rect.bottom + 6, left: rect.left });
  }

  // Keep the popover on screen: flip above the field when there's no room
  // below, and slide left when it would run off the right edge. Measured after
  // it has rendered, so it uses its real size.
  useLayoutEffect(() => {
    const pop = popRef.current;
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!open || !pop || !rect) return;
    const box = pop.getBoundingClientRect();
    const top = rect.bottom + 6 + box.height > window.innerHeight - 8 && rect.top - 6 - box.height > 8 ? rect.top - 6 - box.height : rect.bottom + 6;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - box.width - 8));
    setPos((p) => (p.top === top && p.left === left ? p : { top, left }));
  }, [open]);

  // A fixed-position popover doesn't follow its field when the page scrolls.
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (!popRef.current?.contains(e.target as Node)) popRef.current?.hidePopover();
    };
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const moment = parseIso(value, kind);

  function pick(next: Moment, closes: boolean) {
    editing.current = false;
    const iso = toIso(next, kind);
    setText(formatIso(iso, kind));
    onChange(iso);
    if (closes) {
      popRef.current?.hidePopover();
      inputRef.current?.focus();
    }
  }

  const TriggerIcon = kind === "time" ? Clock : CalendarDays;

  return (
    <div className="dt-field" ref={wrapRef}>
      <input
        ref={inputRef}
        id={id}
        type="text"
        className={`dt-input${invalid && blurred ? " dt-input-invalid" : ""}`}
        value={text}
        placeholder={pattern}
        required={required}
        autoComplete="off"
        spellCheck={false}
        aria-labelledby={labelledBy}
        aria-invalid={invalid && blurred ? true : undefined}
        onFocus={() => {
          editing.current = true;
        }}
        onChange={(e) => type(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && e.altKey) {
            e.preventDefault();
            popRef.current?.showPopover();
          }
        }}
      />
      <button
        type="button"
        className="dt-trigger"
        aria-label={`Choose ${KIND_NOUN[kind]}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={popId}
        // The platform's own toggle: a click on the trigger while the popover is
        // open closes it, instead of light-dismissing it and reopening it.
        popoverTarget={popId}
        popoverTargetAction="toggle"
      >
        <TriggerIcon size={16} aria-hidden="true" />
      </button>
      {invalid && blurred && (
        <span className="run-field-note run-field-note-warn" role="alert">
          Use {pattern}, e.g. {formatMoment(momentOf(new Date()), kind)}
        </span>
      )}
      <div
        ref={popRef}
        id={popId}
        // Top layer, light-dismiss (click outside, Escape) and no clipping by
        // the scrolling filter column it sits in -- all from the platform.
        popover="auto"
        role="dialog"
        aria-label={`Choose ${KIND_NOUN[kind]}`}
        className="dt-popover"
        style={{ top: pos.top, left: pos.left }}
        onBeforeToggle={(e: ToggleEvent<HTMLDivElement>) => {
          if (e.newState === "open") placeBelow();
        }}
        onToggle={(e: ToggleEvent<HTMLDivElement>) => setOpen(e.newState === "open")}
      >
        {open && (
          <>
            {kind !== "time" && <Calendar selected={moment} onPick={(day) => pick(withDay(moment, day), kind === "date")} />}
            {kind !== "date" && (
              <TimeEditor
                moment={moment ?? momentOf(new Date())}
                twelveHour={formatPattern(kind).includes("A")}
                onChange={(next) => pick(next, false)}
                separated={kind === "datetime"}
              />
            )}
            <div className="dt-foot">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => pick(momentOf(new Date()), kind === "date")}>
                {kind === "date" ? "Today" : "Now"}
              </button>
              {!required && value !== "" && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    editing.current = false;
                    setText("");
                    onChange("");
                    popRef.current?.hidePopover();
                  }}
                >
                  Clear
                </button>
              )}
              {kind !== "date" && (
                <button type="button" className="btn btn-sm dt-done" onClick={() => popRef.current?.hidePopover()}>
                  Done
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** `moment` with its calendar day replaced -- the time of day stays (or, with no
 * value yet, is the current time, so a date-time doesn't start at midnight). */
function withDay(moment: Moment | null, day: Pick<Moment, "year" | "month" | "day">): Moment {
  const base = moment ?? momentOf(new Date());
  return { ...base, year: day.year, month: day.month, day: day.day, second: moment ? base.second : 0 };
}

// --- calendar -------------------------------------------------------------------------

function Calendar({ selected, onPick }: { selected: Moment | null; onPick: (day: { year: number; month: number; day: number }) => void }) {
  const today = momentOf(new Date());
  const anchor = selected ?? today;
  const [view, setView] = useState({ year: anchor.year, month: anchor.month });
  // The day that holds the roving tab stop; arrow keys move it.
  const [focus, setFocus] = useState({ year: anchor.year, month: anchor.month, day: anchor.day });
  const gridRef = useRef<HTMLDivElement>(null);
  const moved = useRef(true); // focus the day on open, and after each arrow key

  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    gridRef.current?.querySelector<HTMLButtonElement>(`[data-day="${dayKey(focus.year, focus.month, focus.day)}"]`)?.focus();
  }, [focus, view]);

  function shift(months: number) {
    const total = view.year * 12 + (view.month - 1) + months;
    const year = Math.floor(total / 12);
    const month = (total % 12) + 1;
    setView({ year, month });
    setFocus((f) => ({ year, month, day: Math.min(f.day, daysInMonth(year, month)) }));
  }

  function onKeyDown(e: KeyboardEvent) {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (step !== undefined) {
      e.preventDefault();
      const d = new Date(focus.year, focus.month - 1, focus.day + step);
      moved.current = true;
      setFocus({ year: d.getFullYear(), month: d.getMonth() + 1, day: d.getDate() });
      setView({ year: d.getFullYear(), month: d.getMonth() + 1 });
    } else if (e.key === "PageUp" || e.key === "PageDown") {
      e.preventDefault();
      moved.current = true;
      shift(e.key === "PageUp" ? (e.shiftKey ? -12 : -1) : e.shiftKey ? 12 : 1);
    }
  }

  const leading = new Date(view.year, view.month - 1, 1).getDay();
  const cells = Array.from({ length: 42 }, (_, i) => new Date(view.year, view.month - 1, 1 - leading + i));

  return (
    <div className="dt-calendar">
      <div className="dt-cal-head">
        <button type="button" className="dt-nav" aria-label="Previous year" onClick={() => shift(-12)}>
          <ChevronsLeft size={15} aria-hidden="true" />
        </button>
        <button type="button" className="dt-nav" aria-label="Previous month" onClick={() => shift(-1)}>
          <ChevronLeft size={15} aria-hidden="true" />
        </button>
        <div className="dt-cal-title" aria-live="polite">
          <span>{MONTHS[view.month - 1]}</span> <span className="dt-cal-year">{view.year}</span>
        </div>
        <button type="button" className="dt-nav" aria-label="Next month" onClick={() => shift(1)}>
          <ChevronRight size={15} aria-hidden="true" />
        </button>
        <button type="button" className="dt-nav" aria-label="Next year" onClick={() => shift(12)}>
          <ChevronsRight size={15} aria-hidden="true" />
        </button>
      </div>
      <div className="dt-weekdays" aria-hidden="true">
        {WEEKDAYS.map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>
      <div className="dt-grid" ref={gridRef} role="grid" aria-label={`${MONTHS[view.month - 1]} ${view.year}`} onKeyDown={onKeyDown}>
        {cells.map((d) => {
          const year = d.getFullYear();
          const month = d.getMonth() + 1;
          const day = d.getDate();
          const key = dayKey(year, month, day);
          const isSelected = selected !== null && selected.year === year && selected.month === month && selected.day === day;
          const isToday = today.year === year && today.month === month && today.day === day;
          const isFocus = focus.year === year && focus.month === month && focus.day === day;
          return (
            <button
              key={key}
              type="button"
              role="gridcell"
              data-day={key}
              tabIndex={isFocus ? 0 : -1}
              aria-selected={isSelected}
              aria-current={isToday ? "date" : undefined}
              className={`dt-day${isSelected ? " is-selected" : ""}${isToday ? " is-today" : ""}${month !== view.month ? " is-outside" : ""}`}
              onClick={() => onPick({ year, month, day })}
            >
              {day}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// --- time -----------------------------------------------------------------------------

function TimeEditor({
  moment,
  twelveHour,
  onChange,
  separated,
}: {
  moment: Moment;
  twelveHour: boolean;
  onChange: (next: Moment) => void;
  separated: boolean;
}) {
  const shownHour = twelveHour ? (moment.hour % 12 === 0 ? 12 : moment.hour % 12) : moment.hour;
  const [hourText, setHourText] = useState(pad(shownHour));
  const [minuteText, setMinuteText] = useState(pad(moment.minute));

  useEffect(() => setHourText(pad(shownHour)), [shownHour]);
  useEffect(() => setMinuteText(pad(moment.minute)), [moment.minute]);

  function setHour(n: number) {
    const hour = twelveHour ? (n % 12) + (moment.hour >= 12 ? 12 : 0) : n;
    onChange({ ...moment, hour });
  }

  function field(label: string, text: string, setText: (t: string) => void, max: number, min: number, apply: (n: number) => void) {
    const commit = (raw: string) => {
      const n = Number(raw);
      if (raw !== "" && Number.isInteger(n) && n >= min && n <= max) apply(n);
    };
    return (
      <input
        type="text"
        inputMode="numeric"
        className="dt-time-input"
        aria-label={label}
        value={text}
        maxLength={2}
        onFocus={(e) => e.target.select()}
        onChange={(e) => {
          const next = e.target.value.replace(/\D/g, "");
          setText(next);
          commit(next);
        }}
        onBlur={() => setText(pad(Number(text) >= min && Number(text) <= max ? Number(text) : label === "Hour" ? shownHour : moment.minute))}
        onKeyDown={(e) => {
          if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
          e.preventDefault();
          const span = max - min + 1;
          const current = Number(text) >= min && Number(text) <= max ? Number(text) : min;
          apply(((current - min + (e.key === "ArrowUp" ? 1 : -1) + span) % span) + min);
        }}
      />
    );
  }

  return (
    <div className={`dt-time${separated ? " dt-time-separated" : ""}`}>
      <span className="dt-time-label">Time</span>
      <div className="dt-time-fields">
        {field("Hour", hourText, setHourText, twelveHour ? 12 : 23, twelveHour ? 1 : 0, setHour)}
        <span aria-hidden="true">:</span>
        {field("Minute", minuteText, setMinuteText, 59, 0, (n) => onChange({ ...moment, minute: n }))}
        {twelveHour && (
          <button
            type="button"
            className="dt-meridiem"
            aria-label="Toggle AM/PM"
            onClick={() => onChange({ ...moment, hour: (moment.hour + 12) % 24 })}
          >
            {moment.hour < 12 ? "AM" : "PM"}
          </button>
        )}
      </div>
    </div>
  );
}
