// The guides in the repo's /docs, bundled into the portal at build time so
// they open in-app (and always match the release they shipped with) instead of
// linking out to GitHub. Vite inlines each .md as a raw string; the glob is
// lazy, so a guide's text is only fetched when someone opens it.
const sources = import.meta.glob("../../../docs/*.md", { query: "?raw", import: "default" }) as Record<
  string,
  () => Promise<string>
>;

export type DocMeta = {
  slug: string;
  title: string;
  description: string;
  group: "Build reports" | "Understand" | "For administrators";
};

// Curated order + one-liners; the slug is the file name without `.md`. A
// guide added to /docs but not listed here still builds, it just isn't linked.
// Grouped by what the reader wants to do, with template-writing first: people
// reading these inside the portal already have it installed.
export const DOCS: DocMeta[] = [
  {
    slug: "create-a-template",
    title: "Create a template",
    description: "Write, register and version a .docx, .xlsx or .html template — Jinja syntax and worked examples.",
    group: "Build reports",
  },
  {
    slug: "building-a-report",
    title: "Charts, images and data",
    description: "Charts, images, long tables, filters, data sources and embedding.",
    group: "Build reports",
  },
  {
    slug: "protected-terms-guide",
    title: "Keep Khmer words together",
    description: "Protected terms: stop names and terms splitting across lines.",
    group: "Build reports",
  },
  {
    slug: "khmer-line-breaking",
    title: "How Khmer text wraps",
    description: "Why Khmer wraps differently across rendering engines.",
    group: "Understand",
  },
  {
    slug: "why-aksor-khmer-bi",
    title: "Why Aksor Khmer BI",
    description: "The problem this project solves.",
    group: "Understand",
  },
  {
    slug: "getting-started",
    title: "Install and run",
    description: "Set up Docker or a local dev environment, up to a first rendered report.",
    group: "For administrators",
  },
  {
    slug: "deployment",
    title: "Deployment",
    description: "Docker, docker-compose, and what's verified to run.",
    group: "For administrators",
  },
  {
    slug: "authentication",
    title: "Sign-in and sessions",
    description: "Access and refresh tokens, 2FA, scripts, and how sessions end.",
    group: "For administrators",
  },
  {
    slug: "architecture",
    title: "How it works",
    description: "Which engine renders which output format, and why.",
    group: "For administrators",
  },
];

export const DEFAULT_DOC = DOCS[0].slug;

// Addresses a guide used to have, so bookmarks and pasted links keep working.
const RENAMED: Record<string, string> = { "template-authoring-guide": "create-a-template" };

export function findDoc(slug: string): DocMeta | undefined {
  const current = RENAMED[slug] ?? slug;
  return DOCS.find((d) => d.slug === current);
}

export function loadDoc(slug: string): Promise<string> {
  const load = sources[`../../../docs/${slug}.md`];
  return load ? load() : Promise.reject(new Error(`No such guide: ${slug}`));
}
