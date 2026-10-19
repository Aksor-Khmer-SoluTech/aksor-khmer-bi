# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **The portal opens faster.** Its JavaScript was one 1.5 MB file that every visit downloaded whole; each page is now
  fetched when it is first opened, so the first load downloads under a third as much. React, the code editor and the
  icons have their own files, which a release that changes only the portal's pages leaves in the browser's cache.
  The portal image's web server now compresses JavaScript, CSS and fonts (gzip) and lets browsers keep the built
  files for good (their names change whenever their content does), while `index.html` and `config.js` are checked on
  every load, so an upgrade or a changed `PORTAL_*` setting shows straight away. A tab left open across an upgrade
  reloads itself once instead of failing to open its next page.

### Fixed
- **LDAP users whose directory group maps to a role can sign in on PostgreSQL.** The group sync recorded the roles it
  gives with `granted_by = "ldap-sync"`, but that column holds the id of the user who made a grant, and PostgreSQL
  refused the value: the sign-in failed with a server error. Synced roles now say where they came from in a column of
  their own (`source = "ldap"`); a database migration moves any already written that way. A new test runs the sync
  everywhere, not only where a test directory server is running.

### Security
- **Organizations' reports and Resources are kept apart.** An organization's own admins (`report:manage` /
  `folder:manage` -- the Org Admin and Report Admin roles) could reach another organization's folders, images and
  stylesheets by id -- view, download, rename, move, replace and delete them -- and could grant themselves access to
  another organization's report or folder, which then opened it fully. Each of these now answers 404 outside the
  caller's own organization, like an id that doesn't exist. Server-wide administrators are unchanged, and so is
  access given by a grant on the report or folder itself.

## [1.0.0-beta.7] - 2026-10-17

### Fixed
- **PDF previews show again on installed servers.** The portal's web server sent the PDF viewer's worker file
  (`pdf.worker.min-….mjs`) as `application/octet-stream`, which browsers refuse to load as a script, so a preview
  failed with "Setting up fake worker failed: Failed to fetch dynamically imported module". The portal image now
  serves `.mjs` files as JavaScript. (It worked in development, where Vite serves the file itself.)

## [1.0.0-beta.6] - 2026-10-17

### Fixed
- **New reports save on PostgreSQL again.** Creating a report -- a draft from the New report wizard ("Next" after the
  data), an uploaded template or an imported project -- failed on every PostgreSQL install with
  **409 "That code is already taken"**, even with no code given and no reports at all: the report's first version was
  written before the report itself, which PostgreSQL's foreign key refuses (SQLite, used in development, doesn't check
  it). The report is written first now, and any other database error is reported as itself instead of as a taken
  code. The tests now check foreign keys too, so this can't come back unnoticed.
- **`./deployment.sh up` starts the JDBC worker** whenever `JDBC_WORKER_TOKEN` is set in `.env` -- before, it never
  did, and uploaded Oracle / SQL Server / Db2 drivers had nothing to run them unless the worker was started by hand
  with its compose profile. `update`, `status`, `restart` and `logs` include it too, `down` always stops it, and `up`
  warns when drivers are uploaded but the token isn't set.

## [1.0.0-beta.5] - 2026-10-16

### Added
- **Right-click a folder in Resources** for its actions at the pointer -- New subfolder, Rename, Manage access, the
  project options and Delete (the same list as its "…" menu); right-click Root for New folder. The menu doesn't open
  the folder: what's showing stays, and the folder is outlined while its menu is open. **F2** renames the
  selected folder, and renaming starts with the whole name selected, so typing replaces it.
- **Resources loads a big folder fast.** Image cards show a small preview from the new
  `GET /api/v1/images/{id}/thumbnail` (WebP, made once and kept beside the picture, remade when it's replaced; the
  same visibility as the picture) instead of downloading every original -- in a test folder 41.5 MB of scans became
  454 KB. Previews load only as their cards come near the screen and are kept for the session, so going back to a
  folder shows them at once. While loading, one light band sweeps across every card in step (moved by the GPU, not
  repainted); each picture is decoded first, then crossfades in over the shimmer with a slight settle.
- **Smaller cards in Resources:** about a third more fit on a row (two on a phone), with a smaller preview and type.
- **Resources stays quick with hundreds of files in a folder.** Cards outside the scrolling column aren't laid out
  or painted until they come near (`content-visibility`), the lists are grouped by folder once instead of filtered on
  every render, and cards redraw only when their own data changes -- opening a folder of 360 cards went from about
  310 ms of work to 25-45 ms.
