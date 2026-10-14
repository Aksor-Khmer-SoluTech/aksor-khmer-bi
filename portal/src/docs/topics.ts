// "By topic" index for the docs sidebar: the same sections the guides already have, regrouped by the job a reader is
// doing (loop over rows, format a date…) instead of by where an author happened to write them. Each entry is a
// guide + heading anchor (the id rehype-slug gives the heading). A stale anchor just lands at the top of the guide,
// so when a heading is renamed, update it here.

export type TopicLink = { label: string; slug: string; anchor: string };
export type Topic = { name: string; links: TopicLink[] };

const T = "create-a-template";
const B = "building-a-report";

export const TOPICS: Topic[] = [
  {
    name: "Looping",
    links: [
      { label: "Repeat table rows", slug: T, anchor: "52-repeating-table-rows" },
      { label: "Loops: {% %}, {%p %}, {%tr %}", slug: T, anchor: "51-loops-and-conditions---p--and-tr-" },
      { label: "A loop inside a loop", slug: T, anchor: "75-grouped-data-a-loop-inside-a-loop" },
      { label: "Row numbers, running totals", slug: T, anchor: "76-row-numbers-and-running-totals" },
      { label: "Repeating rows (line items)", slug: B, anchor: "repeating-rows-line-items" },
      { label: "One document per record", slug: T, anchor: "710-one-document-per-record-mail-merge" },
      { label: "Very long tables", slug: B, anchor: "very-long-tables-automatic-splitting-into-files" },
    ],
  },
  {
    name: "Conditions",
    links: [
      { label: "Logic: if, for", slug: T, anchor: "42-logic----" },
      { label: "A paragraph that shows sometimes", slug: T, anchor: "53-conditional-paragraph" },
      { label: "A section that appears only sometimes", slug: T, anchor: "73-a-section-that-appears-only-sometimes" },
    ],
  },
  {
    name: "Formatting",
    links: [
      { label: "Dates and times", slug: T, anchor: "dates-and-times" },
      { label: "Numbers and money", slug: T, anchor: "numbers" },
      { label: "Rounding and math", slug: T, anchor: "rounding-and-math-functions" },
      { label: "Arithmetic", slug: T, anchor: "arithmetic" },
      { label: "Khmer digits (០១២)", slug: T, anchor: "khmer-digits" },
      { label: "Combining text", slug: T, anchor: "combining-text" },
      { label: "Choosing text from a value", slug: T, anchor: "choosing-text-from-a-value" },
      { label: "All formatting recipes", slug: T, anchor: "45-formatting-and-converting-values" },
    ],
  },
  {
    name: "Missing data",
    links: [
      { label: "Missing data: read this once", slug: T, anchor: "43-missing-data--read-this-once" },
      { label: "Optional fields that may be missing", slug: T, anchor: "74-optional-fields-that-may-be-missing" },
    ],
  },
  {
    name: "Images, charts, codes",
    links: [
      { label: "Charts", slug: B, anchor: "charts-docx-templates-only" },
      { label: "Images", slug: B, anchor: "images-docx-templates-only" },
      { label: "Barcodes and QR codes", slug: B, anchor: "barcodes-and-qr-codes" },
      { label: "Barcode types", slug: B, anchor: "supported-types" },
      { label: "A chart in a report", slug: T, anchor: "77-a-chart-in-a-report" },
    ],
  },
  {
    name: "Excel and HTML",
    links: [
      { label: ".xlsx templates", slug: T, anchor: "61-xlsx" },
      { label: ".html templates", slug: T, anchor: "62-html" },
      { label: "HTML images and styles (resource)", slug: T, anchor: "64-html-resources-resource" },
      { label: "A styled print layout", slug: T, anchor: "79-a-styled-print-layout-html" },
    ],
  },
  {
    name: "Khmer text and fonts",
    links: [
      { label: "Khmer text in templates", slug: T, anchor: "44-khmer-text" },
      { label: "Fonts", slug: T, anchor: "65-fonts" },
      { label: "Khmer segmentation", slug: B, anchor: "khmer-segmentation--automatic-no-action-needed" },
      { label: "Keep Khmer words together", slug: "protected-terms-guide", anchor: "" },
    ],
  },
  {
    name: "Filters and data",
    links: [
      { label: "Filters, a data source", slug: B, anchor: "filters-a-data-source-and-connections" },
      { label: "A report that asks for filters", slug: T, anchor: "711-report-that-asks-the-user-for-filters" },
      { label: "Embedding a report", slug: B, anchor: "embedding-a-report-that-fetches-its-own-data" },
      { label: "Rendering many at once", slug: B, anchor: "rendering-many-contexts-at-once" },
    ],
  },
  {
    name: "When it goes wrong",
    links: [
      { label: "Testing before you integrate", slug: T, anchor: "8-testing-a-template-before-you-integrate-it" },
      { label: "Troubleshooting", slug: T, anchor: "9-troubleshooting" },
      { label: "Authoring checklist", slug: T, anchor: "10-authoring-checklist" },
    ],
  },
];
