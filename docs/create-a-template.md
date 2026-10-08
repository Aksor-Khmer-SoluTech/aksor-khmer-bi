# Create a template

How to write a template, register it, and use Jinja syntax in `.docx`, `.xlsx` and
`.html` files — with a worked example for each common use case.

Every snippet and output on this page was run against the real render engines
(docxtpl for docx, xltpl for xlsx, Jinja2 + WeasyPrint for html), not copied from the
libraries' own documentation, which differs from what actually works in a few places
(noted where it matters).

Related: [`building-a-report.md`](building-a-report.md) is the reference for charts,
images, long-table splitting, filters/data sources and embedding. This page is the
"how do I write and register one" walkthrough.

---

## 1. Pick a format

| You want | Use | Renders to |
|---|---|---|
| A letter, certificate, invoice, form — laid out in Word | **`.docx`** | `docx`, `pdf`, `png` |
| A spreadsheet the recipient will keep editing / a data export | **`.xlsx`** | `xlsx` |
| Pixel-level print layout with CSS (badges, cards, columns) | **`.html`** | `pdf`, `png` |

Rules of thumb: start with `.docx` — it has the most features (charts, images, PDF) and
anyone can edit it in Word. Use `.xlsx` only when the output must stay a spreadsheet.
Use `.html` when you need CSS control Word can't give you.

An `.xlsx` template can only produce `.xlsx` (see [architecture](architecture.md)).

---

## 2. The workflow, end to end

1. **Write** the file with `{{ placeholders }}` where data goes (sections 4–6).
2. **Register** it (section 3). Aksor reads the file and lists the fields it found.
3. **Check** the **Placeholders** tab — it shows every field the template expects.
4. **Preview** with sample data (**Preview** tab → save it as the *sample payload*).
5. **Integrate** — the **Integration** tab gives ready-made curl / JavaScript / Python
   snippets with your real `report_id` (or code) filled in.
6. **Iterate** — fix the file and *replace* it (section 3.3). Old versions are kept.

---

## 3. Registering a template

You need the `report:manage` permission.

### 3.1 In the portal

**Templates → Register template**, then fill in:

| Field | Required | Notes |
|---|---|---|
| **Name** | yes | What people see in the gallery. |
| **Code** | no | A stable address instead of the random `report_id`: 3–64 lowercase letters, digits and single hyphens, unique across the deployment (e.g. `revenue-comparison`). Use the **same code in every environment** and integrations need no per-environment id. Hard to change later — anything calling the old code breaks. |
| **Folder** | no | Which Resources folder the report is filed in — **Root** (the default) or any folder you may file into. It decides where the report appears in the Reports page's tree view (section 3.4). |
| **Description** | no | Shown on the card. |
| **Template file** | yes | `.docx`, `.xlsx` or `.html`. Drag and drop or browse. |

For an **html** template the dialog also checks the Jinja syntax live, lists the
detected fields, and shows a **Map referenced resources** step for each
`{{ resource('name') }}` it finds (section 6.4). A syntax error blocks registration and
tells you the line.

### 3.2 With the API

```bash
curl -X POST http://localhost:8000/api/v1/reports \
  -H "Authorization: Bearer <token>" \
  -F "file=@invoice.docx" \
  -F "name=Invoice" \
  -F "code=invoice" \
  -F "description=Customer invoice" \
  -F "note=First version"
# -> {"report_id": "4f21d42da926", "version": 1, ...}
```

Optional form fields: `code`, `description`, `note` (recorded against version 1 in the
change log), and — html only — `resource_bindings` (JSON mapping each `resource()` name
to `{"kind": "image"|"stylesheet", "id": "..."}`).

Errors you may see: `400` file isn't a valid `.docx`/`.xlsx`, html isn't valid
UTF-8 / has a syntax error / has an unmapped resource; `409` code already taken.

Render it:

```bash
curl -X POST "http://localhost:8000/api/v1/reports/invoice/render?format=pdf" \
  -H "Content-Type: application/json" \
  -d '{"customer": {"name": "Dara"}, "items": [...]}' -o invoice.pdf
```

### 3.3 Changing a template later (versions)

On the template's **Overview** tab → *Replace template file*:

1. Drop the new file on the zone (nothing is uploaded yet).
2. Set **Version** — pre-filled with the next patch number (`1.0` → `1.0.1`). Type your
   own (`2.0`, `1.1.0-rc1`) or clear it for plain `v3` numbering. Must be unique per
   template.
3. Optionally write **What changed?** — a Word file can't be diffed as text, so this
   note is how the next person knows what you did.
4. **Upload new version.**

The `report_id`, code and integrations stay the same; the previous file stays
downloadable in **History**, which also shows which `{{ placeholders }}` each version
added or dropped. A typo in a label or note can be fixed afterwards with
**Edit version & note**.

> Replacing a `.docx` with an `.xlsx` (or the reverse) changes which output formats the
> template can produce. The form warns you first, because anything asking for a format
> the new file can't make will fail.
> An `.html` template can't be replaced in place — register it as a new template.