- **Stored procedures are called from the SQL box, on any database, with nothing to set up first** -- as in Jasper or
  BI Publisher: `EXEC dbo.GetSales @branch = :branch, @title = N'ខ្មែរ'` on SQL Server, `CALL hr.get_sales(:branch,
  50)` on Oracle, MySQL, MariaDB, Db2 or PostgreSQL. The connection's database login decides what may run; the
  connection's **Procedures** list and dialog are gone. Saving checks the form so a filter's value can't become SQL --
  one call and nothing after it, a plain schema.name, arguments only filters, numbers, 'text', NULL (DEFAULT in an
  EXEC) -- and every run rebuilds the call with each filter and text value bound. A procedure's further result sets can
  be named on SQL Server, Oracle and Db2. Cards made by the earlier picker keep running and open as the equivalent
  EXEC. **Upgrade note:** a procedure runs with the rights its database gives it, so make the connection's login one
  that may only read and execute what reports need.
- **A user at a glance**, in **Users**. A user now opens in a large window over the list (full screen on a phone)
  instead of expanding inside the table: Esc or a click outside closes it, and the address (`#/admin/users?user=<id>`) links straight to them. A strip at the top shows the templates they uploaded (how many
  they started, how many versions, by file type), how many templates they can open and at what level, and their
  roles. A new **Templates** tab lists each template with its folder, their versions, the last upload and the access
  they hold now -- flagging one they uploaded but can no longer open. **Roles & permissions** now maps every
  permission by area, held or not, with where each comes from (a role, or a direct grant, and when it ends), and
  lists the folders and templates they were granted, with how many templates each folder covers. Counted with the
  same rule as their own Reports page. New route `GET /api/v1/users/{id}/overview` (`user:manage`).
- **Granting from a user's window, clearer.** Their **Roles & permissions** tab now only lists what they hold (each
  grant still revocable), and **Grant access…** opens its own dialog with three kinds: **a role**, picked from cards
  that say what each is for and what it would add for this person (“+4 new”, then the exact permissions), with roles
  they hold marked; **a template** -- view, render or manage, optionally until a date -- without a role
  (`report:manage`); or **a permission**, searchable, each with its description. A template granted to them directly
  can be revoked from **Where they have access**.
- **Roles open in a window too.** In **Roles**, a role now opens in the same large window as a user (linkable:
  `#/admin/roles?role=<id>`) instead of expanding in the table. Its permissions are grouped by area, with an all/none
  switch per area; what you tick or untick is marked, and a bar at the bottom counts the changes (+added / −removed)
  with Save and Reset. Closing with unsaved changes asks first. The list shows readable names and what each built-in
  role is for.
- **Grant the system-wide Administrator role from the portal.** A superuser now finds it in a user's
  **Grant a role…** list, under *System-wide*, after a confirmation that spells out what it gives (every permission,
  in every organization); an expiry date works as for any role. It was only reachable through the API before -- it
  belongs to no organization, so the list never showed it. Everyone else still isn't offered it, and the API still
  refuses them.
- **Install and update without the repository.** Each release now publishes an *install kit* -- `deployment.sh`, the
  compose files, `.env.example` and a `config/` folder, a few dozen KB -- so a server needs Docker and nothing else:
  `curl -fsSL …/install.sh | bash` installs the newest release (checksum checked), `./deployment.sh update` (or
  `update 1.2.0`, or `update --from <kit>` without internet) backs up and moves to a new one, and
  `./deployment.sh rollback` goes back, with `--restore` to put back the database too. Git checkouts keep working
  (`git pull`, then `update`); `./deployment.sh switch-to-kit` moves one over. The portal's API address and branding
  are now `.env` settings (`PORTAL_API_BASE_URL`, `PORTAL_BRAND_NAME`…), or a `config/portal/config.js` of your own;
  your own protected-term lists go in `config/protected-terms/` and `config/protected-terms-exclude/`.
  **Upgrade note:** needs this release's images (the portal writes its config at start). An edited
  `PORTAL_CONFIG_FILE` and edited protected-term lists under `api/` are copied into `config/` by `deployment.sh`
  the first time it runs; if you start the stack with `docker compose` yourself, copy them there first.
