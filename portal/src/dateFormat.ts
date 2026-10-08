// The portal's standard display formats for dates, times and date-times --
// how a value reads to the person looking at it, chosen once per deployment in
// public/config.js (loaded before the bundle, so it can be changed on a running
// instance without a rebuild -- same mechanism as PORTAL_API_BASE_URL). The
// API has no say in it, on purpose: what a report *contains* is decided by the
// template and the data; how the portal's own screens show a date is a
// presentation choice of whoever runs the portal.
//
// A format is text with these tokens; everything else is copied as is:
//
//   YYYY  4-digit year         YY  2-digit year (2000-2099)
//   MM    month, 01-12         DD  day of month, 01-31
//   HH    hour, 00-23          hh  hour, 01-12 (needs A)
//   mm    minute, 00-59        ss  second, 00-59
//   A     AM / PM
//
// so PORTAL_DATE_FORMAT = "DD/MM/YYYY", PORTAL_TIME_FORMAT = "hh:mm A",
// PORTAL_DATETIME_FORMAT = "DD MM YYYY, HH:mm". Values are always *stored* and
// sent to the API in ISO form (2026-09-30, 08:30, 2026-09-30T08:30) -- the shape
// the server validates -- and only ever *shown* in these formats.
declare global {
  interface Window {
    PORTAL_DATE_FORMAT?: string;
    PORTAL_TIME_FORMAT?: string;
    PORTAL_DATETIME_FORMAT?: string;
  }
}

export type DateKind = "date" | "time" | "datetime";

export const DEFAULT_DATE_FORMAT = "DD/MM/YYYY";
export const DEFAULT_TIME_FORMAT = "HH:mm";

const TOKEN_RE = /(YYYY|YY|MM|DD|HH|hh|mm|ss|A)/;
const IS_TOKEN_RE = /^(YYYY|YY|MM|DD|HH|hh|mm|ss|A)$/;

type Token = "YYYY" | "YY" | "MM" | "DD" | "HH" | "hh" | "mm" | "ss" | "A";

interface Compiled {
  source: string;
  /** Alternating literals and tokens, in order. */
  parts: { literal?: string; token?: Token }[];
  has: Set<Token>;
  /** Matches a typed value; capture groups are the tokens, in order. */
  matcher: RegExp;
  tokens: Token[];
}

