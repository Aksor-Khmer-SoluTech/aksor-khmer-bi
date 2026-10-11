# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- A database source's query cards label the one-row shape **Object** (was *One row*): List / Object / One value.
- Several queries in a database source can be put in order by dragging a card's handle (or with the keyboard:
  space, then the arrow keys).

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