- **Stylesheets in SCSS, Sass and Less**, not only CSS, compiled on upload (the template always gets CSS) with the
  source kept: its card shows the source beside the compiled CSS, *replace* takes any of the four formats, and a
  project carries the source. Compile errors give the line and column. Each file must be self-contained -- `@import`,
  `@use` and `@forward` are refused, since an import could read files on the server. Stylesheets now also have a place
  in **Manage → Resources**: upload into any folder, view, replace, delete, with the "already here" notice images have.
- **Projects: move templates between servers as one package.** Mark a top-level Resources folder as a project, then
  **Export** it: its templates, images, stylesheets and subfolders, with version history, data sources, fonts and
  protected-term sets, plus the shared files it uses — each of which you may leave out when the other server already
  has it. **Import** shows what will happen to every item first: identical files are linked (never copied again),
  a file with the same name and other content is yours to overwrite, keep both or keep as is, and templates already
  in the project (same code, else same name) get a new version instead of a copy. Secrets never travel; missing
  connections, secrets and datasets are listed. A failed import undoes what it created. New permission
  `project:transfer` (Org Admin and Report Admin). Uploading an image or stylesheet that is already here now says
  where, so the same file isn't kept twice by accident.
- **QR codes and barcodes from a value**, in Word, Excel and HTML templates: `{{ qrcode(invoice_no) }}`,
  `{{ barcode(invoice_no) }}` (Code 128), `{{ barcode(sku, "ean13") }}` or `"code39"`, with `width_mm` (and a
  barcode's `height_mm`), a QR error
  correction `level` and `text=true` to print the value under a barcode. Any field, filter or row column works — no
  upload first. HTML gets a sharp SVG (`<img src="{{ qrcode(…) }}">` is now allowed); Word and Excel get a picture,
  in Excel anchored at the cell. The JSON can also ask for one (`{"barcode": "code128", "value": "…"}`). A value
  that can't be drawn (a wrong EAN-13 check digit, Khmer in a Code 39) fails the render with the reason. Khmer in
  QR codes is supported. No migration; the new libraries come with the images. The guide shows a sample of each
  supported type (Charts, images and data → Barcodes and QR codes → Supported types), and guides can now show
  pictures in the portal.
- **Statistical measures** (Phase 5a). A dataset's measures can now be a *Median*, a *Percentile* (choose which,
  0–100), a *Standard deviation*, a *Variance* or the *Most common value* of a field, besides sum, count, average and
  the rest. They work wherever measures do: report templates (`{{ measures.<key> }}`), Analyze pivots and charts,
  dashboard tiles and data alerts — "tell me when the median sale drops below 30,000 ៛". They follow Excel's
  `PERCENTILE.INC`, `STDEV.S` and `VAR.S`. Existing datasets are unchanged; no migration.
- **Statistics in Analyze** (Phase 5b). *Show value as* a percentage of the total, of the row or column total, a
  running total, or the change (or % change) from the previous row or column. *Ranges*: group a number field into
  ranges of a width you choose or one chosen for you, empty ranges kept — a histogram. *Trend line* down one row
  field, with its slope per period and R², a moving average and a forecast of up to 12 periods (missing months count
  as gaps). *Outliers* by z-score or interquartile range, shaded in the table and outlined on the chart. They carry
  into exports, saved views and dashboard tiles. A **data alert** can now email when one group *stands out* — any
  branch whose sales are unusually high or low — instead of crossing a fixed threshold. No migration.
- **Report jobs email their files, and split them into one file per value** (bursting, as in Oracle BI Publisher).
  A job's new *Where it goes* section saves the report to a folder, emails it, or both; *One file per value* splits
  it by a filter with a list of choices — one run, one file and one set of recipients per branch, say, each with
  only that branch's data. The subject and message fill in `{{ report }}`, `{{ date }}` and each filter (with its
  label), Khmer included; a value with no data can be skipped rather than mailed empty. Every value you split by
  is checked against your own access when you save, so a job never sends data its creator couldn't run.
- **Mail servers** under Manage → Connections (*New Mail Server*), with presets for Google Workspace, Microsoft 365
  and any SMTP server, the password kept as a Secret, and *Send a test email*.