function compile(format: string): Compiled {
  const parts = format
    .split(TOKEN_RE)
    .filter((p) => p !== "")
    .map((p) => (IS_TOKEN_RE.test(p) ? { token: p as Token } : { literal: p }));
  const tokens = parts.flatMap((p) => (p.token ? [p.token] : []));
  const pattern = parts
    .map((p) => {
      if (p.token) return p.token === "YYYY" ? "(\\d{4})" : p.token === "A" ? "([AaPp][Mm])" : "(\\d{1,2})";
      // Punctuation and spaces are interchangeable while typing (30-09-2026,
      // 30.09.2026); a literal with letters in it ("T", "at") must match.
      return /^[^\p{L}\p{N}]+$/u.test(p.literal!) ? "[^\\p{L}\\p{N}]+" : p.literal!.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("");
  return { source: format, parts, has: new Set(tokens), matcher: new RegExp(`^${pattern}$`, "iu"), tokens };
}

function valid(format: string | undefined, kind: DateKind): Compiled | null {
  if (!format?.trim()) return null;
  const c = compile(format.trim());
  const hasDate = c.has.has("MM") && c.has.has("DD") && (c.has.has("YYYY") || c.has.has("YY"));
  const hasTime = (c.has.has("HH") || (c.has.has("hh") && c.has.has("A"))) && c.has.has("mm");
  const noDate = !c.has.has("MM") && !c.has.has("DD") && !c.has.has("YYYY") && !c.has.has("YY");
  const noTime = !c.has.has("HH") && !c.has.has("hh") && !c.has.has("mm") && !c.has.has("ss") && !c.has.has("A");
  const once = c.tokens.length === c.has.size;
  const ok = once && (kind === "date" ? hasDate && noTime : kind === "time" ? hasTime && noDate : hasDate && hasTime);
  return ok ? c : null;
}

function configured(kind: DateKind, raw: string | undefined, fallback: string): Compiled {
  const c = valid(raw, kind);
  if (c) return c;
  if (raw?.trim()) console.warn(`PORTAL_${kind.toUpperCase()}_FORMAT ${JSON.stringify(raw)} isn't a usable ${kind} format; using ${fallback}`);
  return valid(fallback, kind)!;
}

const dateFmt = configured("date", window.PORTAL_DATE_FORMAT, DEFAULT_DATE_FORMAT);
const timeFmt = configured("time", window.PORTAL_TIME_FORMAT, DEFAULT_TIME_FORMAT);
// Unset: the date format, a space, the time format -- so setting the two
// halves is enough for most deployments.
const datetimeFmt = configured("datetime", window.PORTAL_DATETIME_FORMAT, `${dateFmt.source} ${timeFmt.source}`);

const FORMATS: Record<DateKind, Compiled> = { date: dateFmt, time: timeFmt, datetime: datetimeFmt };

/** The pattern shown to people ("DD/MM/YYYY") as a placeholder and in hints. */
export function formatPattern(kind: DateKind): string {
  return FORMATS[kind].source;
}

// --- values ---------------------------------------------------------------------

export interface Moment {
  year: number;
  month: number; // 1-12
  day: number;
  hour: number;
  minute: number;
  second: number;
}

const pad = (n: number, width = 2) => String(n).padStart(width, "0");

export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** ISO text (2026-09-30 / 08:30[:15] / 2026-09-30T08:30[:15]) -> its parts, or null. */
export function parseIso(text: string, kind: DateKind): Moment | null {
  const m =
    kind === "date"
      ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
      : kind === "time"
        ? /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(text)
        : /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(text);
  if (!m) return null;
  const n = m.slice(1).map((x) => (x === undefined ? 0 : Number(x)));
  const moment: Moment =
    kind === "date"
      ? { year: n[0], month: n[1], day: n[2], hour: 0, minute: 0, second: 0 }
      : kind === "time"
        ? { year: 2000, month: 1, day: 1, hour: n[0], minute: n[1], second: n[2] }
        : { year: n[0], month: n[1], day: n[2], hour: n[3], minute: n[4], second: n[5] };
  return real(moment) ? moment : null;
}

function real(m: Moment): boolean {
  return (
    m.year >= 1 && m.month >= 1 && m.month <= 12 && m.day >= 1 && m.day <= daysInMonth(m.year, m.month) &&
    m.hour >= 0 && m.hour <= 23 && m.minute >= 0 && m.minute <= 59 && m.second >= 0 && m.second <= 59
  );
}

/** Parts -> ISO text of `kind`, the shape the API takes. Seconds are only
 * carried when the display format shows them, so the value a person sees is
 * the value that's sent. */
export function toIso(m: Moment, kind: DateKind): string {
  const date = `${pad(m.year, 4)}-${pad(m.month)}-${pad(m.day)}`;
  const time = `${pad(m.hour)}:${pad(m.minute)}${FORMATS[kind].has.has("ss") ? `:${pad(m.second)}` : ""}`;
  return kind === "date" ? date : kind === "time" ? time : `${date}T${time}`;
}

/** Parts -> text in the portal's display format for `kind`. */
export function formatMoment(m: Moment, kind: DateKind): string {
  return FORMATS[kind].parts
    .map((p) => {
      switch (p.token) {
        case undefined:
          return p.literal;
        case "YYYY":
          return pad(m.year, 4);
        case "YY":
          return pad(m.year % 100);
        case "MM":
          return pad(m.month);
        case "DD":
          return pad(m.day);
        case "HH":
          return pad(m.hour);
        case "hh":
          return pad(m.hour % 12 === 0 ? 12 : m.hour % 12);
        case "mm":
          return pad(m.minute);
        case "ss":
          return pad(m.second);
        case "A":
          return m.hour < 12 ? "AM" : "PM";
      }
    })
    .join("");
}

/** ISO text -> how the portal shows it. Text that isn't ISO comes back as is,
 * so a value the server sent in some other shape is still readable. */
export function formatIso(iso: string, kind: DateKind): string {
  const m = parseIso(iso, kind);
  return m ? formatMoment(m, kind) : iso;
}

/** What a person typed -> parts, or null when it isn't a real date/time in the
 * display format. Plain ISO is always accepted too (paste-friendly). */
export function parseTyped(text: string, kind: DateKind): Moment | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const iso = parseIso(trimmed, kind);
  if (iso) return iso;

  const c = FORMATS[kind];
  const match = c.matcher.exec(trimmed);
  if (!match) return null;
  const moment: Moment = { year: 2000, month: 1, day: 1, hour: 0, minute: 0, second: 0 };
  let meridiem: "AM" | "PM" | null = null;
  let twelveHour: number | null = null;
  c.tokens.forEach((token, i) => {
    const value = match[i + 1];
    const n = Number(value);
    if (token === "YYYY") moment.year = n;
    else if (token === "YY") moment.year = 2000 + n;
    else if (token === "MM") moment.month = n;
    else if (token === "DD") moment.day = n;
    else if (token === "HH") moment.hour = n;
    else if (token === "hh") twelveHour = n;
    else if (token === "mm") moment.minute = n;
    else if (token === "ss") moment.second = n;
    else meridiem = value.toUpperCase() as "AM" | "PM";
  });
  if (twelveHour !== null) {
    if (twelveHour < 1 || twelveHour > 12) return null;
    moment.hour = (twelveHour % 12) + (meridiem === "PM" ? 12 : 0);
  }
  return real(moment) ? moment : null;
}

/** Typed text -> ISO, or null. */
export function typedToIso(text: string, kind: DateKind): string | null {
  const m = parseTyped(text, kind);
  return m ? toIso(m, kind) : null;
}

// --- "now" ------------------------------------------------------------------------

export function momentOf(d: Date): Moment {
  return { year: d.getFullYear(), month: d.getMonth() + 1, day: d.getDate(), hour: d.getHours(), minute: d.getMinutes(), second: d.getSeconds() };
}

/** The value of a `now()` default of this kind, from the viewer's own clock. */
export function nowIso(kind: DateKind, now: Date = new Date()): string {
  return toIso(momentOf(now), kind);
}

/** The `now()` a manager writes for a date, time or datetime default. */
export const NOW_EXPRESSION = "now()";

/** The first / last day of the month a date or datetime default is read in. */
export const FIRST_DAY_EXPRESSION = "firstDayOfMonth()";
export const LAST_DAY_EXPRESSION = "lastDayOfMonth()";

/** What a run-form field starts with: the parameter's default, with `now()`,
 * `firstDayOfMonth()` and `lastDayOfMonth()` read from the viewer's clock, or ""
 * when it has none. A datetime takes 00:00 on the first day and 23:59 on the last. */
export function initialValue(type: string, defaultValue: string | null | undefined, now: Date = new Date()): string {
  if (!defaultValue) return "";
  if (defaultValue === NOW_EXPRESSION) return type === "date" || type === "time" || type === "datetime" ? nowIso(type, now) : "";
  if (defaultValue === FIRST_DAY_EXPRESSION || defaultValue === LAST_DAY_EXPRESSION) {
    if (type !== "date" && type !== "datetime") return "";
    const first = defaultValue === FIRST_DAY_EXPRESSION;
    const day = first ? 1 : new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    return toIso({ year: now.getFullYear(), month: now.getMonth() + 1, day, hour: first ? 0 : 23, minute: first ? 0 : 59, second: 0 }, type);
  }
  return defaultValue;
}
