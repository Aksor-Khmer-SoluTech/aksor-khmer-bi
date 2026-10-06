/** The rules for a report's code, mirrored from api/app/report_ref.py so the
 * forms can say what's wrong as you type. The server is the authority -- this is
 * a convenience, and a code that passes here can still be refused (taken). */

export const CODE_MIN = 3;
export const CODE_MAX = 64;

const CODE_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const ID_RE = /^[0-9a-f]{12}$/;
// Fixed path segments the reports API already uses (keep in sync with report_ref.RESERVED).
const RESERVED = new Set(["parse-template", "accessible", "batch-limits", "analytics"]);

/** Why `raw` can't be a report code, or null if it can (or is blank, meaning "none"). */
export function checkCode(raw: string): string | null {
  const code = raw.trim();
  if (code === "") return null;
  if (code.length < CODE_MIN || code.length > CODE_MAX) return `Use ${CODE_MIN}–${CODE_MAX} characters.`;
  if (!CODE_RE.test(code)) return "Lowercase letters, digits and single hyphens only — like revenue-comparison.";
  if (ID_RE.test(code)) return "That looks like a report ID — pick a code that isn't 12 hex characters.";
  if (RESERVED.has(code)) return `“${code}” is reserved.`;
  return null;
}

/** A code suggested from a display name: "Revenue Comparison" → "revenue-comparison".
 * Empty when nothing usable comes out (a Khmer-only title has no ASCII to keep). */
export function suggestCode(displayName: string): string {
  const code = displayName
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, CODE_MAX)
    .replace(/-+$/, "");
  return code && !checkCode(code) && code.length >= CODE_MIN ? code : "";
}

/** Is this API error about the code (taken / invalid), rather than something
 * else on the same request? Those belong against the field, not in a generic alert. */
export function isCodeError(status: number, message: string): boolean {
  return status === 409 || (status === 400 && /\bcode\b|report id|reserved/i.test(message));
}
