import { Fragment, isValidElement, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import {
  BookOpen,
  CalendarDays,
  ChevronRight,
  CircleHelp,
  Filter,
  GitBranch,
  Image as ImageIcon,
  Languages,
  LifeBuoy,
  Repeat,
  Search,
  Sheet,
  X,
  type LucideIcon,
} from "lucide-react";
import { ExternalLinkIcon } from "../admin/icons";
import { branding } from "../branding";
import { DEFAULT_DOC, DOCS, findDoc, loadDoc, type DocMeta } from "../docs/registry";
import { groupHits, parseSections, searchDocs, searchTerms, type SearchHit } from "../docs/search";
import { TOPICS, type TopicLink } from "../docs/topics";
import type { Route } from "../hooks";
import Code from "./Code";
import DocsHome from "./DocsHome";
import CopyButton from "./CopyButton";

function nodeText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return nodeText(node.props.children);
  return "";
}

/** Where a link written inside a guide should go. Other guides and their
 * headings stay in the portal; anything else in the repo (an example file, the
 * API source) opens on GitHub, since it isn't shipped with the portal. */
function resolveHref(href: string, slug: string): { href: string; external: boolean } {
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return { href, external: true };
  if (href.startsWith("#")) return { href: `#/docs/${slug}/${href.slice(1)}`, external: false };
  const url = new URL(href, "https://docs.invalid/docs/");
  const file = /^\/docs\/([^/]+)\.md$/.exec(url.pathname);
  const target = file && findDoc(file[1]);
  if (target) {
    return { href: `#/docs/${target.slug}${url.hash ? `/${url.hash.slice(1)}` : ""}`, external: false };
  }
  return { href: `${branding.repoUrl}/blob/main${url.pathname}${url.hash}`, external: true };
}

function markdownComponents(slug: string): Components {
  return {
    a({ href, children }) {
      if (!href) return <>{children}</>;
      const to = resolveHref(href, slug);
      return to.external ? (
        <a href={to.href} target="_blank" rel="noreferrer">
          {children}
        </a>
      ) : (
        <a href={to.href}>{children}</a>
      );
    },
    pre({ children }) {
      const code = isValidElement<{ className?: string; children?: ReactNode }>(children) ? children : null;
      const text = nodeText(code?.props.children).replace(/\n$/, "");
      const language = /language-(\w+)/.exec(code?.props.className ?? "")?.[1] ?? "text";
      return (
        <div className="doc-code">
          <CopyButton text={text} />
          <Code code={text} language={language} />
        </div>
      );
    },
    table({ children }) {
      return (
        <div className="doc-table">
          <table>{children}</table>
        </div>
      );
    },
  };
}

function Marked({ text, ranges }: { text: string; ranges: [number, number][] }) {
  const parts: ReactNode[] = [];
  let at = 0;
  ranges.forEach(([a, b], i) => {
    parts.push(text.slice(at, a), <mark key={i}>{text.slice(a, b)}</mark>);
    at = b;
  });
  parts.push(text.slice(at));
  return <>{parts.map((p, i) => <Fragment key={i}>{p}</Fragment>)}</>;
}

const TOPIC_ICON: Record<string, LucideIcon> = {
  Looping: Repeat,
  Conditions: GitBranch,
  Formatting: CalendarDays,
  "Missing data": CircleHelp,
  "Images, charts, codes": ImageIcon,
  "Excel and HTML": Sheet,
  "Khmer text and fonts": Languages,
  "Filters and data": Filter,
  "When it goes wrong": LifeBuoy,
};

type Flat = { key: string; open: () => void };

/** Topic links whose label holds every word of the query -- shown above the results as quick jumps. */
function matchingTopicLinks(query: string): (TopicLink & { topic: string })[] {
  const terms = searchTerms(query);
  if (!terms.length) return [];
  return TOPICS.flatMap((t) => t.links.map((l) => ({ ...l, topic: t.name }))).filter((l) => {
    const text = `${l.label} ${l.topic}`.toLowerCase();
    return terms.every((term) => text.includes(term));
  }).slice(0, 6);
}

