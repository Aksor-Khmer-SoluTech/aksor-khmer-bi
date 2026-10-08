# Charts, images and data

`/api/v1/reports` renders **any** `.docx` or `.xlsx` template you upload
against arbitrary JSON — a receipt, an invoice, a certificate, a payroll
slip, a rental agreement, whatever your own use case is. This walks
through building one from scratch, using the real templates already in
[`examples/report_templates/`](../examples/report_templates/) as worked
examples you can open and copy from directly.

> New to templates? Start with the [Create a template guide](create-a-template.md) —
> registering, Jinja syntax for docx / xlsx / html, and worked use cases.

## The short version

1. Open a `.docx` (Word/LibreOffice Writer) or `.xlsx` (Excel/Calc) file.
2. Type `{{ field_name }}` anywhere you want data to appear.
3. For a repeating table row (line items), see "Repeating rows" below —
   it needs a specific structure, verified against actual rendered
   output, not assumed.
4. Register it — via the [portal](#registering-and-managing-templates)
   at http://localhost:8080, or `curl`:
   ```bash
   curl -X POST http://localhost:8000/api/v1/reports \
     -F "file=@my_template.docx" -F "name=My Report"
   # -> {"report_id": "...", ...}
   ```
5. Render it against your data:
   ```bash
   curl -X POST "http://localhost:8000/api/v1/reports/<report_id>/render?format=pdf" \
     -H "Content-Type: application/json" \
     -d '{"field_name": "..."}' -o out.pdf
   ```

A `.docx` template can render to `docx`/`pdf`/`png`; a `.xlsx` template
only to `xlsx` — see [`architecture.md`](architecture.md) for why.

## Simple placeholders

Both formats use the same Jinja2 `{{ field }}` syntax — for docx (via
[docxtpl](https://docxtpl.readthedocs.io/)) type it directly into a
paragraph; for xlsx (via [xltpl](https://github.com/zhangyu836/xltpl))
type it directly into a cell. From
[`examples/report_templates/receipt.docx`](../examples/report_templates/receipt.docx):

```
លេខបង្កាន់ដៃ៖ {{ receipt_no }}    ចុះថ្ងៃទី {{ date }}
ទទួលបានពី៖ {{ payer_name }}
```

Nested fields and simple expressions work too — from `invoice.docx`'s
grand-total line:

```
សរុបរួម៖ {{ "{:,}".format(items | sum(attribute="line_total")) }} រៀល
```

`items` here is just a list of dicts in the JSON you send at render
time; `sum(attribute=...)` and `.format()` are plain Jinja2/Python, nothing
template-engine-specific.

## Repeating rows (line items)

This is the one part that isn't "just type it where you want it" — both
engines need the loop markers in **their own dedicated row**, separate
from the row that actually repeats. This was confirmed by direct testing
this session, not assumed from either library's docs (xltpl's docs in
particular describe a syntax that doesn't work as written).

**docx** (docxtpl's `{%tr %}` row tag) — three rows:

| Row | Content |
|---|---|
| 1 (marker) | `{%tr for item in items %}` — nothing else in this row |
| 2 (body — this is what repeats) | `{{ loop.index }}` / `{{ item.label }}` / `{{ item.amount }}` in separate cells |
| 3 (marker) | `{%tr endfor %}` — nothing else in this row |

docxtpl strips the two marker rows down to bare Jinja text in the
underlying XML, so they don't leave a visible gap — only row 2 actually
appears in the output, once per item. See `receipt.docx` or
`invoice.docx` for the real thing; both render clean, verified via
actual PDF output.

**xlsx** (plain `{% for %}` / `{% endfor %}`, *not* xltpl's documented
`{%- for %}` whitespace-trim variant — that one leaves the loop variable
unbound) — same three-row shape, but xltpl's marker rows **do** stay in
the output as blank rows, so hide them explicitly:

```python
ws["A9"] = "{% for item in items %}"
ws.row_dimensions[9].hidden = True
ws.row_dimensions[9].height = 1
# ... body row 10 with {{ item.field }} cells ...
ws["A11"] = "{% endfor %}"
ws.row_dimensions[11].hidden = True
ws.row_dimensions[11].height = 1
```

Full working recipe with the exact reasoning:
[`excel_engine.render_xlsx_template`](../packages/doc_engine/src/doc_engine/engines/excel_engine.py)'s
docstring. There's also a known LibreOffice Calc-specific bug rendering
Khmer text when *previewing* an xlsx as PDF (documented in that same
docstring) — it doesn't affect the actual `.xlsx` file the API returns,
only LibreOffice's own PDF-conversion path, which this render path
doesn't use.

## Charts (docx templates only)

Bar, line, and pie charts render as a static image embedded directly
into the document — not an interactive/live element, just a picture, the
same as any other image you'd insert in Word (see
[`docs/why-aksor-khmer-bi.md`](why-aksor-khmer-bi.md) for why this stays
document-embedded rather than becoming a dashboard feature). Put a plain
`{{ field }}` placeholder wherever you want the chart, exactly like any
other value — the field's *value*, not the placeholder syntax, is what
tells doc_engine it's a chart:

```json
{
  "sales_chart": {
    "chart": "bar",
    "title": "ការលក់ប្រចាំខែ 2026",
    "labels": ["មករា", "កុម្ភៈ", "មីនា", "Q2"],
    "series": [
      {"name": "ឆ្នាំមុន", "values": [80, 120, 95, 140]},
      {"name": "ឆ្នាំនេះ", "values": [100, 150, 120, 180]}
    ],
    "width_mm": 150,
    "height_mm": 90
  }
}
```

`"chart"` is `"bar"`, `"line"`, or `"pie"`; `pie` only uses `series[0]`,
`bar`/`line` support multiple series (grouped bars / multiple lines,
each becoming one legend entry). `width_mm`/`height_mm` are optional
(default 150×90mm).

Rendered via matplotlib — see
[`doc_engine/charts.py`](../packages/doc_engine/src/doc_engine/charts.py).
One thing worth knowing if you're picking fonts: the bundled
`KhmerOSSiemreap.ttf` has **no Latin glyphs at all** (checked directly
against its character map — A-Z/a-z are simply absent, only Khmer plus
digits are covered). Word/LibreOffice paper over this invisibly with
OS-level font substitution, but matplotlib doesn't substitute
automatically for a font handed to it directly, so mixed Khmer+Latin
chart text (a date, "Q1", a plain English word) is routed through a
font-fallback list (`[Khmer OS Siemreap, DejaVu Sans]`) instead of one
font — confirmed empirically (rendered a chart with both scripts mixed
in the same title before relying on it, not assumed from the fix alone).
Chart title/label text is **not** run through Khmer segmentation (see
below) — chart text is short and non-wrapping, so there's nothing for a
ZWSP break point to do there, and segmenting the spec's `"chart"` value
itself would silently break type detection.

## Images (docx templates only)

An image you've uploaded to the Resources library (`POST /api/v1/images`
on the api service, or the portal's Admin > Resources page) embeds into a
rendered document the same way a chart does — a plain `{{ field }}`
placeholder, with the *value* (not the placeholder syntax) telling
doc_engine to treat it as an image instead of text:

```json
{
  "employee_photo": {
    "image_id": "77438b0d3b93",
    "width_mm": 40
  }
}
```

`image_id` is whatever `POST /api/v1/images` returned when you uploaded
it; `width_mm` is optional (default 40mm) — height isn't settable
separately, it scales automatically from the image's own aspect ratio.
The image must belong to the same organization as the report being
rendered, checked server-side at render time (`app/context_media.py`) —
rendering itself stays public/unauthenticated the same as every other
report render (see "Registering and managing templates" below), so this
org check is the only gate an image reference goes through, not a
separate permission on top of it. A missing or cross-org `image_id`
fails the render with `400`, same shape as any other render error.

Unlike a chart (generated on the fly from data already in the request),
an image is *fetched* — `doc_engine` itself never sees an `image_id` or
touches the image store at all (it's a standalone library with no
database access); the api service resolves the reference to raw bytes
before doc_engine ever runs, then doc_engine turns those bytes into a
`docxtpl.InlineImage` exactly the way it already does for a rendered
chart PNG. Only `.docx` templates support this — `.xlsx` has no
equivalent mechanism yet, the same limitation charts already have.

## Khmer segmentation — automatic, no action needed

Every string in your JSON body is run through ICU word segmentation
(ZWSP insertion) before rendering, regardless of which fields you named
or what language they're in — see
[`segment_generic`](../packages/doc_engine/src/doc_engine/segmentation.py),
which recurses into every string in the payload since a report template
has no fixed field list to selectively segment against. In practice this
means long Khmer text in any field wraps/justifies correctly without you
doing anything — see
[`khmer-line-breaking.md`](khmer-line-breaking.md) for why this step
exists at all.

## Very long tables: automatic splitting into files

A PDF costs a fixed ~2 s to produce (LibreOffice starting up) plus time per
row that grows faster than the row count. Measured on a plain three-column
invoice: 1,000 rows ≈ 4 s (65 pages), 5,000 rows ≈ 28 s, 10,000 rows ≈ 2 minutes
and 1.3 GB of memory. So a report whose repeating table has more than
`MAX_ROWS_PER_FILE` rows (**1,000** by default, never more than 5,000) is
rendered as **several files**, each with an equal share of the rows
(1,001 rows → 501 + 500, not 1,000 + 1), and returned as **one ZIP**:

```
<report_id>-part-01-of-03.pdf
<report_id>-part-02-of-03.pdf
<report_id>-part-03-of-03.pdf
```

- **Which table** is the one the template loops over — the `items` in
  `{%tr for item in items %}` (docx) or `{% for item in items %}` (xlsx/html).
  It's found by reading the template, never guessed from the data. If a report has
  two loops that are *both* over the limit it isn't split (the other table would
  repeat in every file) and a warning is logged.
- **From the API**: `POST …/render?format=pdf` (and the authenticated
  `POST …/run`) returns the ZIP with `X-Report-Parts: 3`. Add `part=2` (`"part": 2`
  in the `/run` body) to get just that one file — that's what the portal's preview
  does. A report under the limit is one ordinary file (`X-Report-Parts: 1`).
- **In the portal** the preview shows one file with a "File 1 of 3" switcher, and
  Export downloads all of them as the ZIP.
- **Limits**: one request renders its files one after another, so it's capped at
  `MAX_REPORT_PARTS` files (20 by default, at most 100); more rows than that is a
  `400` telling the caller to narrow the filters. Splitting isn't free — every extra
  file pays the ~2 s startup — so it's for big reports, not small ones.
- **Batch render** makes one document per record and never splits: a record with more
  rows than one file allows is a `400` (render it on its own to get it split).

### Template variables

For any report that has a repeating table, **every** render is given these — split or
not, so a template reads the same either way:

| Variable | Meaning |
|---|---|
| `part_number`, `part_count` | which file this is, of how many |
| `row_offset` | rows in the earlier files — `{{ row_offset + loop.index }}` keeps the numbering going across files |
| `first_row`, `last_row` | this file's 1-based row range |
| `part_row_count`, `total_row_count` | rows in this file / in the whole set |
| `part_totals`, `grand_totals` | `{column: sum}` over this file's rows / over the whole set |

```
Part {{ part_number }} of {{ part_count }} — rows {{ first_row }}–{{ last_row }} of {{ total_row_count }}
…table…
Subtotal (this file): {{ part_totals.line_total }}
Total (all files):    {{ grand_totals.line_total }}
```

`part_totals`/`grand_totals` cover every numeric column of the rows (JSON numbers — a
number sent as a string isn't summed); the template picks the column it means as "the
total". A key you already send yourself (your own `grand_total`, say) is never overridden.

## Rendering many contexts at once

`POST /api/v1/reports/{report_id}/render/batch?format=...` takes a JSON
*array* of contexts instead of one object, and returns a ZIP with one
rendered file per context (`{report_id}-0000.<fmt>`,
`{report_id}-0001.<fmt>`, ...) — useful for a mail-merge-style run (many
invoices, many notices) without one HTTP round trip per document.

```bash
curl -X POST "http://localhost:8000/api/v1/reports/<report_id>/render/batch?format=pdf" \
  -H "Content-Type: application/json" \
  -d '[{"customer_name": "A"}, {"customer_name": "B"}]' -o out.zip
```

This is one synchronous request: every context renders in order, the first
error fails the whole batch, and there's no progress while it runs. (The Jobs
feature's worker could run it in the background, but there is no batch job type
yet — its `render_report` job renders a single context.) So the size of a batch
is bounded by **time**, and that differs sharply by output format:

| Format | About | Default limit per request | Setting |
|---|---|---|---|
| `pdf`, `png` | 2 s per record — each is a LibreOffice conversion, and the ~2 s is LibreOffice starting up | **30** (~ a minute) | `MAX_BATCH_PDF_PNG` (at most 200) |
| `docx`, `xlsx` | 0.01 s per record — filled in directly, no conversion | **1,000** | `MAX_BATCH_DOCX_XLSX` (at most 5,000) |

(Timings are from one machine on a small invoice — the limits are what's
enforced, the times just say roughly what to expect.) A batch over its
format's limit is a `400` before anything renders, saying why and what to do;
`GET /api/v1/reports/batch-limits` returns the current numbers, which is where
the portal's Batch render page gets its estimate. A single record with more
rows than one file allows is refused too — render it on its own to have it split
(see [*Very long tables*](#very-long-tables-automatic-splitting-into-files)).

In the portal, **Batch render** is shown to people who can manage templates
(`report:manage`); it takes hand-written JSON records, so it's a developer tool.

## Finding out what a template expects

`GET /api/v1/reports/{report_id}/schema` returns a best-effort list of
the Jinja2 placeholder names a registered template references — useful
for building the JSON payload without opening the `.docx`/`.xlsx` file
yourself. It's a cheap heuristic, not a guaranteed-complete schema (a
docx template's fields come from docxtpl's own AST walk; an xlsx
template's come from a plain regex scan of the workbook XML, since xltpl
has no equivalent introspection) — see the route's docstring for exactly
what it can and can't see. Pair it with `PATCH /api/v1/reports/{id}`'s
`sample_context` field to save one known-good example payload once you've
worked out real values, so you (or the portal) don't have to rebuild it
from scratch every time.

## Registering and managing templates

Two ways to do everything from here — register, list, preview/render,
edit metadata, replace the file (bumps a version), delete — and
[get the template back out](#getting-a-template-back-out-and-what-changed):

- **The [portal](../portal)** (http://localhost:8080) — a console for all
  of the above plus a per-template Placeholders tab (the fields the file expects),
  Preview (render inline, save a sample payload), and Integration tab
  (ready-to-run curl/JavaScript/Python snippets with the real
  `report_id` filled in) — running as its own service separate from the
  API (see [`deployment.md`](deployment.md)). Needs
  `PORTAL_USERNAME`/`PORTAL_PASSWORD` (and `CORS_ALLOWED_ORIGINS`) set on
  the API. Each tab has its own link — `#/reports/<report_id>/history`,
  `…/parameters`, `…/preview`, and so on — so you can send a colleague
  straight to the right one.
- **The REST API directly** — see the endpoint table in
  [`api/README.md`](../api/README.md#generic-reports-apiv1reports).

### Calling a template by code instead of by id

A template's `report_id` is random and differs in every environment, which makes
anything that embeds or calls it awkward to deploy: you'd have to look up and configure
a different id for dev, staging and production. Give the template a **code** — on
its **Overview** tab (or when you register it) — and use that instead, anywhere the id
goes:

- API: `POST /api/v1/reports/revenue-comparison/render?format=pdf`
- Embed: `<iframe src="https://your-portal/#/embed/revenue-comparison">`
- Portal links: `#/reports/revenue-comparison`

The **Integration** tab has an *ID | Code* switch that fills every snippet and the embed
URL with whichever you pick. Register the template with the same code in each environment
(the Register dialog's *Code* field, or `code=` on `POST /api/v1/reports`) and
the integration needs no per-environment id at all — for example, a host app that keeps a
map like `revenue-comparison=<report_id>` can point it at the code itself.

### Filters, a data source, and connections

A template's **Parameters** and **Data source** tabs (managers only) decide what a person is
asked for when they run the report, and where the server gets its data. They are two views of
one configuration and save together — a data source's URL names filters by `{{ name }}`, so a
filter can't be renamed apart from the URL that uses it.

**Parameters** — each filter is *free text* (text, number, date, date & time, time) or a *choice
list*:

- **Default value** (free-text kinds): what the run form starts with — a literal (`H.E`,
  `2026-09-30`) or, on a date, date-time or time filter, `now()`: today's date, the current
  date and time, or the current time. A date or date-time filter can also default to
  `firstDayOfMonth()` or `lastDayOfMonth()` (a date-time reads 00:00 on the first day, 23:59 on
  the last) — handy for "this month so far" ranges. The portal fills these from the viewer's own
  clock. A run that leaves the filter out entirely (an API call, an embed) gets the same default,
  with them read in `REPORT_TIMEZONE` (default UTC); a filter sent as an empty string stays empty.
- **Choice list — a fixed list** (`value` or `value | label`, one per line), or **a REST API**:
  the *server* fetches the choices, so they can be limited per person in the Access Privilege
  tab like a fixed list. The request is set up like a data source (below); the response is read
  with JSONPath — *Items path* says where the list is (`$.data[*]` for `{"data": [...]}`; empty
  when the response is the list), and *Value* and *Label* are read from each item. **Test
  choices** makes the real request with what's typed, saved or not, and shows what came out.

  | Value / Label | Reads |
  |---|---|
  | `code`, `$.code` | the item's `code` |
  | `name.en`, `tags[0]`, `['odd key']` | a nested key, an array element, a key with awkward characters |
  | `${code} - ${nameEn}` | text mixing several paths |

  `[*]` (or `[]`, `.*`) means every element and belongs in the items path. Filters (`[?(...)]`),
  recursive search (`..`) and slices aren't supported; a path that lands on an object or a list
  is an error rather than JSON in a dropdown.

**Data source** — where the data behind the report comes from, in one of three kinds (the first thing
you choose on the tab):

- **Sample data** — a fixed JSON object you type in. Every run renders the template with exactly it, so
  you can design a template and show it to management before any real source exists. Because it has the
  same shape a REST API or a query would return, switching the source later needs no template change.
  Not for confidential data: anyone who can edit the report can read it.
- **REST API** — the response must be a JSON object; its keys become the template's fields. Either write a
  full URL — scheme and host out in full, `{{ name }}` filter values only after the host, URL-encoded for
  you — or use a **connection**.
- **Database** — a read-only SQL query (below) against a database **connection**.

Switching a report from one kind to another throws the old kind's settings away, since they mean nothing
to the new one. When there is something to lose the tab asks first, saying what would go; nothing changes
on the server until you save.

**Database queries.** A database source is one `SELECT` (or `WITH … SELECT`). A filter is written
`:name` and its value is *bound* as a parameter — never pasted into the SQL — so what someone types into
the run form can't change the statement. A filter's type (date, number…) is always checked before the query runs. Turn on **Bind filters by their type**
(on by default for a new source) and a built-in driver receives a real date or number, so `WHERE d >= :fromDate`
needs no CAST. With it off — how sources saved earlier behave — every value reaches the database as text, so cast
a date or number in the SQL (`CAST(:fromDate AS DATE)`, or `TO_DATE(:fromDate, 'YYYY-MM-DD')` on Oracle; the
editor writes these for you). An uploaded JDBC driver (Oracle, SQL Server…) always receives text, whatever the
setting, so cast there. Turning it on for an existing report may mean removing a `CAST` / `TO_DATE` that wrapped a
filter (on PostgreSQL, `TO_DATE(<date>, …)` no longer matches). a filter left empty arrives
as an empty string, so `(:branch = '' OR branch = :branch)` makes a text filter optional, and
`(NULLIF(:from, '') IS NULL OR d >= CAST(NULLIF(:from, '') AS DATE))` a date one (a bare
`CAST('' AS DATE)` fails). The rows come back under a
name you choose (default `rows`), each as an object keyed by column name, so the template loops
`{% for r in rows %}` and reads `{{ r.column_name }}`. Dates and times arrive as ISO text, decimals as
numbers. Anything but a single `SELECT` is refused — writes, DDL, procedures, a second statement,
file or network functions — the session is opened read-only with a time limit, and a result over the row
limit (20,000 by default) is an error, not a silent cut-off. That guard is a safety net, not a sandbox:
**point the connection at a read-only database account**, which is the real limit on what a report's SQL
can do.

**Connections** (Admin → Connections; permission `connection:manage`, held by system
administrators and each organization's `ROLE_ORG_ADMIN`) are named, reusable
`base URL + headers + authentication`. A report picks one and adds only a path, so when an API moves —
or you go from test to production — you edit the connection once instead of every report. Give
the connection the same *name* in each environment and the reports need no change at all.
Authentication is a bearer token, or a username with a password, and where it comes from is a choice
made per connection: a **Secret** (Admin → Secrets — a named credential created, rotated and revoked
in the portal, encrypted at rest, and never shown again once saved) or an environment variable on the
API server, for a deployment that would rather keep credentials out of the database entirely. Rotating
a Secret is one edit; the very next run uses it, no server access, no restart. Whoever can edit a connection (`connection:manage`) decides where its credential is
sent: pointing it at another host sends the same Secret there, so grant that permission as you would the
ability to read the credential. The same is true of **a report's own data source or
choice list (no connection at all), which can name a Secret too**: whoever can edit the report can aim that
Secret at any URL, so prefer a connection when the credential matters. The same "Where the token/password is
kept" picker appears on its Data source and Parameters tabs, so a one-off credential doesn't need a
connection wrapped around it just to keep it out of the server's environment. Report authors and
connection authors alike can pick an existing Secret by name (that permission is enough to list them),
but creating, rotating, revoking or deleting one needs `secret:manage`, separately. Revoking a Secret
doesn't delete it: whatever still names it keeps existing, but the next run that needs it fails with a
plain "credential has been revoked" instead of silently using a stale value. Report authors see
connections (`report:manage` is enough to pick one) but neither their header values nor their
credentials. A connection in use, or a Secret anything still refers to, can't be deleted; a connection's
name is fixed once created because reports refer to it.

**Database connections** (Admin → Connections → *+ Database*) hold what is needed to reach one database:
the engine (Oracle, PostgreSQL, MySQL, SQL Server, MariaDB or IBM Db2, each with its logo), host, port,
database (Oracle: service name or SID), a **secure connection mode** (disabled, required, verify CA,
verify full — each engine's own settings are built for you), the driver, and the login. The JDBC URL is
shown and editable: it is built from the fields, and pasting one fills them in. **Test connection** logs
in with the settings on screen and runs the engine's trivial statement, saving nothing; a failure says
only that it failed, since the driver's own message can name hosts and users (it is in the server log).

The password is never a field on that form. It is a **Secret** (Admin → Secrets): encrypted in the
database with a key kept outside it, write-only — no page, API, audit entry or backup can read it back —
and decrypted only for the moment a query runs. The picker offers *+ New credential* for anyone who holds
`secret:manage`; replacing a password is rotating the Secret. A Secret that a connection uses can't be
deleted. Whoever can edit a connection (`connection:manage`) decides where that credential is sent, so
treat the permission accordingly.

**JDBC drivers.** PostgreSQL, MySQL and MariaDB run on built-in Python drivers. For any other engine —
Oracle, SQL Server, Db2 — upload the vendor's JDBC driver (`.jar`) under Admin → JDBC Drivers
(permission `driver:manage`, held by system administrators and each organization's `ROLE_ORG_ADMIN`),
then choose it on the connection; the page links to each vendor's download. The upload is checked (a
real `.jar` containing the driver class you named, under 80 MB), its SHA-256 is recorded and audited, and
it can be downloaded again to reuse in another environment. A driver is code, and loading it runs it, so
queries on an uploaded driver never run inside the API: they go to the isolated `jdbc-worker` service
(`docker compose --profile jdbc up -d`; see docs/deployment.md), which has no access to the platform's
database or keys. An uploaded driver also unlocks a custom JDBC URL, used exactly as written.

**Display formats** — how dates and times read in the portal (the run form, the default-value
editor) is a per-deployment setting in the portal's `config.js`, not the API's; see
[`portal/README.md`](../portal/README.md#date-and-time-display). The values a report *receives*
are always ISO (`2026-09-30`, `08:30`, `2026-09-30T08:30`).

### Embedding a report that fetches its own data

`#/embed/<report>` is anonymous, and its `postMessage` `context` (or `?context=`) is data the
*host page* supplies — Aksor only formats it. A report with a **data source** is different:
"run it for these parameters" makes Aksor's *server* fetch data using the report's stored
credentials, so anyone who could ask would be reading that data with no login. So Aksor decides
who may ask: an **API client** an admin granted the report ([below](#running-a-report-as-an-api-client-client-id--secret)).
A request without valid client credentials is refused (`401`), for every report. (There is deliberately no setting
that lets a report run with no credential at all.)

**Where the secret lives matters.** A client's secret is a password for every report it was granted. Best: the
host's own **server** calls `POST /api/v1/reports/{id}/embed-run` (with `client_id` + `client_secret`) and hands the
rendered file to its user, so the secret never reaches a browser. If the host page posts the credentials to the
embed frame from browser JavaScript (as below), anyone who can open that page can read them and run **any granted
report with any filters** — so grant such a client only reports that every visitor of that page may see, and rotate
its secret if it is ever exposed.

Codes are 3–64 lowercase letters, digits and single hyphens, unique across the deployment,
and — once an organization has used one — reserved to that organization. Changing or
removing a code breaks anything calling the old one (the id always keeps working), so the
form warns first. Full rules: [`api/README.md`](../api/README.md#addressing-a-report-by-id-or-by-code).

### Running a report as an API client (client id + secret)

An **API client** is a machine identity -- a client ID and a secret -- that may run an explicit
list of reports, beside roles and per-user grants. It is the way to let an embedding app (such as
partner-web) send just the parameters, and it is managed at runtime: no environment variable, no restart.

1. In the portal open **Admin → API Clients** (needs the `client:manage` permission -- a system
   administrator or an organization's `ROLE_ORG_ADMIN`; deliberately *not* `report:manage`, so
   editing a template can't also hand out access to its data), choose **New client**, tick the
   reports it may run, and copy the client ID and secret it shows. The secret is shown **once**; only
   its hash is stored. (`POST /api/v1/clients` does the same; see `/docs`.)
2. The embedding app posts the parameters with the credentials:

   ```js
   frame.contentWindow.postMessage(
     { source: "aksor-report-viewer", type: "render", parameters: { … },
       clientId: "partner-web", clientSecret: "aksor_cs_…" },
     "https://your-portal");
   ```
3. The frame calls `POST /api/v1/reports/{id}/embed-run` with `{parameters, client_id, client_secret, format, part}`.
   Aksor checks the secret (constant time), that the client is active and holds a grant for *this*
   report in its own organization, applies the same parameter validation as any run, then fetches
   the data and renders.

A wrong secret, an unknown client and a disabled client all answer `401 Invalid client
credentials`; a genuine client asking for a report it wasn't granted is `403` and lands in the
security feed. Runs are rate-limited **per client** (`CLIENT_RUN_LIMIT_PER_MINUTE`, default 120 --
over it, `429`) and logged as `embed-client`. Change the granted reports, **rotate** the secret (the
old one stops working at once), or disable/delete the client from the same page; each change is in
the audit log, the secret never is.

If the embedder is a *browser app*, its secret is visible to that app's users -- it can't stay
private from them. What it does give you is scope (only the granted reports, only through
parameter-validated runs), instant revocation and per-client accounting; keep each client's report
list minimal. A server-side embedder keeps the secret fully private.
Design and security notes: `specs/api_clients_design.md` (a local design note, not in the repo).

### Getting a template back out, and what changed

The file you upload is kept, not just used. On a template's **Overview** tab,
**Download current** gives you the `.docx`/`.xlsx`/`.html` exactly as
uploaded — placeholders intact, not a rendering of it — and **Download
original** gives you the very first upload (v1), even after the file has been
replaced any number of times. (API: `GET /api/v1/reports/{id}/file`, add
`?version=N` for a specific one.) Both need Manage access on the template.

The **History** tab is the template's change log. Each uploaded version is
a card: who uploaded it and when, their note (replacing a file is choose → describe → confirm: drop the
new file on the zone, set the *Version* (pre-filled with the next patch number, e.g. 1.0 → 1.0.1; clear it for plain v3-style numbering), fill in *What changed?*, then press *Upload new version* —
nothing is uploaded before that, and a `.docx` can't show you a text diff, so
the note is where a person says what they did), its size, a checksum, and — computed for you —
which `{{ placeholders }}` that version added or dropped compared with the one
before. Every version has its own download button. Alongside the versions
sit the other recorded changes to the template: renames, data-source and
filter changes, protected-term changes, who was granted or lost access, and
every download of the template file. Filter by *File versions*, *Settings*,
*Access* or *Downloads*.

A template that was replaced **before version history existed** can't give
back files that were already overwritten: its History starts at the current
version (marked "recovered — uploader unknown"), says plainly which earlier
versions weren't kept, and the *Download original* button is disabled. From
its next replace on, everything is kept.

Admins can search the same trail across everything — templates, users, roles,
access, directory settings, jobs — under **Admin → Audit Log**; see
[the change audit trail](../api/README.md#change-audit-trail).

## Worked examples

Run these yourself (`python examples/build_receipt.py` /
`build_invoice.py` from the repo root, venv active) to see the whole
pipeline end to end, output lands in `output/`:

- **Receipt** — payer/payee fields, one repeating line-item table, a
  total. The simplest complete example.
- **Invoice** — issuer/customer fields, a 5-column repeating table
  (qty × unit price), a grand total — rendered as **both** `.docx`
  (`invoice.docx`) and `.xlsx` (`invoice.xlsx`) from the exact same
  Python dict, demonstrating both engines side by side on one dataset.