- **What each run sent:** a job's Run history opens each run's files — who each went to, sent / saved / failed
  (with the mail server's reason) / skipped — and *Re-send the ones that failed* sends them again with the very
  same file, kept on the server for `JOB_OUTPUT_DAYS` (30) days. A run where nothing went out and the cause may
  pass (the database or mail server down) is retried with the job's retry settings; once something went out it
  isn't, so nobody gets the same file twice.
- **Datasets** (Manage → Datasets): a source and its filters defined once, with what each field means (type,
  English and Khmer label, format, hidden) and named **measures** — sum, count, count distinct, average, minimum,
  maximum (optionally *only where* a field equals a value) and ratios — each with a format such as `#,##0 ៛` or
  `0.0%`. *Run it* finds the fields and shows each measure's value. A report built on a dataset (Data source →
  *A dataset*) asks for its filters and gets `{{ measures.<key> }}` (formatted) and `{{ measure_values.<key> }}`
  (numbers) besides the data; a change to the dataset reaches all of them on their next run. *Save this report's
  data as a dataset* turns an existing report's source into one. New permission `dataset:manage`, given to
  `ROLE_ORG_ADMIN` and `ROLE_REPORT_ADMIN`.
- **Who gets which rows, per dataset** (a dataset's *Access* tab). Restrict a dataset to the people and roles it
  lists, each with *Run its reports* or *Build & run* and, per filter, all values or only some (say Siem Reap staff:
  `សៀមរាប (BR02)` only) — for every report built on it, on top of each report's own grants: both must allow a value.
  Open is the default, so existing datasets behave as before; revoking the last grant never opens one back up.
  Dataset grants show in Access Review, and every change is audited.
- **Upgrade note:** migrations `0007_job_deliveries` and `0008_datasets` run at start-up. `docker-compose.yml` mounts a new
  `data/job_outputs` folder on `api` and `worker` — run `./deployment.sh update`, which creates it.

### Changed
- **Manage → Resources is simpler.** One **Upload** button takes images and stylesheets together (several at once,
  or dropped onto the folder); chips filter the folder to templates, images or stylesheets; each card has one "…"
  menu. Clicking an image or stylesheet opens its details: the exact line to use it in an html template, its
  `image_id` for a Word template's data, which templates already use it, and Replace, Rename, Move and Delete. Images
  and stylesheets can now be moved between folders (also by dragging them onto the tree), and an image replaced
  while keeping its id.
- **Top bar in a clearer order**: what there is to look at — *Home, Reports, Dashboards, Analyze* — then, after a thin
  divider, what's your own — *Starred, My runs*. On phones the pages show as icons, so all six fit; the guided tour
  follows the same order and now stops at Dashboards and Analyze too.
- **Analyze has its own place in the top bar**, next to Dashboards, for everyone who can analyze datasets
  (`analyze:use`). Before, it was only reachable through Dashboards → *Explore data*.
- **Dashboards** (top bar): Analyze views as tiles on one page — tables, bar and line charts, or a single big number
  (KPI) — with the filters they share across the top (one *Branch* for every tile that has it). Owners add tiles from
  Explore data, then rename, resize, reorder and **share** them with roles; viewers don't need `analyze:use`, and
  each sees every tile with their own access (a restricted dataset still only gives them their values). Changes are
  audited. The top bar's *Analyze* became *Dashboards*, with *Explore data* inside it.
- **Data alerts**: from Explore data, *Alert me* emails when a measure drops below or rises above a threshold, checked
  hourly, daily, on weekdays or on Mondays — once when it crosses, not again until it recovers. It's a new job type
  (*Data alert*, under Manage → Jobs) whose run history shows the value each check saw; it may only watch what its
  creator could analyze.
  **Upgrade note:** migration `0010_dashboards` runs at start-up.
- **Analyze** (top bar): slice a dataset into a pivot — fields in rows and columns (a date grouped by day, month or
  year), measures in values — as a table with totals or a bar or line chart, Khmer labels throughout. Measures are
  worked out per cell, so a ratio is right everywhere. The data is fetched once per filter set and kept five minutes,
  so re-arranging answers at once. **Export** as PDF or Word (title, filters, chart and table, Khmer shaped and
  wrapped) or Excel (numbers kept as numbers, in each measure's format); exports are audited. **Save view** keeps a
  layout under its own link, private to you. New permission `analyze:use`, given to `ROLE_REPORT_ADMIN` and
  `ROLE_ORG_ADMIN`; a restricted dataset still only gives its grants' values.
  **Upgrade note:** migration `0009_analyses` runs at start-up.
- **Stored procedures and functions (SQL Server).** A connection manager approves what reports may call — under
  Manage → Connections → *Procedures*, with **Discover** listing what the connection's login may run (and warning
  when that login could also change data) — and a query card switches to *Procedure / function*, picks one and gives
  each parameter a filter or a fixed value. A procedure's several result sets each get a name (a header and its
  lines from one call); table-valued and scalar functions work too. The call is built on the server from the
  approved name with every value bound, and approval is checked on every run. Datasets get it too.
  **Upgrade note:** procedures run in the JDBC driver service — update its image with this release (an older one
  answers with a clear "too old to call stored procedures").