const PER_GUIDE = 4;

/** Search results, grouped by guide (the guide with the best match first, a few results each, "Show more" for the
 * rest), with topic links that match on top. `selected` is the keyboard selection, an index into the flat order the
 * results are drawn in. */
function SearchResults({
  query,
  hits,
  selected,
  onOpenHit,
  onOpenLink,
  register,
}: {
  query: string;
  hits: SearchHit[] | null;
  selected: number;
  onOpenHit: (h: SearchHit) => void;
  onOpenLink: (l: TopicLink) => void;
  register: (items: Flat[]) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  useEffect(() => setExpanded(new Set()), [query]);
  const links = useMemo(() => matchingTopicLinks(query), [query]);
  const groups = useMemo(() => groupHits(hits ?? []), [hits]);

  const flat: Flat[] = [];
  links.forEach((l) => flat.push({ key: `topic:${l.slug}#${l.anchor}`, open: () => onOpenLink(l) }));
  const shown = groups.map((g) => ({ ...g, visible: expanded.has(g.slug) ? g.hits : g.hits.slice(0, PER_GUIDE) }));
  shown.forEach((g) => g.visible.forEach((h) => flat.push({ key: `${h.slug}#${h.sectionId}`, open: () => onOpenHit(h) })));
  useEffect(() => {
    register(flat);
  });
  const selectedKey = flat[selected]?.key;

  // Follow the keyboard selection -- not the first result's automatic one, which would move the page before it's been
  // put at the top.
  useEffect(() => {
    if (selected > 0 && selectedKey) document.querySelector(`[data-result-key="${CSS.escape(selectedKey)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selected, selectedKey]);

  const total = hits?.length ?? 0;
  return (
    <div className="docs-results" role="region" aria-live="polite" aria-label="Search results">
      <div className="docs-results-head">
        <h1>
          {hits === null ? "Searching…" : total === 0 ? `Nothing found for “${query}”` : `${total === 60 ? "60+" : total} result${total === 1 ? "" : "s"} for “${query}”`}
        </h1>
        {hits !== null && total > 0 && (
          <span className="docs-results-keys" aria-hidden="true">
            <kbd>↑</kbd>
            <kbd>↓</kbd> to move · <kbd>Enter</kbd> to open · <kbd>Esc</kbd> to go back
          </span>
        )}
      </div>
      {hits?.length === 0 && links.length === 0 && <p className="docs-empty-hint">Try fewer words, or a word from the guide's headings: <em>loop</em>, <em>date</em>, <em>image</em>, <em>filter</em>.</p>}

      {links.length > 0 && (
        <section className="docs-result-group">
          <h2 className="docs-result-guide">Topics</h2>
          <div className="docs-topic-hits">
            {links.map((l) => {
              const key = `topic:${l.slug}#${l.anchor}`;
              const Icon = TOPIC_ICON[l.topic] ?? BookOpen;
              return (
                <button key={key} type="button" data-result-key={key} className={`docs-topic-hit${key === selectedKey ? " selected" : ""}`} onClick={() => onOpenLink(l)}>
                  <Icon size={15} aria-hidden="true" />
                  <span>{l.label}</span>
                  <span className="docs-topic-hit-where">{l.topic}</span>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {shown.map((g) => (
        <section key={g.slug} className="docs-result-group">
          <h2 className="docs-result-guide">
            {g.docTitle} <span className="docs-result-count">{g.hits.length}</span>
          </h2>
          {g.visible.map((h) => {
            const key = `${h.slug}#${h.sectionId}`;
            return (
              <button key={key} type="button" data-result-key={key} className={`docs-result${key === selectedKey ? " selected" : ""}`} onClick={() => onOpenHit(h)}>
                <span className="docs-result-where">{h.heading}</span>
                <span className={`docs-result-snippet${h.inCode ? " code" : ""}`}>
                  <Marked text={h.snippet} ranges={h.ranges} />
                </span>
              </button>
            );
          })}
          {g.hits.length > g.visible.length && (
            <button type="button" className="docs-result-more" onClick={() => setExpanded((e) => new Set(e).add(g.slug))}>
              Show {g.hits.length - g.visible.length} more in {g.docTitle}
            </button>
          )}
        </section>
      ))}
    </div>
  );
}

const GROUPS: DocMeta["group"][] = ["Build reports", "Understand", "For administrators"];

/** The in-app documentation: a guide list + the open guide with an "On this
 * page" outline, or -- with no guide chosen -- the Docs home. The guides are the
 * repo's /docs/*.md (see docs/registry.ts), so this is the same text people read
 * on GitHub, rendered here with working cross-links and copyable code.
 *
 * Search takes over the article column: it starts at the top of the results (and
 * the guide's scroll position is put back when you leave it), hides the outline,
 * and is driven from the search box with ↑ ↓ Enter Esc. Opening a result scrolls
 * to its heading -- again once code blocks have laid out, so the page doesn't
 * land short -- and flashes it so you can see where you are. */
export default function DocsPage({ route, navigate }: { route: Extract<Route, { view: "docs" }>; navigate: (r: Route) => void }) {
  const home = !route.slug || !findDoc(route.slug);
  const slug = (route.slug && findDoc(route.slug)?.slug) || DEFAULT_DOC;
  const doc = findDoc(slug)!;
  const [loaded, setLoaded] = useState<{ slug: string; text: string } | { slug: string; error: true } | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [selected, setSelected] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const flatRef = useRef<Flat[]>([]);
  const savedScroll = useRef<number | null>(null);
  const [openTopic, setOpenTopic] = useState<string | null>(null);
  const searching = query.trim().length >= 2;

  const scroller = () => document.querySelector<HTMLElement>(".app-main");

  // Into search: start at the top of the results (where the guide was is saved as the query is typed, before any
  // result renders). Out of it (cleared, not by opening a result): put the guide back where it was.
  const wasSearching = useRef(false);
  function changeQuery(next: string) {
    if (!searching && next.trim().length >= 2) savedScroll.current = scroller()?.scrollTop ?? 0;
    setQuery(next);
  }
  useEffect(() => {
    if (searching && !wasSearching.current) {
      scroller()?.scrollTo({ top: 0 });
    } else if (!searching && wasSearching.current && savedScroll.current !== null) {
      // The guide is back in the DOM by the time effects run; no need to wait a frame (a background tab never gets one).
      scroller()?.scrollTo({ top: savedScroll.current });
      savedScroll.current = null;
    }
    wasSearching.current = searching;
  }, [searching]);

  useEffect(() => {
    setSelected(0);
    if (!searching) return setHits(null);
    let live = true;
    searchDocs(query, home ? "" : slug).then((r) => live && setHits(r)).catch(() => live && setHits([]));
    return () => {
      live = false;
    };
  }, [query, searching, slug, home]);

  // "/" jumps to the search box from anywhere on the page, like most docs sites.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) && !t.isContentEditable) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function leaveSearchFor(r: Route) {
    savedScroll.current = null; // going somewhere new, not back
    landed.current = null; // land even if it's the heading the address already names
    setQuery("");
    navigate(r);
  }
  const openHit = (hit: SearchHit) => leaveSearchFor({ view: "docs", slug: hit.slug, anchor: hit.sectionId });
  const openLink = (l: TopicLink) => leaveSearchFor({ view: "docs", slug: l.slug, anchor: l.anchor || undefined });

  useEffect(() => {
    if (home) return;
    let live = true;
    loadDoc(slug)
      .then((text) => live && setLoaded({ slug, text }))
      .catch(() => live && setLoaded({ slug, error: true }));
    return () => {
      live = false;
    };
  }, [slug, home]);

  const text = !home && loaded?.slug === slug && "text" in loaded ? loaded.text : null;
  const failed = !home && loaded?.slug === slug && "error" in loaded;
  const headings = useMemo(
    () => (text ? parseSections(text).filter((h) => h.level === 2 || h.level === 3).map((h) => ({ ...h, text: h.heading })) : []),
    [text],
  );
  const components = useMemo(() => markdownComponents(slug), [slug]);
  // FAQ answers on the home page link the way the FAQ guide itself does.
  const faqComponents = useMemo(() => markdownComponents("faq"), []);

  // Land on the requested heading once the text is in, otherwise at the top. Code blocks are highlighted after the
  // first paint and grow, which used to leave the page short of the heading -- so look again once they've settled,
  // unless the reader has started scrolling.
  // What was last landed on: leaving a search mustn't land on the address's heading again (it puts the guide back where
  // the reader was instead), so landing happens once per guide + heading.
  const landed = useRef<string | null>(null);
  useEffect(() => {
    document.title = home ? "Guides · Documentation" : `${doc.title} · Documentation`;
    if (searching) return;
    const key = home ? "home" : `${slug}#${route.anchor ?? ""}#${text ? "loaded" : ""}`;
    if (landed.current === key) return;
    landed.current = key;
    if (home) {
      if (savedScroll.current === null) scroller()?.scrollTo({ top: 0 });
      return;
    }
    if (!text) return;
    const target = route.anchor ? document.getElementById(route.anchor) : null;
    if (!target) {
      if (savedScroll.current === null) scroller()?.scrollTo({ top: 0 });
      return;
    }
    let userScrolled = false;
    const main = scroller();
    const stop = () => (userScrolled = true);
    main?.addEventListener("wheel", stop, { passive: true });
    main?.addEventListener("touchmove", stop, { passive: true });
    const land = () => !userScrolled && document.getElementById(route.anchor!)?.scrollIntoView({ block: "start" });
    land();
    const timers = [80, 300, 800].map((ms) => window.setTimeout(land, ms));
    setActiveId(route.anchor!); // a jump doesn't scroll past the headings in between, so the outline won't follow by itself
    document.querySelectorAll(".doc-landed").forEach((el) => el.classList.remove("doc-landed"));
    void target.offsetWidth; // restart the flash when the same heading is opened again
    target.classList.add("doc-landed");
    return () => {
      timers.forEach(clearTimeout);
      main?.removeEventListener("wheel", stop);
      main?.removeEventListener("touchmove", stop);
    };
  }, [text, route.anchor, doc.title, searching, home, slug]);

  // Highlight the section being read in the outline.
  useEffect(() => {
    if (!headings.length || searching) return;
    const seen = new Map<string, boolean>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) seen.set(e.target.id, e.isIntersecting);
        const first = headings.find((h) => seen.get(h.id));
        if (first) setActiveId(first.id);
      },
      { root: scroller(), rootMargin: "0px 0px -70% 0px" },
    );
    headings.forEach((h) => {
      const el = document.getElementById(h.id);
      if (el) io.observe(el);
    });
    return () => io.disconnect();
  }, [headings, searching]);

  function onSearchKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setQuery("");
      return;
    }
    if (!searching) return;
    const count = flatRef.current.length;
    if (e.key === "ArrowDown" && count) {
      e.preventDefault();
      setSelected((i) => Math.min(i + 1, count - 1));
    } else if (e.key === "ArrowUp" && count) {
      e.preventDefault();
      setSelected((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && count) {
      e.preventDefault();
      flatRef.current[Math.min(selected, count - 1)]?.open();
    }
  }

  return (
    <div className={`docs-page${searching || home ? " docs-page-wide" : ""}`}>
      <nav className={searching ? "docs-nav searching" : "docs-nav"} aria-label="Guides">
        <div className="search-icon-field docs-search">
          <Search size={16} className="search-icon" aria-hidden="true" />
          <input
            ref={searchRef}
            type="text"
            value={query}
            placeholder="Search guides"
            aria-label="Search the guides"
            onChange={(e) => changeQuery(e.target.value)}
            onKeyDown={onSearchKey}
          />
          {query ? (
            <button type="button" className="search-clear" onClick={() => setQuery("")} aria-label="Clear search">
              <X size={14} />
            </button>
          ) : (
            <kbd aria-hidden="true">/</kbd>
          )}
        </div>
        <div>
          <button
            type="button"
            className={`docs-nav-item docs-nav-home${home && !searching ? " active" : ""}`}
            aria-current={home ? "page" : undefined}
            onClick={() => leaveSearchFor({ view: "docs" })}
          >
            <BookOpen size={15} aria-hidden="true" /> Guides home
          </button>
        </div>
        <div className="docs-topics">
          <div className="docs-nav-group">By topic</div>
          {TOPICS.map((t) => {
            const open = openTopic === t.name;
            const Icon = TOPIC_ICON[t.name] ?? BookOpen;
            return (
              <div key={t.name}>
                <button
                  type="button"
                  className={`docs-nav-item docs-topic${open ? " open" : ""}`}
                  aria-expanded={open}
                  onClick={() => setOpenTopic(open ? null : t.name)}
                >
                  <Icon size={15} className="docs-topic-icon" aria-hidden="true" />
                  <span className="min-w-0 flex-1">{t.name}</span>
                  <ChevronRight size={14} className="docs-topic-caret" aria-hidden="true" />
                </button>
                {open && (
                  <div className="docs-topic-links">
                    {t.links.map((l) => (
                      <a key={l.label} className="docs-nav-item docs-topic-link" href={`#/docs/${l.slug}${l.anchor ? `/${l.anchor}` : ""}`} onClick={() => setQuery("")}>
                        {l.label}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {GROUPS.map((group) => (
          <div key={group}>
            <div className="docs-nav-group">{group}</div>
            {DOCS.filter((d) => d.group === group).map((d) => (
              <button
                key={d.slug}
                type="button"
                className={`docs-nav-item${!home && !searching && d.slug === slug ? " active" : ""}`}
                aria-current={!home && d.slug === slug ? "page" : undefined}
                onClick={() => leaveSearchFor({ view: "docs", slug: d.slug })}
              >
                {d.title}
              </button>
            ))}
          </div>
        ))}
      </nav>

      <article className="docs-article">
        {searching && (
          <SearchResults
            query={query.trim()}
            hits={hits}
            selected={selected}
            onOpenHit={openHit}
            onOpenLink={openLink}
            register={(items) => {
              flatRef.current = items;
            }}
          />
        )}
        {!searching && home && (
          <DocsHome
            onSearch={() => searchRef.current?.focus()}
            navigate={navigate}
            renderMarkdown={(answer) => (
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={faqComponents}>
                {answer}
              </ReactMarkdown>
            )}
          />
        )}
        {!searching && !home && failed && <p className="docs-error">Couldn't load this guide.</p>}
        {!searching && !home && !text && !failed && <div className="docs-loading" aria-busy="true" />}
        {!searching && text && (
          <div className="doc-prose">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={components}>
              {text}
            </ReactMarkdown>
          </div>
        )}
        {!searching && !home && (
          <a className="docs-github" href={`${branding.repoUrl}/blob/main/docs/${slug}.md`} target="_blank" rel="noreferrer">
            View on GitHub <ExternalLinkIcon />
          </a>
        )}
      </article>

      {!searching && !home && headings.length > 0 && (
        <aside className="docs-toc" aria-label="On this page">
          <div className="docs-nav-group">On this page</div>
          {headings.map((h) => (
            <a
              key={h.id}
              href={`#/docs/${slug}/${h.id}`}
              className={`docs-toc-item${h.level === 3 ? " sub" : ""}${h.id === activeId ? " active" : ""}`}
            >
              {h.text}
            </a>
          ))}
        </aside>
      )}
    </div>
  );
}
