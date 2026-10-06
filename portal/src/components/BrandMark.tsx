import { branding } from "../branding";

// Inter-family cap height as a fraction of the font size -- used to
// center the monogram's lines vertically in the 40x40 viewBox.
const CAP_HEIGHT = 0.72;

/** 4+ letters stack onto two lines ("AKBI" -> "AK" / "BI") rather than
 * sitting in one row: a one-row 4-letter mark shrinks to ~7px in the
 * 28px mobile logo square, while two lines keep each letter at ~10px. */
function splitMark(mark: string): string[] {
  const chars = [...mark.toUpperCase()];
  if (chars.length <= 3) return [chars.join("")];
  const mid = Math.ceil(chars.length / 2);
  return [chars.slice(0, mid).join(""), chars.slice(mid).join("")];
}

/** The logo square's glyph when no PORTAL_LOGO_URL is configured. With
 * PORTAL_BRAND_MARK set (branding.mark) it draws that acronym as a
 * monogram; otherwise the neutral abstract dial/gauge -- not tied to any
 * one product's identity (the point of the default being generic, see
 * branding.ts), and one that doubles as the visual motif carried into the
 * Monitor page's meters. Both render in `currentColor`, so they inherit
 * whatever the surrounding badge sets. */
export default function BrandMark() {
  if (branding.mark) {
    const lines = splitMark(branding.mark);
    const longest = Math.max(...lines.map((l) => [...l].length));
    // ~0.68em average advance for bold caps; leave ~13 of the 40 units as margin.
    const fontSize = Math.min(lines.length === 1 ? 20 : 16, 27 / (longest * 0.68));
    const capH = fontSize * CAP_HEIGHT;
    const gap = lines.length === 1 ? 0 : 3;
    const firstBaseline = lines.length === 1 ? 20 + capH / 2 : 20 - gap / 2;
    return (
      <svg viewBox="0 0 40 40" width="100%" height="100%" aria-hidden="true">
        {lines.map((line, i) => (
          <text
            key={i}
            x="20"
            y={firstBaseline + i * (capH + gap)}
            textAnchor="middle"
            fill="currentColor"
            fontSize={fontSize}
            fontWeight={700}
            letterSpacing="0.02em"
          >
            {line}
          </text>
        ))}
      </svg>
    );
  }

  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.8" />
      <line x1="12" y1="12" x2="12" y2="4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="12" cy="12" r="2.1" fill="currentColor" />
    </svg>
  );
}
