import GithubSlugger from "github-slugger";
import { DOCS, loadDoc } from "./registry";

export type Section = {
  /** Same id rehype-slug gives the rendered heading, so it works as a deep link. */
  id: string;
  heading: string;
  level: number;
  /** Plain text under the heading, up to the next heading -- code included (what search matches). */
  body: string;
  /** The same without code blocks, and tables read as "cell · cell" -- what a result's snippet shows. */
  prose: string;
};

/** A table row's cells: split on | that isn't escaped (\|) or inside `code`. */
function cells(row: string): string[] {
  const out: string[] = [];
  let cell = "";
  let code = false;
  for (let i = 0; i < row.length; i++) {
    const ch = row[i];
    if (ch === "`") code = !code;
    if (ch === "|" && !code && row[i - 1] !== "\\") {
      out.push(cell.trim());
      cell = "";
    } else cell += ch;
  }
  out.push(cell.trim());
  return out.filter(Boolean);
}

/** A line as a person reads it: a table row's cells joined with " · ", list markers and quote marks dropped. */
const readable = (line: string) =>
  line
    .replace(/^\s*\|(.*)\|\s*$/, (_, row: string) => cells(row).join(" · "))
    .replace(/^\s*(?:[-*+]|\d+\.)\s+(\[[ x]\]\s+)?/, "")
    .replace(/^\s*>\s?/, "");

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
  const sections: Section[] = [{ id: "", heading: "", level: 1, body: "", prose: "" }];
  let fenced = false;
  for (const line of markdown.split("\n")) {
    const fence = /^```/.test(line);
    if (fence) fenced = !fenced;
    const m = !fenced && !fence && /^(#{1,6})\s+(.+?)\s*#*$/.exec(line);
    if (m) {
      const heading = stripInline(m[2]);
      sections.push({ id: slugger.slug(heading), heading, level: m[1].length, body: "", prose: "" });
    } else if (!/^\|[-|: ]+\|$/.test(line.trim())) {
      const section = sections[sections.length - 1];
      const plain = stripInline(line);
      section.body += plain + "\n";
      if (!fenced && !fence) section.prose += stripInline(readable(line)) + "\n";
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
  /** The match is only in a code example, so the snippet is code. */
  inCode: boolean;
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

const STOP = new Set(["a", "an", "the", "to", "of", "in", "on", "for", "and", "or", "how", "do", "i", "is", "with", "my"]);

/** Crude English stemming, enough to make "formatting", "formatted" and "formats" all find "format", and "dates" find
 * "date". Matching is by substring of the stem, so it also finds "formatting" from a typed "format". */
export function stem(word: string): string {
  let w = word.toLowerCase();
  if (w.length > 4) w = w.replace(/(ing|ed|es|er|s)$/, "");
  return w.replace(/([^aeiou])\1$/, "$1");
}

/** The words that count in a query: no filler words, each reduced to its stem. */
export function searchTerms(query: string): string[] {
  const words = query.toLowerCase().split(/[^\p{L}\p{N}_.:{}\[\]-]+/u).filter(Boolean);
  const content = words.filter((w) => !STOP.has(w));
  return [...new Set((content.length ? content : words).map(stem))];
}

function highlight(text: string, terms: string[]): { snippet: string; ranges: [number, number][] } {
  const lower = text.toLowerCase();
  // Centre the snippet on the first place two or more terms sit close together, else on the first hit.
  const spots = terms.flatMap((t) => [...lower.matchAll(new RegExp(escapeRe(t), "g"))].map((m) => m.index!));
  spots.sort((a, b) => a - b);
  const close = spots.find((p, i) => i + 1 < spots.length && spots[i + 1] - p < 120);
  const first = close ?? spots[0] ?? 0;
  const flat = (s: string) => s.replace(/\s+/g, " ");
  const start = Math.max(0, first - 60);
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

const escapeRe = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** How often `term` starts a word in `text` (so "qr" finds "qrcode" but not "sqrt"). */
function count(text: string, term: string): number {
  return text.match(new RegExp(`(?<![\\p{L}\\p{N}])${escapeRe(term)}`, "gu"))?.length ?? 0;
}

/** Words are matched by stem, so "formatting dates" finds "format … date". A section needs most of the words (all of
 * them for one or two words, otherwise about two thirds), and the more it has the higher it ranks: every word beats
 * some words, then heading hits, then the exact phrase, then the open guide, then document order. */
export async function searchDocs(query: string, currentSlug: string): Promise<SearchHit[]> {
  const terms = searchTerms(query);
  if (!terms.length) return [];
  const needed = terms.length <= 2 ? terms.length : Math.ceil(terms.length * 0.67);
  const phrase = query.trim().toLowerCase();
  const hits: SearchHit[] = [];
  for (const s of await buildIndex()) {
    const heading = s.heading.toLowerCase();
    const body = s.body.toLowerCase();
    const inHeading = terms.filter((t) => count(heading, t) > 0).length;
    const counts = terms.map((t) => count(body, t));
    const matched = terms.filter((t, i) => counts[i] > 0 || count(heading, t) > 0).length;
    if (matched < needed) continue;
    // Show prose when the words are in it; a match only inside a code example shows that code.
    const prose = s.prose.toLowerCase();
    const inProse = terms.some((t) => count(prose, t) > 0);
    const inCode = !inProse && counts.some((c) => c > 0) && inHeading === 0;
    const text = (inCode ? s.body : s.prose).trim() || s.heading;
    hits.push({
      slug: s.slug,
      docTitle: s.docTitle,
      sectionId: s.id,
      heading: s.heading,
      ...highlight(text, terms),
      inCode,
      score:
        matched * 100 +
        inHeading * 10 +
        counts.reduce((sum, c) => sum + Math.min(c, 5), 0) * 2 +
        (s.slug === currentSlug ? 5 : 0) +
        (heading.includes(phrase) ? 30 : body.includes(phrase) ? 15 : 0),
    });
  }
  return hits.sort((a, b) => b.score - a.score).slice(0, 60);
}

export type HitGroup = { slug: string; docTitle: string; hits: SearchHit[]; best: number };

/** Hits grouped by guide, the guide with the best hit first; within a guide, best first. */
export function groupHits(hits: SearchHit[]): HitGroup[] {
  const groups = new Map<string, HitGroup>();
  for (const h of hits) {
    const g = groups.get(h.slug) ?? { slug: h.slug, docTitle: h.docTitle, hits: [], best: h.score };
    g.hits.push(h);
    g.best = Math.max(g.best, h.score);
    groups.set(h.slug, g);
  }
  return [...groups.values()].sort((a, b) => b.best - a.best);
}