- **A query can read its own database.** For data spread over several databases (a service each), each query card
  of a database source has a *Database* of its own; the top connection becomes the default the others use. The
  queries still run side by side and merge into one object, each on its own database with that connection's login
  (an uploaded driver gets one request per database), and an error names the query and its connection. Datasets get
  it too, since they share the editor. A connection any query uses can't be deleted. Existing reports are unchanged.
- **When a data source fails to run, it says so where you're looking.** In the New Template wizard and a dataset's
  *Run it*, a failed run of sample data, a REST API or a database now shows in place of the data, under the Run
  button (not in a banner at the top of the page): a heading that names the problem (couldn't connect, the API
  answered HTTP 404, the database rejected the query, it took too long, too much data, the sample isn't valid
  JSON…), the server's own message, what to check, and *Try again*.
- **Ctrl+P (⌘P on a Mac) prints the report** when one is showing in the report viewer: it does what the toolbar's
  Print button does (the button flashes), instead of printing the portal page around the report. Before a report
  has rendered, the browser's own print works as before.
- **Questions and answers.** The Guides home now opens on the questions people ask most — 33 of them, in eight
  categories (templates, Khmer text, data and datasets, output, schedules and email, sign-in, running the server) —
  each opening in place with a short answer and a link to the section that explains it fully. The common ones are
  one click from the search box. They're a guide of their own too (`docs/faq.md`), so search finds them and GitHub
  shows them.
- **Guides are easier to find your way in.** *Guides* opens on a home page: a search box, a card for each topic
  (looping, formatting, missing data…) with its links, and the guides by what they're for. Search results are
  grouped by guide (a few each, *Show more* for the rest), matching topics come first, and snippets read as text
  rather than raw Markdown. Arrow keys and Enter work from the search box; Esc goes back.
- **New user** (and a user's Profile, and your own in Settings) marks what's required and counts characters:
  username required, up to 100 (no `|`, which separates name and organization at sign-in); email optional, up to
  254 and checked to look like an address; display name optional, up to 100. The API enforces the same — before,
  any length was accepted. Existing accounts are untouched.
- The browser tab names the page: **Aksor Khmer · Home**, **· Reports** (a report's run page too), **· My runs**,
  **· Starred**, and **Aksor Khmer · Control Plane** in Manage; signed out, just **Aksor Khmer** (was *Aksor Khmer ·
  Control Plane* everywhere).
- A database source's query cards name their shapes **List / Object / Single value** (were *List / One row / One
  value*), each with an icon: `[ ]`, `{ }` and `#`.
- A report built on a dataset can be limited by filter value from its own Access Privilege tab too (the dataset's
  filters are offered there; before, that list was empty for such a report).
- Several queries in a database source can be put in order by dragging a card's handle (or with the keyboard:
  space, then the arrow keys), or with each card's up and down arrows when there are many.

### Fixed
- **Resources:** a folder's "…" menu was cut off by the folder tree's own box (only its first item showed), and a
  file card's "…" menu was cut off by its card and hidden under the next row; both now open on top of the page, like
  the right-click menu. The cards no longer scroll sideways under the folder tree. The page now fills the window
  exactly, above the footer: the folder tree runs to the bottom even beside an empty folder, each column scrolls on
  its own, and the page itself no longer scrolls (on a phone the two stack and scroll as one page).
- **New template, sample data**: pressing *Use this data* with the editor empty no longer says the data "isn't valid
  JSON" — it asks you to paste some (or press *Insert example*); invalid JSON is reported once, under the editor,
  instead of twice; and the editor's placeholder now reads as an example, not as data already entered.