### 3.4 Folders and shortcuts

Templates are organised in **Resources** folders (Admin → Resources), which can be nested as deep as you
like. The **Reports** page (where people go to *run* things) offers **Tree** (the default, first in the layout
switch), **Grid** and **List**: the tree shows each folder with a count, its sub-folders inside it, and what is
filed there. The **Templates** page is a flat catalogue of every template — grid or list — because folders and
shortcuts are about where people find a report, not about managing the template. Your choice is remembered per
page.

- **File a template** with the **Folder** field on the Register dialog, or later on the template's
  **Overview** tab (then *Save changes*). **Root** means no folder. Filing into a folder needs
  `manage` access on that folder, and the folder must belong to the template's organization.
- **Why shortcuts exist: one report, several teams.** When two or more departments or teams use the same
  report, each can keep it in *their own* folder and arrange that space the way they like (their own
  sub-folders, their own order of things) without copying the report. There is still one report, one template
  and one set of permissions. To set it up: give each team's role access to the report itself (Access tab →
  report grant), then add a shortcut in each team's folder. Folder access alone is not enough — a shortcut never
  grants the report.
- **A shortcut** lists the same template in *another* folder as well, so one report can sit under
  "Finance / Q1" and "Audit" without a copy. On the template's **Shortcuts** tab, choose a
  folder and **Add shortcut**; remove one with the ✕. A shortcut is only a second place to find the report:
  opening it opens the original, so it has **exactly the original's permissions**.
  - It grants nothing. Giving someone access to the folder that holds a shortcut does **not** give them the
    report, and never reveals it to them.
  - People see it only if they already have access to the original, and only in folders they may open.
  - Making one needs `manage` on the report **and** on the destination folder. Removing one needs `manage`
    on the report *or* on the folder it sits in, and never touches the report.
  - Deleting the report removes its shortcuts. Deleting a folder removes the shortcuts in it (they are only
    links); filing the report itself into a folder where it has a shortcut replaces that shortcut.
  - In Admin → Resources a shortcut shows with a *Shortcut* badge, **Open the original** and
    **Remove shortcut**; it can't be dragged (move the original instead).

---

## 4. Jinja syntax cheat sheet

All three formats use Jinja2. What differs is *where* the control tags go.

### 4.1 Output — `{{ … }}`

