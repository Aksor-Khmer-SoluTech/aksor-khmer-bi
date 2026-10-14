// The Guides home's questions and answers come from the repo's docs/faq.md, so GitHub readers, search and the home
// page all read the same text: each `## Heading` is a category, each `### Question` under it a question, and the
// Markdown up to the next heading its answer.

export type FaqItem = { id: string; question: string; answer: string };
export type FaqCategory = { name: string; items: FaqItem[] };

export function parseFaq(markdown: string): FaqCategory[] {
  const categories: FaqCategory[] = [];
  let item: FaqItem | null = null;
  let inCode = false;
  for (const line of markdown.split("\n")) {
    if (line.startsWith("```")) inCode = !inCode;
    const heading = inCode ? null : /^(#{2,3})\s+(.*)$/.exec(line);
    if (heading?.[1] === "##") {
      categories.push({ name: heading[2].trim(), items: [] });
      item = null;
    } else if (heading?.[1] === "###" && categories.length) {
      const category = categories[categories.length - 1];
      item = { id: `${categories.length}-${category.items.length + 1}`, question: heading[2].trim(), answer: "" };
      category.items.push(item);
    } else if (item) {
      item.answer += `${line}\n`;
    }
  }
  for (const c of categories) for (const i of c.items) i.answer = i.answer.trim();
  return categories.filter((c) => c.items.length);
}