**Upgrade note** — migrations `0011_projects` (a project flag on folders, a content fingerprint on images and
stylesheets) and `0012_stylesheet_formats` (a stylesheet's source format). Docker installs run them on start; a
hand-run API needs `alembic upgrade head` and `pip install -r api/requirements.txt` (the Sass and Less compilers,
`libsass` and `lesscpy`, are new; the images include them).
- Searching the guides kept the open guide's scroll position, so results started part-way down with the count out
  of sight; they now start at the top, and clearing the search puts the guide back where you were. Opening a result
  lands exactly on its heading (it used to stop short while code blocks finished drawing) and highlights it.
- Clearing your email or display name in Settings → Profile (or an administrator clearing a user's) didn't stick:
  the empty field was sent as "no change".
- A job's Run history table inside the expanded job showed squashed, tinted cells: the expanded row's styling
  leaked into tables inside it.
- Deleting a job now removes its run history with it, instead of leaving it (or failing on PostgreSQL, whose
  foreign keys refuse to orphan the runs).

## [1.0.0-beta.4] - 2026-10-11

### Added
- **Excel (tables)** for `.docx` reports: the run page's Export menu (and the API, embeds, jobs and batches with
  `format=xlsx`) gives the report as a workbook that reads like it — a sheet per table (or per page, when the
  template has page breaks, as in Oracle BI Publisher), named after the heading above it; the title and lines around
  each table come along; numbers are real numbers *and* keep their look (`1,240.00`, `12.5%`, `(1,240.00)`); the
  table's look comes too — fonts, colours (theme colours included), cell shading, Word's built-in table styles
  (header and banded rows), mixed formatting within a cell, alignment, real merged cells, borders and column widths —
  with a frozen, filterable header row. Images aren't copied; for a spreadsheet designed cell by cell, use an
  `.xlsx` template.

- **Several queries in one database source.** A report's database source can have up to 10 queries — line
  items, a receipt's header, a count — each named, and each a *list*, *one row* or *one value*. They run at the
  same time and are merged into one object the template reads (`{{ info.receiptCode }}`, `{%tr for r in rows %}`),
  every name always present: no row is `null` (an empty list is `[]`). One failing query fails the run and is
  named. In the Data source tab and the New Template wizard, **Add query** turns the one query into cards — each
  with its result name, List / One row / One value, its SQL and its own filter buttons; the wizard's Run shows the
  one-row and one-value results above the table of rows. A source with one query is
  saved and runs exactly as before. On an uploaded driver (Oracle, SQL Server, Db2) a report's queries go to the
  jdbc-worker as **one request** — one JVM, one connection — instead of a JVM each. **Upgrade note:** update the
  `jdbc-worker` image with the others; an older worker still works, the queries are then sent one by one.

### Fixed
- New Template's starter no longer adds a Total under identifier columns (card numbers, ids, codes) — only under
  amounts.
- Typing Khmer (or any non-ASCII character) into the sign-in form — say, with the keyboard still in Khmer — failed
  with a server error instead of "Invalid credentials"; a two-factor code typed in Khmer digits did the same.
- **Scheduled cron jobs never ran:** the scheduler crashed building a cron trigger, and since one bad job stopped
  the whole pass, interval and one-off jobs stopped with it. Cron weekdays are now read the crontab way too —
  `1-5` is Monday to Friday (it would have been Tuesday to Saturday).
- A scheduled **Render report** job rendered only the JSON typed into it: a report fed by SQL, a JDBC database or
  a REST API came out empty. It now runs the report like its Run button (see Changed).

### Changed
- **New job, redone.** A *Render report* job is a form: pick the report and format, set its filters (the run
  page's own — a date left empty is the day the job runs), and where the file goes; each run fetches the report's
  data from its data source. Extra JSON is optional, laid over the fetched data. The schedule is picked in words —
  every hour, every day, weekdays, chosen days of the week, a day of the month, or a custom cron expression — with
  the next three run times shown as you choose. The report and filter values are checked against your own access
  when you save. The other job types keep their JSON, now in the JSON editor.
- **Scheduled jobs run in `REPORT_TIMEZONE`** (UTC when unset) — set it to `Asia/Phnom_Penh` and a job for 08:00
  runs at 08:00 in Phnom Penh. **Upgrade note:** a cron job already scheduled keeps its expression, which is now
  read in that zone.
- **The run page fits the window:** the report viewer, the footer and an even 24px margin around them, with no
  scrolling — so the Run panel stays level with the viewer instead of drifting when the page scrolled.
- **Templates' two buttons are New Template** (start from your data, in the wizard) **and Upload Template** (a file
  you've already designed) — were *New report* and *Register template*, which read like two names for the same
  thing. The upload dialog is titled to match, and the wizard's "already have a template?" link opens it right there. Both now sit
  top right in the page header, like every other page's actions.
- Connections' buttons read **New Database** and **New REST API** (were *+ Database* / *+ REST API*), with icons.
- **Upload driver** names the driver after the chosen file (`mssql-jdbc-13.6.0.jre11`) unless a name was typed, and
  refuses a `-sources` or `-javadoc` jar straight away, pointing at the driver jar beside it.
- In the database connection dialog the **JDBC URL** sits right under Database and Organization — the fields it's
  built from — instead of after Security and Driver.
- **Sample data is edited in a real JSON editor** (the SQL editor's look): line numbers, folding, coloured keys and
  values, matching and auto-closing brackets, Tab to indent — in New report and a report's Data source tab.
- **New report:** Name and Folder side by side, Description full width below them; Name and Description show how
  many characters are left, like Code. The page uses the full width, and what a source returns is shown below its
  settings at full width, so a query's columns have room.

## [1.0.0-beta.3] - 2026-10-10

### Changed
- **New navigation.** Everyday pages — Home, Reports, My runs, Starred — are links in the top bar, and people who
  only run reports no longer see a sidebar. The **Admin** button is now **Manage**: it appears only for someone with
  something to manage (templates, schedules, data sources, users…), and opens a sidebar grouped into Authoring,
  Scheduling, Data sources, People & access and Operations, showing only the pages that person can use. Manage's "Back to …" returns to the page you opened it
  from (Home if you came straight in), and the logo now goes to Home. The product name ("Control Plane") shows in the top bar only on Manage
  pages. Templates,
  Batch render and Schedules moved there from the old sidebar. The admin Dashboard is now for people who can view the
  audit log or manage settings, rather than everyone.

### Added
- **A short guided tour** the first time someone opens Home (the top-bar pages, Home's cards, notifications, the guides,
  Manage, their account) and the first time they open Manage (its groups, Templates, data sources, people, the
  way back). Each stop highlights the thing it explains; **Skip tour** or Esc ends it, and it's remembered on the
  account so it doesn't come back. Steps for things a person can't see are left out. **Show me around** in the
  account menu plays it again.
- **New report — start from your data** (Templates → New report). Choose a data source (sample JSON, a REST API
  or a database query), press **Run** and see exactly what it returns; the filters it uses (`:month`,
  `{{ month }}`) become the report's filters by themselves. Then every field is listed with its type and an
  example — click one for the exact placeholder (a list gives the whole table-row loop) — and Aksor writes a
  **starter template** (.docx, .xlsx or .html) with every field already placed, totals included, to restyle.
  Upload your design and it's **checked against the data**: a placeholder that names nothing is flagged with the
  nearest real field (the typo), and unused fields are listed. Preview it with real data, then **Publish**.
  Until then the report is a **draft**, seen and run only by people who manage it. *Register template* still
  takes a finished file and publishes it at once. **Upgrade note:** adds a database migration
  (`0006_report_drafts`), applied automatically at start-up; existing reports are published.
- **My runs** (`#/runs`): every report you've run, newest first, each one a click from running again — backed by
  `GET /api/v1/me/runs?limit=` (your own runs only, up to 200).
- **Starred** (`#/starred`): the reports you starred, on their own page.
- **New sign-in alerts you can act on.** When your account signs in on a browser it hasn't used before, the bell
  asks your other signed-in browsers *Was this you?* — **It was me**, or **Not me**, which signs that device out
  and offers to change your password and review your sign-in activity. The new browser itself never sees the alert.
  Browsers are now recognised by a device cookie rather than IP address + browser version, so a new network or a
  browser update no longer counts as a new device, and an account's first sign-in raises no alert. Each person can
  still turn alerts off under Settings → Notifications. **Upgrade note:** adds a database migration
  (`0004_signin_device`), applied automatically at start-up.

### Fixed
- **Dates, amounts and IDs reach templates exactly as sent.** Khmer word-breaking used to add invisible
  separators to *every* string — `2026-09-02` became `2026​-​09​-​02` — so the guide's own date recipe
  (`{{ date[8:10] }}`) printed the wrong characters, comparing a value could fail, and `.xlsx` cells held hidden
  characters inside IDs and dates. Only text that contains Khmer (or Thai, Lao or Myanmar) is segmented now;
  Khmer wraps exactly as before.
- An `.html` file can now replace a template's file (it used to need registering as a new template), checked
  like a new html template against the resources the report already has mapped.
- **Resources** no longer has a double margin around it; it lines up with every other Manage page.
- Page action buttons (*+ New credential*, *+ Database* / *+ REST API*, *+ Upload driver*) sit top-right like on every
  other page, instead of dropping under a long page description; JDBC Drivers gets a search box like the other lists.
- **Resources → Fonts → Add font** asks for the optional *source and license* note in a dialog after you pick the
  file, with an example, instead of an unlabeled box you had to fill in before choosing it.
- **Brave was listed as Chrome** in Active Sessions, the sign-in log and new-sign-in alerts: Brave sends Chrome's
  browser identification unchanged, so it's now named from its client hint (https / localhost) or, on plain http,
  by the portal at sign-in. Browser versions show the major number only ("Chrome 152", not "152.0.0.0"), and the
  session list says "signed in 5 min ago · ends in 12 h" (exact times on hover). **Upgrade note:** adds a database
  migration (`0005_browser_brand`), applied automatically at start-up.
- **Active Sessions:** *Sign out other sessions* sits in its own row under the list instead of crowding the first
  session.
- **Two-step verification at sign-in** is clearer: it shows who you're signing in as (click to change account,
  instead of a bare "Back" link), six code boxes that accept a pasted code and sign in on the sixth digit, a wrong code
  clears the boxes ready to try again, and a note on what to do if you've lost your authenticator.
- The file-type filter on the Templates page no longer shows a scrollbar under its chips (Windows browsers drew one).
- **Register a template** is a wide, short dialog instead of one tall stack (one column on a phone): Name and
  Folder beside the file, then Code beside a larger Description box, their labels level; a stray horizontal
  scrollbar in it is gone.

## [1.0.0-beta.2] - 2026-10-09

### Changed
- **The generated admin password is one-time.** At the first sign-in with `PORTAL_USERNAME` / `PORTAL_PASSWORD`
  (while no administrator account exists) the portal asks you to choose your own password, which creates a real
  administrator account with that name — profile, two-factor and sessions included — and the generated password stops
  working for it. **Upgrade note:** on an install that already has an administrator account nothing changes, except
  that the `.env` password no longer signs in for a name that also exists as a database account; use a different
  `PORTAL_USERNAME` as the emergency key.

### Fixed
- A wrong password on the sign-in screen no longer makes the browser open its own login dialog.
- The account menu explains the built-in admin account instead of showing an empty Profile page.

### Added
- `./deployment.sh set-db-password` gives an existing database the `POSTGRES_PASSWORD` now in `.env` (any characters
  are safe); `./deployment.sh restart api portal …` restarts single services; `up` stops early, with the fix, when
  `API_PORT` / `PORTAL_PORT` don't match the portal's API address or `CORS_ALLOWED_ORIGINS`; `./deployment.sh cleanup`
  removes the old Aksor image versions an update leaves behind (asks first).

## [1.0.0-beta.1] - 2026-10-09

First public beta. Settings, the API and the database schema may still change before 1.0.0: back up before every
upgrade and read this file first.

### Included
- **Khmer-correct documents** — PDF, PNG, DOCX and XLSX from `.docx`, `.xlsx` and `.html` templates with Jinja2
  placeholders. Khmer text is word-segmented automatically so it wraps and justifies correctly; protected terms fix
  names and loanwords the dictionary splits wrongly.
- **Templates** — versions with history, codes, folders and shortcuts, charts and images, automatic splitting of very
  long tables, batch rendering to a ZIP.
- **Data** — filters and choice lists; data from sample JSON, a REST API or a database query (PostgreSQL, MySQL,
  MariaDB, plus Oracle, SQL Server and Db2 through uploaded JDBC drivers in an isolated service); credentials kept
  encrypted as Secrets.
- **Access** — organizations, users, roles and expiring grants; sign-in with short-lived tokens, two-factor
  authentication and LDAP/AD; API clients for embedding and integration; audit trail.
- **Automation** — scheduled jobs with retries.
- **Portal** — web console for templates, runs, previews and administration; fonts added at runtime; light and dark
  themes; built-in documentation.
- **Installation** — `deployment.sh` installs, updates, backs up and restores with Docker Compose, using released
  images for Intel/AMD and ARM. All data lives in one folder, `data/` (the database in `data/postgres`); an install
  that still keeps the database in the older `aksor-khmer-bi_pgdata` Docker volume is moved there automatically.
  Passwords in `.env` may contain any character (wrap a value containing `$` in single quotes).

### Known limitations
- HTTPS is not built in: put a reverse proxy in front of the portal and the API.
- Database migrations only move forward; to go back to an earlier version, restore a backup taken before upgrading.
