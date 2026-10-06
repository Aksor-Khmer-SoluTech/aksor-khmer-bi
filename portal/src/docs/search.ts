import GithubSlugger from "github-slugger";
import { DOCS, loadDoc } from "./registry";

export type Section = {
  /** Same id rehype-slug gives the rendered heading, so it works as a deep link. */
  id: string;
  heading: string;
  level: number;
  /** Plain text under the heading, up to the next heading. */
  body: string;
};

const stripInline = (s: string) =>
  s
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`/g, "")
    .replace(/[*_]/g, "")
    .replace(/\\\|/g, "|");

/** Splits a guide into heading-delimited sections (headings inside code fences
 * don't count). Every level is slugged, in order, because duplicate heading
 * names get -1/-2 suffixes counted across the whole document. */
export function parseSections(markdown: string): Section[] {
  const slugger = new GithubSlugger();
  const sections: Section[] = [{ id: "", heading: "", level: 1, body: "" }];
  let fenced = false;
  for (const line of markdown.split("\n")) {
    if (/^```/.test(line)) fenced = !fenced;
    const m = !fenced && /^(#{1,6})\s+(.+?)\s*#*$/.exec(line);
    if (m) {
      const heading = stripInline(m[2]);
      sections.push({ id: slugger.slug(heading), heading, level: m[1].length, body: "" });
    } else if (!/^\|[-|: ]+\|$/.test(line.trim())) {
      sections[sections.length - 1].body += stripInline(line) + "\n";
    }
  }
  return sections.filter((s) => s.heading);
}

export type SearchHit = {
  slug: string;
  docTitle: string;
  sectionId: string;
  heading: string;
  /** Text around the first match; `ranges` are [start, end) offsets into it to highlight. */
  snippet: string;
  ranges: [number, number][];
  score: number;
};

type IndexedSection = Section & { slug: string; docTitle: string };

let index: Promise<IndexedSection[]> | null = null;

/** Loads and parses every guide once, on first search. */
function buildIndex(): Promise<IndexedSection[]> {
  index ??= Promise.all(
    DOCS.map(async (d) =>
      parseSections(await loadDoc(d.slug)).map((s) => ({ ...s, slug: d.slug, docTitle: d.title })),
    ),
  ).then((all) => all.flat());
  index.catch(() => (index = null));
  return index;
}

function highlight(text: string, terms: string[]): { snippet: string; ranges: [number, number][] } {
  const lower = text.toLowerCase();
  const first = Math.min(...terms.map((t) => lower.indexOf(t)).filter((i) => i >= 0));
  const flat = (s: string) => s.replace(/\s+/g, " ");
  const start = Math.max(0, (Number.isFinite(first) ? first : 0) - 60);
  const raw = text.slice(start, start + 200);
  const snippet = (start > 0 ? "…" : "") + flat(raw).trim() + (start + 200 < text.length ? "…" : "");
  const sl = snippet.toLowerCase();
  const ranges: [number, number][] = [];
  for (const t of terms) {
    for (let i = sl.indexOf(t); i >= 0; i = sl.indexOf(t, i + t.length)) ranges.push([i, i + t.length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  // Merge overlaps so the renderer can walk the ranges in order.
  const merged: [number, number][] = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([...r]);
  }
  return { snippet, ranges: merged };
}

/** Every word typed must appear in the section (heading or text); heading hits
 * rank first, then the open guide, then document order. */
export async function searchDocs(query: string, currentSlug: string): Promise<SearchHit[]> {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const hits: SearchHit[] = [];
  for (const s of await buildIndex()) {
    const heading = s.heading.toLowerCase();
    const body = s.body.toLowerCase();
    if (!terms.every((t) => heading.includes(t) || body.includes(t))) continue;
    const inHeading = terms.filter((t) => heading.includes(t)).length;
    const text = s.body.trim() || s.heading;
    hits.push({
      slug: s.slug,
      docTitle: s.docTitle,
      sectionId: s.id,
      heading: s.heading,
      ...highlight(text, terms),
      score: inHeading * 10 + (s.slug === currentSlug ? 5 : 0) + (heading === terms.join(" ") ? 20 : 0),
    });
  }
  return hits.sort((a, b) => b.score - a.score).slice(0, 40);
}
