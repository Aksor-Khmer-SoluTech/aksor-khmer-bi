// Shared by the protected-terms screens (Admin page, report tab).

// Mirrors api/app/protected_terms_config.py -- the server enforces these
// either way; knowing them here lets the form say so before a round trip.
export const MAX_TERMS = 1000;
export const MAX_TERM_LENGTH = 200;

/** Splits pasted text into terms: one per line (a spreadsheet column pastes
 * that way; a row pastes tab-separated). Spaces are *not* separators --
 * "ធនាគារ អេស៊ីលីដា" is one term -- and neither are commas, which real names
 * contain. Cleaned the way the server cleans them: trimmed, blanks dropped,
 * repeats collapsed (first occurrence wins). */
export function parseTerms(text: string): string[] {
  const seen = new Set<string>();
  const terms: string[] = [];
  for (const piece of text.split(/[\r\n\t]+/)) {
    const term = piece.trim();
    if (!term || seen.has(term)) continue;
    seen.add(term);
    terms.push(term);
  }
  return terms;
}
