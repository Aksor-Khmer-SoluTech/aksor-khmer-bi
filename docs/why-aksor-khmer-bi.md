# Why Aksor Khmer BI

## The actual problem

Khmer is normally written with no spaces between words. Every layout
engine that isn't dictionary-aware — browsers, WeasyPrint/Pango, most
PDF tooling, mail-merge in a generic office suite — treats a long
unspaced Khmer string as a single unbreakable token. Point it at a form
field, an invoice line, an address block, and it doesn't wrap: it
overflows, gets clipped, or breaks the layout. This isn't a rare edge
case for Khmer text specifically — it's the default, because almost no
tooling outside the Khmer-speaking world was built with it in mind.

LibreOffice/Word's own Writer engine gets this right, because it uses
ICU's dictionary-based word `BreakIterator` internally. The
[`aksor_khmer_ocr_segmenter`](../packages/aksor_khmer_ocr_segmenter)
package exposes that exact same mechanism standalone — dictionary-based
Khmer segmentation via `PyICU`, the same open-source library
LibreOffice/ICU-based tools use — so any renderer can get real break
points, not just ones with Writer's engine built in. The research behind
this is in [`khmer-line-breaking.md`](khmer-line-breaking.md); every
claim there was checked against actual rendered output.

## What this project actually is

A template-to-document renderer: fill a `.docx` or `.xlsx` template
(Jinja2 placeholders) once, get `PDF`, `PNG`, `DOCX`, or `XLSX` out,
correctly Khmer-wrapped regardless of field length. `/api/v1/reports`
makes that generic — register any template, render it against arbitrary
JSON, no fixed schema. It's free, MIT-licensed, and self-hostable, which
matters specifically for financial/legal documents (receipts, invoices,
official notices) where keeping the data on infrastructure you control
is often a real requirement, not a preference.

## What it deliberately is not

Worth being explicit about, since "dynamic report engine" invites the
comparison: this is not JasperReports or Power BI. Specifically absent,
on purpose, not as an oversight:

- **No data connectors.** Nothing here queries a database or an API on
  your behalf — you supply the JSON, every time. Adding that would be a
  legitimate future direction, but it's a materially different, larger
  scope than what's built today.
- **No BI/analytics layer.** No dashboards, no drill-down, no scheduled
  report runs, no live/interactive charts. Bar/line/pie charts *can* be
  embedded as static images inside a generated document (see
  [`building-a-report.md`](building-a-report.md#charts-docx-templates-only))
  — that's still "render a picture into a document from a template you
  supplied the data for," not a dashboard. There's no view where a chart
  updates live, queries anything itself, or exists outside a rendered
  document.
- ~~No multi-tenant access control beyond the one admin credential~~ —
  no longer true: `api` now has multi-tenant Organizations, Users, Roles,
  a fixed permission catalog, and three *expiring* access-grant tables
  (a role, a direct permission, or access to one specific report, each
  optionally time-boxed), benchmarked against JasperReports Server's own
  model — see `api/README.md`'s "Multi-tenant auth, roles & permissions"
  section and `api/app/rbac.py`. The break-glass single admin credential
  still exists (`PORTAL_USERNAME`/`PORTAL_PASSWORD`), now as a bootstrap
  fallback rather than the only mechanism. People sign in with the standard
  short-lived access token + rotating refresh token flow, over sessions an
  administrator or the user can end at once, with optional two-factor
  authentication — see [`authentication.md`](authentication.md).

If your actual need is a BI dashboard or a scheduled-report platform,
this isn't that tool. If your need is "take this Word/Excel template my
business already uses and generate real documents from it, in Khmer,
correctly" — that's exactly the gap this fills, and free/open-source
alternatives for that specific problem are genuinely scarce.

## Why it's worth using over rolling your own

The honest case isn't "this does more than you'd build yourself" — a
docx-mail-merge script is not hard to write. It's:

- **The Khmer line-breaking problem is already solved and verified**,
  which is the part that's easy to get subtly wrong (and easy to not
  notice being wrong until a field is longer than whoever tested it
  expected).
- **Two rendering paths already exist and are documented** — LibreOffice
  (native justify, matches the source docx exactly) and WeasyPrint
  (lighter, HTML/CSS-templated) — see [`architecture.md`](architecture.md)
  for the actual tradeoff, not just "use whichever."
- **A curated, growing list of known ICU mis-splits** (transliterated
  names, brands, loanwords) that would otherwise need discovering the
  hard way, one production bug at a time — see
  [`protected-terms-guide.md`](protected-terms-guide.md).
- **It's a starting point you can read end to end.** Every package is a
  few hundred lines, not a framework to learn — see
  [`architecture.md`](architecture.md) for the whole shape of it.

## Contributing

This project has near-zero tolerance for "looks right in one
screenshot" without verification — see [`CONTRIBUTING.md`](../CONTRIBUTING.md).
Real-world Khmer text that exposes a segmentation or justify bug is
exactly the kind of contribution most valuable to it.