| Write | Result |
|---|---|
| `{{ name }}` | the field `name` |
| `{{ customer.name }}` | nested field (`{"customer": {"name": "Dara"}}`) |
| `{{ items[0].label }}` | first list element's field |
| `{{ qty * price }}` | arithmetic |
| `{{ first ~ " " ~ last }}` | string concatenation (`~`) |
| `{{ "{:,.2f}".format(amount) }}` | `1,234.50` — thousands separator, 2 decimals |
| `{{ amount \| round(0) \| int }}` | rounded whole number (`1234.5` → `1234`; halves round to even) — ceiling/floor/abs/min/max in [4.5](#45-formatting-and-converting-values) |
| `{{ name \| upper }}` / `lower` / `title` | case |
| `{{ note \| default("N/A", true) }}` | fallback when the value is missing **or empty/null** |
| `{{ items \| length }}` | number of items |
| `{{ items \| sum(attribute="line") }}` | total of one column |
| `{{ items \| map(attribute="label") \| join(", ") }}` | `Pen, Book` |
| `{{ text \| truncate(80) }}` | shorten long text |

Dates and times arrive as **ISO strings** (`2026-09-30`, `08:30`, `2026-09-30T08:30`) and
there's no date filter, so reformat by slicing:

```
{{ date[8:10] }}/{{ date[5:7] }}/{{ date[:4] }}      →  30/09/2026
```

(Or send the date already formatted in your JSON.) More date, number and Khmer-digit
recipes are in [4.5](#45-formatting-and-converting-values).

### 4.2 Logic — `{% … %}`

| Write | Meaning |
|---|---|
| `{% if status == "paid" %}…{% elif status == "due" %}…{% else %}…{% endif %}` | conditional |
| `{% if items %}` | true when the list is non-empty |
| `{% if a and b %}`, `or`, `not` | combine conditions |
| `{% for it in items %}…{% endfor %}` | loop |
| `{{ loop.index }}` / `loop.index0` / `loop.first` / `loop.last` / `loop.length` | position inside a loop |
| `{% set total = items \| sum(attribute="line") %}` | a local variable |

### 4.3 Missing data — read this once

| Template | Field absent from the JSON | Result |
|---|---|---|
| `{{ nothing }}` | missing | **empty** — renders as blank, no error |
| `{{ issuer.name }}` | `issuer` missing | **error** — `'issuer' is undefined` |
| `{{ issuer.name if issuer else "" }}` | `issuer` missing | empty (safe) |
| `{{ note \| default("N/A", true) }}` | missing / null / `""` | `N/A` |

Reading a *property of* something that isn't there fails the render. Guard nested fields
that may be absent with `if`, or give the filter a default (see
[Filters, a data source…](building-a-report.md#filters-a-data-source-and-connections)).

### 4.4 Khmer text

Nothing to do. Every string in your JSON is word-segmented automatically so long Khmer
text wraps and justifies correctly ([why](khmer-line-breaking.md)). If a Khmer word is
being split wrongly, see the [protected-terms guide](protected-terms-guide.md).
Set the template's font to a Khmer font (e.g. *Khmer OS Siemreap*) in Word.

### 4.5 Formatting and converting values

Recipes for the usual display jobs. Each result below was produced by running the
expression with `date` = `"2026-09-30"`, `ts` = `"2026-09-30T08:30"`, `amount` = `1234.5`,
`qty` = `3`, `price` = `2.5`, `pct` = `0.256`, `n` = `7`.

**Combining text with `~`** — `~` joins values and literals (including `"/"`); `+` is for
numbers only, so `"a" + 1` is an error.

| Write | Result |
|---|---|
| `{{ (qty * price) ~ "/" ~ n }}` | `7.5/7` |
| `{{ first ~ " " ~ last }} ({{ first[0] }}.{{ last[0] }}.)` | `Dara Sok (D.S.)` |
| `{{ phone[:3] }} {{ phone[3:6] }} {{ phone[6:] }}` | `012 345 678` (from `012345678`) |

**Arithmetic** — `+ - * /`, `//` (whole-number divide), `%` (remainder), parentheses.

| Write | Result |
|---|---|
| `{{ qty * price }}` | `7.5` |
| `{{ 10 / 4 }}` / `{{ 10 // 4 }}` / `{{ 10 % 4 }}` | `2.5` / `2` / `2` |
| `{{ (qty * price) \| round(1) }}` | `7.5` |

**Rounding and math functions** — Jinja has no `round()`, `ceil()`, `floor()` or `sqrt()`
*functions*; these are **filters** (`value | filter`) or operators, and they are the whole
list. Rounding returns a decimal (`1235.0`), so add `| int` when you want a whole number.
Values: `x` = `1234.567`, `neg` = `-7.25`, `amt` = `-12.5`, `a` = `10`, `b` = `4`.

| You want | Write | Result |
|---|---|---|
| Round to 2 decimals | `{{ x \| round(2) }}` | `1234.57` |
| Round to a whole number | `{{ x \| round(0) \| int }}` | `1235` |
| Round to tens / hundreds | `{{ x \| round(-2) }}` | `1200.0` |
| **Ceiling** (always up) | `{{ x \| round(0, "ceil") \| int }}` | `1235` |
| **Floor** (always down) | `{{ x \| round(0, "floor") \| int }}` | `1234` |
| Ceiling / floor to 2 decimals | `{{ x \| round(2, "ceil") }}` / `{{ x \| round(2, "floor") }}` | `1234.57` / `1234.56` |
| Ceiling / floor of a negative | `{{ neg \| round(0, "ceil") \| int }}` / `{{ neg \| round(0, "floor") \| int }}` | `-7` / `-8` |
| Cut off the decimals (toward zero) | `{{ x \| int }}` / `{{ neg \| int }}` | `1234` / `-7` |
| Absolute value | `{{ amt \| abs }}` | `12.5` |
| Larger / smaller of two | `{{ [a, b] \| max }}` / `{{ [a, b] \| min }}` | `10` / `4` |
| Largest / smallest in a column | `{{ items \| map(attribute="v") \| max }}` | `9` |
| Total / average of a column | `{{ items \| sum(attribute="v") }}` / `{{ (items \| sum(attribute="v")) / (items \| length) }}` | `12` / `6.0` |
| Power / square root | `{{ a ** 2 }}` / `{{ (a ** 0.5) \| round(3) }}` | `100` / `3.162` |
| Pages needed (divide, round up) | `{{ (a / b) \| round(0, "ceil") \| int }}` or `{{ (a + b - 1) // b }}` | `3` |
| Round up to the next 5 | `{{ ((x / 5) \| round(0, "ceil") \| int) * 5 }}` | `1235` |
| Text to a number | `{{ "12.5" \| float + 1 }}` / `{{ "12" \| int + 1 }}` | `13.5` / `13` |

Two things that surprise people:

- **Plain `round` rounds halves to the even number** (`2.5` → `2`, `3.5` → `4`), the way
  Python does. For "always .5 up" on a positive number use `{{ (value + 0.5) | int }}`
  (`2.5` → `3`).
- **Floor division and remainder follow Python on negatives:** `-7 // 2` is `-4` and
  `-7 % 3` is `2`. Use `round(0, "floor")` / `round(0, "ceil")` when you mean floor and
  ceiling, so the intent is readable.

Round **before** you format (`"{:,.2f}".format(x | round(2, "ceil"))`) when the rounding
rule matters; `"{:.2f}".format(x)` alone uses the half-to-even rule.

**Numbers** — format with `"{...}".format(value)`; the part after `:` is the format.

| Write | Result |
|---|---|
| `{{ "{:,.2f}".format(amount) }}` | `1,234.50` |
| `{{ "{:,.0f}".format(amount) }}` | `1,234` (halves round to even) |
| `{{ "{:,}".format(1234567) }}` | `1,234,567` |
| `${{ "{:,.2f}".format(qty * price) }}` | `$7.50` |
| `{{ "{:.1f}%".format(pct * 100) }}` | `25.6%` |
| `{{ "{:05d}".format(n) }}` | `00007` — zero-padded (invoice numbers) |
| `{{ "{:,.2f}".format(amount).replace(",", " ") }}` | `1 234.50` |
| `{{ "{:,.2f}".format(amount).replace(",", "X").replace(".", ",").replace("X", ".") }}` | `1.234,50` — swap the separators |
| `{{ "{:,.2f}".format(items \| sum(attribute="line")) }}` | a formatted column total |

**Dates and times** — they arrive as ISO text, so slice (`[start:end]`, counting from 0):

| Write | Result |
|---|---|
| `{{ date[8:10] }}/{{ date[5:7] }}/{{ date[:4] }}` | `30/09/2026` |
| `{{ date[8:10] \| int }}/{{ date[5:7] \| int }}/{{ date[:4] }}` | `30/9/2026` — `\| int` drops the leading zero |
| `{{ ts[11:16] }} on {{ ts[:10] }}` | `08:30 on 2026-09-30` |
| `{{ ts.replace("T", " ") }}` | `2026-09-30 08:30` |
| `{{ ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][date[5:7] \| int - 1] }} {{ date[8:10] \| int }}, {{ date[:4] }}` | `Sep 30, 2026` — month name from a list |
| `{{ ["មករា","កុម្ភៈ","មីនា","មេសា","ឧសភា","មិថុនា","កក្កដា","សីហា","កញ្ញា","តុលា","វិច្ឆិកា","ធ្នូ"][date[5:7] \| int - 1] }}` | `កញ្ញា` — Khmer month name |

**Khmer digits** — convert `0–9` to `០–៩` with `translate`. It converts every digit in the
text, so apply it to the whole formatted string:

| Write | Result |
|---|---|
| `{{ ("{:,.2f}".format(amount)).translate("".maketrans("0123456789", "០១២៣៤៥៦៧៨៩")) }}` | `១,២៣៤.៥០` |
| `{% set kh = "".maketrans("0123456789", "០១២៣៤៥៦៧៨៩") %}` then `{{ (date[8:10] ~ "/" ~ date[5:7] ~ "/" ~ date[:4]).translate(kh) }}` | `៣០/០៩/២០២៦` |

Define `kh` once near the top and reuse it. In a `.docx` put the `{% set %}` alone in its
own paragraph as `{%p set kh = … %}` (see [5.1](#51-loops-and-conditions---p--and-tr-)).

**Choosing text from a value**

| Write | Result |
|---|---|
| `{{ "Paid" if n > 5 else "Due" }}` | `Paid` |
| `{{ note \| default("—", true) }}` | `—` when `note` is missing or empty |
| `{{ code \| upper }}` | `INV-0042` (from `inv-0042`) |

Only the values you format are changed — what's in the JSON (and what the API returns) is
untouched. For the same format everywhere, format once in your data instead of in every
template.

---

## 5. Writing a `.docx` template

Type the placeholders straight into the Word document — body, headers, footers, table
cells, text boxes. Keep each tag **typed in one go** with consistent formatting: Word
sometimes splits a typed tag into several invisible "runs" if you change formatting
mid-tag or let autocorrect touch it. If a tag doesn't render, retype it (or paste it as
plain text) and turn off smart quotes — Jinja needs straight `"` quotes.

### 5.1 Loops and conditions: `{% %}`, `{%p %}` and `{%tr %}`

A Word file is XML, and a Jinja tag works on text — so a control tag has to say **which piece of
Word it controls**: some text inside one paragraph, whole paragraphs, or whole table rows. That is
the only difference between the three forms. Everything else (`for`, `if`, `endfor`, `loop.index`,
`{{ field }}`) is the same Jinja you already know from [section 4](#4-jinja-syntax-cheat-sheet).

| Form | It controls | Where you type it | What happens to the paragraph / row that holds the tag |
|---|---|---|---|
| `{% … %}` | text **inside one paragraph** | in the sentence, with the text it wraps | nothing is removed — it's an ordinary paragraph |
| `{%p … %}` | **whole paragraphs** (body, table cells, headers, footers) | **alone in its own paragraph**, one above and one below what repeats | the tag's paragraph is **deleted** |
| `{%tr … %}` | **whole table rows** | **alone in its own row**, one above and one below the row that repeats | the marker row is **deleted — including anything else typed in it** |

Which one do I use?

- Repeating or hiding some **words** in a line → plain `{% %}`, all in the same paragraph.
- Repeating or hiding **paragraphs** (bullet points, a stamp, a clause) → `{%p %}`.
- Repeating or hiding **table rows** (line items, a group, a total row) → `{%tr %}`.
- If a plain `{% for %}` / `{% endfor %}` sits in paragraphs or rows of their own, those paragraphs and
  rows **stay behind as blank lines and empty rows** — that blank gap is exactly what `{%p %}` and
  `{%tr %}` exist to remove.

Every example below was rendered with this data, so the result shown is what you get:

```json
{"items": [{"n": "Pen", "q": 2}, {"n": "Book", "q": 1}], "names": ["A", "B", "C"]}
```

#### Plain `{% %}` — inside one paragraph

Type this as **one paragraph**; the tag and what it repeats share the line:

```
Names: {% for n in names %}{{ n }}{% if not loop.last %}, {% endif %}{% endfor %}.
```

Result: `Names: A, B, C.` (`loop.last` is true on the final item, so there is no trailing comma.)

The same works inside a single table cell, for example a cell holding
`{% for it in items %}{{ it.n }} {% endfor %}` → `Pen Book `.

#### `{%p %}` — repeat whole paragraphs

Four paragraphs; the first and third hold only the tag:

```
Before
{%p for it in items %}
- {{ it.n }} × {{ it.q }}
{%p endfor %}
After
```

Result — three kinds of paragraph, no gaps:

```
Before
- Pen × 2
- Book × 1
After
```

With plain tags in the same four paragraphs (`{% for it in items %}` … `{% endfor %}`) the result has an
empty paragraph before every item and one more at the end — that's the difference.

`{%p %}` also works **inside a table cell**, to repeat paragraphs within the cell:

```
{%p for it in items %}
{{ it.n }} × {{ it.q }}
{%p endfor %}
```

#### `{%tr %}` — repeat table rows

Three rows; the first and last hold only the tag, the middle one repeats. Type each line in the
cell shown:

| Row | Cell 1 | Cell 2 | Cell 3 |
|---|---|---|---|
| marker | `{%tr for it in items %}` | | |
| body (repeats) | `{{ loop.index }}` | `{{ it.n }}` | `{{ it.q }}` |
| marker | `{%tr endfor %}` | | |

```
{%tr for it in items %}
{{ loop.index }}   {{ it.n }}   {{ it.q }}
{%tr endfor %}
```

Result — only the body row, once per item:

```
1   Pen    2
2   Book   1
```

Put a **header row above the marker row** (`No.`, `Item`, `Qty`). If `items` is empty the marker and
body rows vanish, and with a header row you still get a header rather than a hollow, row-less table.

A condition can hide rows, inside or outside a loop — here only items with `q > 1` print:

```
{%tr for it in items %}
{%tr if it.q > 1 %}
{{ it.n }}   {{ it.q }}
{%tr endif %}
{%tr endfor %}
```

Result: `Pen   2`. Each of the four lines is its own marker row. A condition on a whole paragraph is the
same with `{%p if … %}` / `{%p endif %}` (see [5.3](#53-conditional-paragraph)).

#### The mistakes that cause trouble

| What you see | Cause | Fix |
|---|---|---|
| a blank line or empty row before/after every repeat | plain `{% for %}` in its own paragraph or row | `{%p for %}` (paragraph) or `{%tr for %}` (row) |
| text typed in a marker row is missing from the output | `{%tr %}` deletes the **whole** row | keep marker rows to the tag alone; put headings in a row above |
| `Encountered unknown tag 'endfor'` although you have one `for` and one `endfor` | `{%p for %}`, the field and `{%p endfor %}` are all typed in **one** paragraph — `{%p %}` replaces the whole paragraph it sits in, so two of them in one paragraph break each other | put each `{%p %}` tag in its own paragraph (three paragraphs: `{%p for … %}`, what repeats, `{%p endfor %}`), or, to repeat words inside one paragraph, use plain `{% for %}` … `{% endfor %}` |
| a table with broken or half-empty rows, no error | opened with one kind and closed with another (`{%tr for %}` … `{% endfor %}`) | open and close with the **same** kind: `{%tr for %}` … `{%tr endfor %}` |
| `Encountered unknown tag 'endfor'` | more `endfor` than `for` (the render-error screen shows the counts) | one `endfor` for every `for`, one `endif` for every `if` |
| `Unexpected end of template` | a `for` or `if` that is never closed | add the missing `endfor` / `endif` |
| the tag prints literally in the output | Word split the tag into several runs (formatting or autocorrect changed mid-tag) | retype it in one go, or paste as plain text; turn off smart quotes |

### 5.2 Repeating table rows

Three rows — marker, body, marker:

| | |
|---|---|
| `{%tr for it in items %}` | |
| `{{ loop.index }}` &nbsp; `{{ it.label }}` &nbsp; `{{ it.qty * it.price }}` | ← repeats |
| `{%tr endfor %}` | |

Data `{"items":[{"label":"Pen","qty":2,"price":1.5},{"label":"Book","qty":1,"price":10}]}`
renders:

```
1   Pen    3.0
2   Book   10
```

### 5.3 Conditional paragraph

```
{%p if status == "paid" %}
PAID — thank you
{%p endif %}
```

With `status = "paid"` the stamp paragraph is kept; with `"void"` it disappears entirely.

---

## 6. Writing other formats

### 6.1 `.xlsx`

Same `{{ field }}` in cells. Loops use plain `{% for %}` / `{% endfor %}` each **in its own
row** — the same three-row shape as docx — but, unlike docx, the marker rows stay in the
output as empty rows, so give them 1 pt height and hide them in the template.

> Do **not** use the `{%- for %}` whitespace-trim form that xltpl's own docs show — the
> loop variable ends up unbound. Plain `{% for %}` works.

| | A | B | C |
|---|---|---|---|
| 3 | `{% for it in items %}` | | |
| 4 | `{{ loop.index }}` | `{{ it.label }}` | `{{ it.line }}` |
| 5 | `{% endfor %}` | | |
| 6 | Total | | `{{ items \| sum(attribute='line') }}` |

Output (rows 3 and 5 are blank/hidden): `(1, 'Pen', 3)`, `(2, 'Book', 10)`, `('Total', None, 13)`.

Things worth knowing:

- A cell containing **only** `{{ it.line }}` is written as a real **number** (so Excel can
  sum and format it). Anything wrapped in text or `"{:,.2f}".format(...)` becomes **text**.
  To keep numbers numeric, leave the cell as a bare `{{ … }}` and set the number format
  (`#,##0.00`) on the cell in Excel.
- `{% if %}…{% endif %}` works inside a cell: `{% if customer.vip %}VIP{% else %}Regular{% endif %}`.
- No charts or images in `.xlsx` templates.
- LibreOffice's own *PDF preview* of Khmer cells is garbled; the `.xlsx` file the API
  returns is correct (details in the engine's docstring).

### 6.2 `.html`

A normal HTML+CSS file with Jinja in it. Rendered with WeasyPrint to PDF/PNG, so use
print CSS (`@page`, `page-break-*`, `@media print`).

```html
<h1>{{ customer.name }}</h1>
<table>
  {% for it in items %}
  <tr><td>{{ it.label }}</td><td>{{ "%.2f"|format(it.line) }}</td></tr>
  {% endfor %}
</table>
{% if customer.vip %}<span class="badge">VIP</span>{% endif %}
```

- **Output is HTML-escaped**: `{{ "<b>x</b>" }}` prints the literal text `<b>x</b>`. Use
  `{{ value|safe }}` only for markup *you* control, never for user data.
- Because loops/ifs are ordinary HTML, there is no special row-tag form — just `{% for %}`
  around whatever you want repeated.

### 6.3 Charts and images (docx only)

A chart or image is still just `{{ field }}` — its *value* in the JSON tells Aksor to draw
it. Full format: [Charts](building-a-report.md#charts-docx-templates-only),
[Images](building-a-report.md#images-docx-templates-only).

```json
{ "sales_chart": {"chart": "bar", "title": "2026", "labels": ["Q1","Q2"],
                  "series": [{"name": "Revenue", "values": [100, 150]}]},
  "logo": {"image_id": "77438b0d3b93", "width_mm": 40} }
```

### 6.4 HTML resources (`resource()`)

An html template can't link to files or URLs — it can only pull in an image or stylesheet
you uploaded to **Resources**, by name:

```html
<link rel="stylesheet" href="{{ resource('theme') }}">
<img src="{{ resource('logo') }}" alt="">
```

Every `href`/`src` must be exactly one `resource('…')` call; anything else (a literal
URL, a relative path) is rejected at registration. At register time you map each name to
an uploaded resource. Rendering never touches the network.

### 6.5 Fonts

A template **names** its fonts; it doesn't carry them (the sample `.docx` files hold no font data). Whatever the
server has installed is what the PDF is drawn with — so a font the server lacks is replaced by another, and line
breaks, widths and the page count change. Check before you rely on a font:

- **See what a template names:** the template's **Placeholders** tab ends with *Fonts it names*, each marked
  **Installed**, **Added** (under Resources → Fonts), **Substituted** (not installed, but a metric-compatible font
  such as Liberation Serif stands in for "Times New Roman", so the layout holds) or **Missing** (no match: the
  renderer picks a default and the layout can change).
- **Add a font without redeploying:** **Admin → Resources → Fonts → Add font** (a `.ttf` or `.otf`; needs the
  `font:manage` permission, which system administrators have). It is installed for the **whole server**: the next render of
  *every* organization's templates that name the font's family uses it — LibreOffice for `.docx`, WeasyPrint for
  `.html`, and charts — with no restart. A template names it by the **family** shown in the list (`Noto Sans Khmer`),
  exactly as Word shows it.
- **Verify it first.** Opening a font shows who made it and which version, how much of the Khmer block it covers,
  whether it has the layout tables Khmer needs (GSUB/GPOS), what its license says (and whether the license forbids
  embedding it in PDFs), a sample you can type into, and **every character it has**, drawn with the font itself. Two files can't both be the
  same family and style, so replacing a font means removing the old one first (Aksor warns if templates still name
  it). A font whose family the server already has is accepted with a warning — which of the two a render uses is up to the
  operating system, so check the result, or give it its own family name.
- **Charts** use the Khmer font plus DejaVu; a chart spec may name another with `"font": "Noto Sans Khmer"`.

Exact files matter: two versions of "the same" font can lay a Khmer paragraph out differently (different glyphs and
line metrics). Keep the version your layouts were designed with, and note where it came from in the *Note* box.

---

## 7. Use cases

Each shows the template content, the JSON, and the result.

### 7.1 A certificate or letter (simple fields)

Template (`docx`):

```
ប័ណ្ណសរសើរ
សូមប្រគល់ជូន {{ recipient.name }}
{{ recipient.title }} · {{ organization }}
ចុះថ្ងៃទី {{ date[8:10] }}/{{ date[5:7] }}/{{ date[:4] }}
```

```json
{ "recipient": {"name": "សុខ ដារា", "title": "Engineer"},
  "organization": "Aksor", "date": "2026-09-30" }
```

Result: `ចុះថ្ងៃទី 30/09/2026` with the name and title filled in.

### 7.2 Receipt / invoice (line items and totals)

Template (`docx`): a header paragraph `Invoice {{ invoice_no }} — {{ customer.name }}`, a
three-row table as in 5.2 with `{{ it.label }}`, `{{ it.qty }}`, `{{ "{:,.2f}".format(it.qty * it.price) }}`,
and below it:

```
Total: {{ "{:,.2f}".format(items | sum(attribute="line")) }} USD
```

```json
{ "invoice_no": "INV-0042", "customer": {"name": "Dara"},
  "items": [{"label": "Pen", "qty": 2, "price": 1.5, "line": 3.0},
            {"label": "Book", "qty": 1, "price": 10, "line": 10}] }
```

Compute the `line` per row in your JSON (or in the cell with `it.qty * it.price`) —
`sum(attribute="line")` only adds up a key that exists in each item. Working copies:
[`examples/report_templates/receipt.docx`](../examples/report_templates/receipt.docx),
[`invoice.docx`](../examples/report_templates/invoice.docx),
[`invoice.xlsx`](../examples/report_templates/invoice.xlsx).

### 7.3 A section that appears only sometimes

```
{%p if status == "paid" %}
PAID — thank you
{%p endif %}
{%p if status == "due" %}
Payment due by {{ due_date }}
{%p endif %}
```

Only the matching paragraph survives; the other leaves no blank line.
Inline variant: `Customer type: {% if customer.vip %}VIP{% else %}Regular{% endif %}`.

### 7.4 Optional fields that may be missing

```
Phone: {{ customer.phone | default("—", true) }}
Fax:   {{ customer.fax | default("—", true) }}
Branch: {{ branch.name if branch else "Head office" }}
```

`default(..., true)` also catches `null` and `""`, which is what an API usually sends for
"no value". Use the `if branch` form when the whole parent object may be absent.

### 7.5 Grouped data (a loop inside a loop)

Four marker/body rows: outer-for, group row, inner-for, detail row, inner-endfor, outer-endfor.

| |
|---|
| `{%tr for g in groups %}` |
| `{{ g.name }}` … `{{ g.subs \| sum(attribute='v') }}` ← group row with subtotal |
| `{%tr for s in g.subs %}` |
| `{{ s.n }}` … `{{ s.v }}` ← detail row |
| `{%tr endfor %}` |
| `{%tr endfor %}` |

```json
{"groups": [{"name": "A", "subs": [{"n": "a1", "v": 1}, {"n": "a2", "v": 2}]},
            {"name": "B", "subs": [{"n": "b1", "v": 5}]}]}
```

Result:

```
A      3
  a1   1
  a2   2
B      5
  b1   5
```

A real production layout using this is
[`revenue-comparison.docx`](../examples/report_templates/revenue-comparison.docx).

### 7.6 Row numbers and running totals

`{{ loop.index }}` numbers rows from 1; `{{ loop.first }}` / `{{ loop.last }}` let you style
or skip. For a total *after* the loop use the `sum` filter (7.2). For tables long enough to
be split across several files, use `{{ row_offset + loop.index }}` so numbering continues
— see [Template variables](building-a-report.md#template-variables).

### 7.7 A chart in a report

Put `{{ sales_chart }}` where the chart should sit and send the chart spec as that field
(6.3). Bar, line and pie are supported; docx templates only.

### 7.8 A spreadsheet export with totals (xlsx)

Rows 3–5 as in 6.1, a header row above with plain labels, and a total cell. Make the
numeric cells bare `{{ it.line }}` and apply `#,##0.00` in Excel so recipients can still
sort and sum. Register as `.xlsx`; request `format=xlsx`.

### 7.9 A styled print layout (html)

Use `.html` when you want CSS — e.g. a two-column ID card with a badge:

```html
<style>@page { size: 90mm 55mm; margin: 4mm } .badge{background:#2b6;color:#fff;padding:1mm 3mm}</style>
<img src="{{ resource('logo') }}" height="12">
<h2>{{ name }}</h2>
{% if role %}<span class="badge">{{ role }}</span>{% endif %}
```

Map `logo` to an uploaded image when registering. `format=pdf` or `png`.

### 7.10 One document per record (mail merge)

Same template, many contexts — post a JSON **array** to
`/reports/<id>/render/batch?format=pdf` and get a ZIP with one file per record. Limits
(30 PDF/PNG, 1,000 docx/xlsx per request by default) in
[Rendering many contexts at once](building-a-report.md#rendering-many-contexts-at-once).

### 7.11 Report that asks the user for filters

Placeholders can also be fed by **Parameters** (what the run form asks for) and a
**Data source** (where the server fetches the rest): filter `fromDate` → `{{ fromDate }}`
in the template. Setup in
[Filters, a data source, and connections](building-a-report.md#filters-a-data-source-and-connections).

---

## 8. Testing a template before you integrate it

1. **Placeholders tab** — compare the detected fields with what your data will send.
   (It's a best-effort scan: docx via docxtpl's own parser, xlsx by regex.)
2. **Preview tab** — two modes. **Sample data**: paste JSON, render, fix, repeat; **save** the good one as the
   sample payload so the Integration tab's snippets are ready to run. It skips the filters and the data source, so it
   is for laying the template out. If the report has filters or a data source, the tab opens on **Live run**: choose
   the filters and run it exactly as the people who open it will (same route, same data source, same defaults and
   required filters) — use this to test a report that fetches its own data. A live run uses the *saved*
   Parameters and Data source, so save them first.
3. **Try every branch** — render once with each `if` taking each path, once with the
   optional fields missing, once with an empty list.
4. **Try long data** — a very long Khmer paragraph and a table past one page.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `'x' is undefined` on render | You read `x.something` and `x` wasn't sent. Guard with `{{ x.y if x else "" }}` or send an empty object. |
| `{{ field }}` shows up literally in the output | The tag was split by Word formatting or autocorrect. Retype it in one go; keep one font style across it. |
| Curly quotes break an expression | Turn off smart quotes; Jinja needs straight `"` / `'`. |
| Table prints a stray blank row | A plain `{% for %}` was used across rows instead of `{%tr for %}`, or a marker row isn't alone in its row. Anything else typed in a `{%tr %}` marker row is thrown away. (xlsx: hide the marker rows.) See [5.1](#51-loops-and-conditions---p--and-tr-). |
| Loop prints nothing | The field isn't a list, or is empty. Check the JSON key name and case. |
| xlsx numbers can't be summed | The cell mixes text with `{{ }}` or uses `.format()` → text. Use a bare `{{ x }}` and format the cell in Excel. |
| xlsx loop variable is unbound | You used `{%- for %}`. Use `{% for %}`. |
| Khmer wraps badly in a table cell | Set the cell/paragraph to justify + a Khmer font; see [khmer-line-breaking](khmer-line-breaking.md). |
| Khmer word split in the wrong place | Add it to a [protected-terms](protected-terms-guide.md) set. |
| html: `{{ x }}` shows `&lt;b&gt;` | Output is escaped on purpose. `\|safe` only for markup you control. |
| html: registration rejects an `href`/`src` | Must be exactly `{{ resource('name') }}`; upload the asset and map it. |
| `400 … not a valid .docx/.xlsx` | Wrong extension or a corrupt/renamed file — re-save it from Word/Excel. |
| `409` on register | The code is taken by another template. |
| Version label rejected | Letters, digits and `. - _ +` only, ≤ 32 chars, and unique per template (`409` if reused). |
| Format not offered / `400` on render | xlsx → only xlsx; html → only pdf/png; charts and images are docx-only. |

---

## 10. Authoring checklist

- [ ] Placeholders typed in one go; straight quotes
- [ ] Every loop/if has its matching `endfor` / `endif`, in the right kind of row/paragraph
- [ ] Optional nested fields guarded with `if` or `default`
- [ ] Money/number formatting decided (`"{:,.2f}".format(...)` or cell format in xlsx)
- [ ] Dates formatted by slicing, or sent pre-formatted
- [ ] Khmer font set; long Khmer text tested
- [ ] Registered with a **code** if anything integrates with it
- [ ] Filed in the right **folder** (add a shortcut if it belongs under more than one)
- [ ] Sample payload saved; every branch previewed
- [ ] A version note written whenever you replace the file
