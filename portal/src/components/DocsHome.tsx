import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowRight,
  BookOpen,
  CalendarClock,
  ChevronDown,
  Database,
  FileOutput,
  FilePen,
  Languages,
  Rocket,
  Search,
  Server,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { parseFaq, type FaqCategory, type FaqItem } from "../docs/faq";
import { DOCS, loadDoc, type DocMeta } from "../docs/registry";
import { TOPICS } from "../docs/topics";
import type { Route } from "../hooks";

/** The Guides home (#/docs): a search box, the questions people ask most -- from docs/faq.md, by category, each
 * opening in place -- then the recipes by topic and the guides themselves. */

const CATEGORY_ICON: Record<string, LucideIcon> = {
  "Getting started": Rocket,
  "Writing templates": FilePen,
  "Khmer text and fonts": Languages,
  "Data, filters and datasets": Database,
  "Output: PDF, Excel and big reports": FileOutput,
  "Schedules and email": CalendarClock,
  "Sign-in and access": ShieldCheck,
  "Running the server": Server,
};

// Asked often enough to sit right under the search box. Matched by question text, so a reworded one just drops out.
const POPULAR = [
  "How do I repeat a table row for every item?",
  "A Khmer word is split in the wrong place. How do I fix it?",
  "How do I let a branch see only its own data?",
  "Can the result be emailed?",
  "My report has thousands of rows. What happens?",
];

const GROUPS: DocMeta["group"][] = ["Build reports", "Understand", "For administrators"];
const ALL = "All questions";

function QuestionCard({
  item,
  number,
  open,
  onToggle,
  renderMarkdown,
}: {
  item: FaqItem;
  number: number;
  open: boolean;
  onToggle: () => void;
  renderMarkdown: (text: string) => ReactNode;
}) {
  return (
    <div className={`faq-card${open ? " open" : ""}`} id={`faq-${item.id}`}>
      <button type="button" className="faq-q" aria-expanded={open} aria-controls={`faq-a-${item.id}`} onClick={onToggle}>
        <span className="faq-num" aria-hidden="true">
          {String(number).padStart(2, "0")}
        </span>
        <span className="faq-q-text">{item.question}</span>
        <ChevronDown size={17} className="faq-caret" aria-hidden="true" />
      </button>
      <div className="faq-a-wrap" id={`faq-a-${item.id}`} role="region" aria-label={item.question} hidden={!open}>
        <div className="faq-a doc-prose">{renderMarkdown(item.answer)}</div>
      </div>
    </div>
  );
}

