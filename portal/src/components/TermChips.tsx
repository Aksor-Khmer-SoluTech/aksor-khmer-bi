/** Terms as small tags -- the one place a set's contents are shown
 * read-only. Khmer face via `.terms-chip`. */
export default function TermChips({ terms, empty, muted = false }: { terms: string[]; empty?: string; muted?: boolean }) {
  if (terms.length === 0) return empty ? <p className="terms-empty">{empty}</p> : null;
  return (
    <ul className={`terms-chips${muted ? " terms-chips-muted" : ""}`}>
      {terms.map((t) => (
        <li key={t} className="terms-chip">
          {t}
        </li>
      ))}
    </ul>
  );
}
