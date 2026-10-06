// Client-side mirror of api/app/security.py's password policy -- there so a
// person finds out *before* submitting, never instead of the server's own
// check (which is the one that counts).

export const MIN_PASSWORD_LENGTH = 8;
const MAX_PASSWORD_LENGTH = 72;

export const PASSWORD_HINT = `At least ${MIN_PASSWORD_LENGTH} characters, using standard keyboard characters only (no accents or Khmer script — the sign-in header can't carry them).`;

/** Null when `password` is acceptable, else the reason it isn't. */
export function passwordProblem(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (password.length > MAX_PASSWORD_LENGTH) return `Password must be at most ${MAX_PASSWORD_LENGTH} characters.`;
  if (!/^[\x20-\x7e]+$/.test(password)) {
    return "Password may only use standard keyboard characters (no accents or non-Latin scripts).";
  }
  return null;
}

// No 0/O, 1/l/I -- same alphabet as the server's generator.
const ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";

/** A random 16-character password (crypto-strength, unbiased) with at least
 * one lower-case letter, upper-case letter and digit. */
export function generatePassword(length = 16): string {
  // Rejection sampling: 256 isn't a multiple of the alphabet size, so a bare
  // modulo would favour the first few characters.
  const limit = 256 - (256 % ALPHABET.length);
  for (;;) {
    let out = "";
    while (out.length < length) {
      const bytes = crypto.getRandomValues(new Uint8Array(length));
      for (const b of bytes) {
        if (b < limit && out.length < length) out += ALPHABET[b % ALPHABET.length];
      }
    }
    if (/[a-z]/.test(out) && /[A-Z]/.test(out) && /[0-9]/.test(out)) return out;
  }
}
