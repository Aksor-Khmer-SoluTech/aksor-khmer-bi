import { Fragment, isValidElement, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import { Search, X } from "lucide-react";
import { ExternalLinkIcon } from "../admin/icons";
import { branding } from "../branding";
import { DEFAULT_DOC, DOCS, findDoc, loadDoc, type DocMeta } from "../docs/registry";
import { parseSections, searchDocs, type SearchHit } from "../docs/search";
import type { Route } from "../hooks";
import Code from "./Code";
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

function SearchResults({ query, hits, onOpen }: { query: string; hits: SearchHit[] | null; onOpen: (h: SearchHit) => void }) {
  return (
    <div className="docs-results" role="region" aria-live="polite" aria-label="Search results">
      <h1>{hits === null ? "Searching…" : `${hits.length === 40 ? "40+" : hits.length} result${hits.length === 1 ? "" : "s"} for “${query}”`}</h1>
      {hits?.length === 0 && <p className="docs-error">Nothing matched. Try fewer or different words.</p>}
      {hits?.map((h) => (
        <button key={`${h.slug}#${h.sectionId}`} type="button" className="docs-result" onClick={() => onOpen(h)}>
          <span className="docs-result-where">
            {h.docTitle} <span aria-hidden="true">›</span> {h.heading}
          </span>
          <span className="docs-result-snippet">
            <Marked text={h.snippet} ranges={h.ranges} />
          </span>
        </button>
      ))}
    </div>
  );
}

const GROUPS: DocMeta["group"][] = ["Build reports", "Understand", "For administrators"];

/** The in-app documentation: a guide list + the open guide with an "On this
 * page" outline. The guides are the repo's /docs/*.md (see docs/registry.ts),
 * so this is the same text people read on GitHub, rendered here with working
 * cross-links and copyable code. */
export default function DocsPage({ route, navigate }: { route: Extract<Route, { view: "docs" }>; navigate: (r: Route) => void }) {
  const slug = (route.slug && findDoc(route.slug)?.slug) || DEFAULT_DOC;
  const doc = findDoc(slug)!;
  const [loaded, setLoaded] = useState<{ slug: string; text: string } | { slug: string; error: true } | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const searching = query.trim().length >= 2;

  useEffect(() => {
    if (!searching) return setHits(null);
    let live = true;
    searchDocs(query, slug).then((r) => live && setHits(r)).catch(() => live && setHits([]));
    return () => {
      live = false;
    };
  }, [query, searching, slug]);

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

  function openHit(hit: SearchHit) {
    setQuery("");
    navigate({ view: "docs", slug: hit.slug, anchor: hit.sectionId });
  }

  useEffect(() => {
    let live = true;
    loadDoc(slug)
      .then((text) => live && setLoaded({ slug, text }))
      .catch(() => live && setLoaded({ slug, error: true }));
    return () => {
      live = false;
    };
  }, [slug]);

  const text = loaded?.slug === slug && "text" in loaded ? loaded.text : null;
  const failed = loaded?.slug === slug && "error" in loaded;
  const headings = useMemo(
    () => (text ? parseSections(text).filter((h) => h.level === 2 || h.level === 3).map((h) => ({ ...h, text: h.heading })) : []),
    [text],
  );
  const components = useMemo(() => markdownComponents(slug), [slug]);

  // Land on the requested heading once the text is in, otherwise at the top.
  useEffect(() => {
    document.title = `${doc.title} · Documentation`;
    if (!text || searching) return;
    const el = route.anchor ? document.getElementById(route.anchor) : null;
    if (el) el.scrollIntoView({ block: "start" });
    else document.querySelector(".app-main")?.scrollTo({ top: 0 });
  }, [text, route.anchor, doc.title, searching]);

  // Highlight the section being read in the outline.
  useEffect(() => {
    if (!headings.length) return;
    const seen = new Map<string, boolean>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) seen.set(e.target.id, e.isIntersecting);
        const first = headings.find((h) => seen.get(h.id));
        if (first) setActiveId(first.id);
      },
      { rootMargin: "0px 0px -70% 0px" },
    );
    headings.forEach((h) => {
      const el = document.getElementById(h.id);
      if (el) io.observe(el);
    });
    return () => io.disconnect();
  }, [headings]);

  return (
    <div className="docs-page">
      <nav className="docs-nav" aria-label="Guides">
        <div className="search-icon-field docs-search">
          <Search size={16} className="search-icon" aria-hidden="true" />
          <input
            ref={searchRef}
            type="text"
            value={query}
            placeholder="Search guides"
            aria-label="Search the guides"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setQuery("");
              if (e.key === "Enter" && hits?.[0]) openHit(hits[0]);
            }}
          />
          {query ? (
            <button type="button" className="search-clear" onClick={() => setQuery("")} aria-label="Clear search">
              <X size={14} />
            </button>
          ) : (
            <kbd aria-hidden="true">/</kbd>
          )}
        </div>
        {GROUPS.map((group) => (
          <div key={group}>
            <div className="docs-nav-group">{group}</div>
            {DOCS.filter((d) => d.group === group).map((d) => (
              <button
                key={d.slug}
                type="button"
                className={`docs-nav-item${d.slug === slug ? " active" : ""}`}
                aria-current={d.slug === slug ? "page" : undefined}
                onClick={() => navigate({ view: "docs", slug: d.slug })}
              >
                {d.title}
              </button>
            ))}
          </div>
        ))}
      </nav>

      <article className="docs-article">
        {searching && <SearchResults query={query.trim()} hits={hits} onOpen={openHit} />}
        {!searching && failed && <p className="docs-error">Couldn't load this guide.</p>}
        {!searching && !text && !failed && <div className="docs-loading" aria-busy="true" />}
        {!searching && text && (
          <div className="doc-prose">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={components}>
              {text}
            </ReactMarkdown>
          </div>
        )}
        <a className="docs-github" href={`${branding.repoUrl}/blob/main/docs/${slug}.md`} target="_blank" rel="noreferrer">
          View on GitHub <ExternalLinkIcon />
        </a>
      </article>

      {headings.length > 0 && (
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