export default function DocsHome({
  onSearch,
  navigate,
  renderMarkdown,
}: {
  onSearch: () => void;
  navigate: (r: Route) => void;
  renderMarkdown: (text: string) => ReactNode;
}) {
  const [faq, setFaq] = useState<FaqCategory[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [category, setCategory] = useState(ALL);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadDoc("faq")
      .then((text) => setFaq(parseFaq(text)))
      .catch(() => setFailed(true));
  }, []);

  const total = faq?.reduce((n, c) => n + c.items.length, 0) ?? 0;
  const recipes = TOPICS.reduce((n, t) => n + t.links.length, 0);
  const guides = DOCS.filter((d) => d.slug !== "faq");
  const popular = useMemo(
    () =>
      POPULAR.flatMap((q) => {
        for (const c of faq ?? []) {
          const item = c.items.find((i) => i.question === q);
          if (item) return [{ item, category: c.name }];
        }
        return [];
      }),
    [faq],
  );
  // Numbered across the whole FAQ, so "07" is the same question whichever category is showing.
  const numberOf = useMemo(() => {
    const map = new Map<string, number>();
    let n = 0;
    for (const c of faq ?? []) for (const i of c.items) map.set(i.id, ++n);
    return map;
  }, [faq]);
  const shown = (faq ?? []).filter((c) => category === ALL || c.name === category);

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function jumpTo(item: FaqItem, inCategory: string) {
    setCategory(inCategory);
    setOpen((prev) => new Set(prev).add(item.id));
    // After the category's list has rendered.
    window.setTimeout(() => document.getElementById(`faq-${item.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 30);
  }

  function pick(name: string) {
    setCategory(name);
    listRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  return (
    <div className="docs-home">
      <header className="dh-hero">
        <span className="dh-hero-mark" aria-hidden="true">
          អក្សរ
        </span>
        <p className="dh-eyebrow">Guides &amp; answers</p>
        <h1>
          Ask a question,
          <br />
          <em>build the report.</em>
        </h1>
        <p className="dh-lede">How to build reports with Khmer that prints right — answers first, the full guides when you want the detail.</p>
        <button type="button" className="docs-home-search" onClick={onSearch}>
          <Search size={17} aria-hidden="true" />
          <span>Search every guide and answer — try “date”, “QR code”, “email”</span>
          <kbd aria-hidden="true">/</kbd>
        </button>
        {popular.length > 0 && (
          <div className="dh-popular">
            <span className="dh-popular-label">People ask</span>
            {popular.map(({ item, category: c }) => (
              <button key={item.id} type="button" className="dh-chip" onClick={() => jumpTo(item, c)}>
                {item.question}
              </button>
            ))}
          </div>
        )}
        <p className="dh-stats" aria-label="What's here">
          <span>
            <b>{total || "—"}</b> answers
          </span>
          <span>
            <b>{recipes}</b> recipes
          </span>
          <span>
            <b>{guides.length}</b> guides
          </span>
        </p>
      </header>

      <section className="dh-faq" aria-labelledby="dh-faq-title">
        <div className="dh-section-head">
          <h2 id="dh-faq-title">Questions &amp; answers</h2>
          <a href="#/docs/faq" className="dh-more">
            All on one page <ArrowRight size={14} aria-hidden="true" />
          </a>
        </div>
        {failed && <p className="docs-error">Couldn't load the questions.</p>}
        {!faq && !failed && <div className="docs-loading" aria-busy="true" />}
        {faq && (
          <div className="dh-faq-body">
            <nav className="dh-cats" aria-label="Question categories">
              {[{ name: ALL, count: total }, ...faq.map((c) => ({ name: c.name, count: c.items.length }))].map(({ name, count }) => {
                const Icon = name === ALL ? BookOpen : (CATEGORY_ICON[name] ?? BookOpen);
                return (
                  <button key={name} type="button" className={`dh-cat${category === name ? " active" : ""}`} aria-pressed={category === name} onClick={() => pick(name)}>
                    <Icon size={15} aria-hidden="true" />
                    <span className="dh-cat-name">{name}</span>
                    <span className="dh-cat-count">{count}</span>
                  </button>
                );
              })}
            </nav>
            <div className="dh-questions" ref={listRef}>
              {shown.map((c) => (
                <div key={c.name} className="dh-q-group">
                  {category === ALL && <h3 className="dh-q-group-name">{c.name}</h3>}
                  {c.items.map((item) => (
                    <QuestionCard
                      key={item.id}
                      item={item}
                      number={numberOf.get(item.id) ?? 0}
                      open={open.has(item.id)}
                      onToggle={() => toggle(item.id)}
                      renderMarkdown={renderMarkdown}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section>
        <div className="dh-section-head">
          <h2>Recipes by topic</h2>
        </div>
        <div className="docs-home-topics">
          {TOPICS.map((t) => (
            <div key={t.name} className="docs-home-topic">
              <h3>{t.name}</h3>
              <ul>
                {t.links.map((l) => (
                  <li key={l.label}>
                    <a href={`#/docs/${l.slug}${l.anchor ? `/${l.anchor}` : ""}`}>{l.label}</a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="dh-section-head">
          <h2>The guides</h2>
        </div>
        <div className="dh-guide-groups">
          {GROUPS.map((group) => (
            <div key={group}>
              <h3 className="docs-home-label">{group}</h3>
              <div className="docs-home-guides">
                {guides
                  .filter((d) => d.group === group)
                  .map((d) => (
                    <button key={d.slug} type="button" className="docs-home-guide" onClick={() => navigate({ view: "docs", slug: d.slug })}>
                      <b>{d.title}</b>
                      <span>{d.description}</span>
                    </button>
                  ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
