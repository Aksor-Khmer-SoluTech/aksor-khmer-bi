# Questions and answers

Short answers to what people ask most, each with a link to the guide that explains it fully. In the portal these
are on the Guides home page, by category; search finds them too.

## Getting started

### Which template format should I use?

Start with **`.docx`**: it has the most features (charts, images, PDF, and an Excel copy of its tables) and anyone can
edit it in Word. Use **`.xlsx`** only when the result must stay a spreadsheet, and **`.html`** when you need CSS
control Word can't give you (badges, cards, columns). See [Pick a format](create-a-template.md#1-pick-a-format).

### What's the quickest way to make a first report?

**Templates → New Template** starts from your data: paste sample JSON, or point it at a REST API or a database
query, and press **Run** to see what comes back. It then lists every field with the exact placeholder to type, and
can write a **starter template** with every field already placed for you to restyle in Word. The whole path is in
[The workflow, end to end](create-a-template.md#2-the-workflow-end-to-end).

### Can I change a template without breaking the reports people already run?

Yes. *Replace template file* on the template's Overview tab adds a new version and keeps the report's id, code and
integrations. Every earlier file stays downloadable under **History**, which also shows the placeholders each version
added or dropped, next to your *What changed?* note. See
[Changing a template later](create-a-template.md#33-changing-a-template-later-versions).

### How do I organize lots of reports for different teams?

File them in **folders** (Manage → Resources). When several teams use the same report, don't copy it: give each
team's role access to the report, then add a **shortcut** in each team's folder. There's still one report to
maintain, and a shortcut grants nothing by itself — it has exactly the original's permissions. See
[Folders and shortcuts](create-a-template.md#34-folders-and-shortcuts).

## Writing templates

### How do I repeat a table row for every item?

Put `{%tr for item in items %}` alone in a row above the row to repeat, and `{%tr endfor %}` alone in a row below it;
the row in between uses `{{ item.name }}`, `{{ item.amount }}` and so on. See
[Repeating table rows](create-a-template.md#52-repeating-table-rows).

### What happens when a field is missing from the data?

`{{ note }}` with no `note` simply prints nothing. But reading a field *of* something that isn't there —
`{{ issuer.name }}` with no `issuer` — stops the render with an error. Guard it with
`{{ issuer.name if issuer else "" }}`, or give a default with `{{ note | default("N/A", true) }}`. See
[Missing data](create-a-template.md#43-missing-data--read-this-once).

### How do I format money, numbers and dates?

Numbers: `{{ "{:,.2f}".format(amount) }}` gives `1,234.50`. Dates arrive as ISO text (`2026-09-30`), so slice them:
`{{ date[8:10] }}/{{ date[5:7] }}/{{ date[:4] }}` gives `30/09/2026`. There are recipes for Khmer month names,
percentages, zero-padding and more in [Formatting and converting values](create-a-template.md#45-formatting-and-converting-values).

### Can numbers be printed in Khmer digits (០១២)?

Yes, with `translate` over the whole formatted text:
`{{ ("{:,.2f}".format(amount)).translate("".maketrans("0123456789", "០១២៣៤៥៦៧៨៩")) }}` gives `១,២៣៤.៥០`. See
[Khmer digits](create-a-template.md#khmer-digits).

### My `{{ field }}` shows up literally in the output. Why?

Word split the tag while you typed it: autocorrect, a spelling mark or a change of font style in the middle. Retype
it in one go, keeping one style across it. Curly quotes cause the same kind of trouble; Jinja needs straight `"` and
`'`. More symptoms and fixes are in [Troubleshooting](create-a-template.md#9-troubleshooting).

## Khmer text and fonts

### Do I need to put spaces between Khmer words?

No. Every piece of Khmer text in the data is split into words automatically before it reaches the document, so long
Khmer text wraps and justifies correctly. Text without Khmer — dates, numbers, IDs — is left as it is. See
[Khmer text](create-a-template.md#44-khmer-text) and [why Khmer wraps differently](khmer-line-breaking.md).

### A Khmer word is split in the wrong place. How do I fix it?

Add it as a **protected term**: on the report's own **Protected Terms** tab, or in a shared set under
**Manage → Protected Terms** that reports select. It applies from the next render, with no restart. Don't add spaces
or change the template. See
[Configuring terms from the portal](protected-terms-guide.md#configuring-terms-from-the-portal-no-code-no-restart).

### Which font should I use for Khmer?

Set the template's font to a Khmer font such as *Khmer OS Siemreap* in Word. A template only *names* its fonts, so
the server draws with the font it has: the template's **Placeholders** tab lists each font it names as installed,
added, substituted or missing. To use another font, add it under **Manage → Resources → Fonts**, no restart needed.
See [Fonts](create-a-template.md#65-fonts).

## Data, filters and datasets

### Where can a report get its data?

From **sample data** (fixed JSON, handy while designing), a **REST API**, a **database** (a read-only SQL query on
PostgreSQL, MySQL, MariaDB, Oracle, SQL Server or Db2), or a **dataset** shared with other reports. It's set on the
report's Data source tab. See [Filters, a data source, and connections](building-a-report.md#filters-a-data-source-and-connections).

### How do I let a branch see only its own data?

Give the branch's people or role access on the report's **Access Privilege** tab and tick **Only these** values for
the branch filter. The server checks every run, so a value they weren't given is refused and never reaches the data
source. When many reports share the data, put the limit on the **dataset** instead, so it applies to all of them. See
[Datasets](building-a-report.md#datasets-one-source-its-filters-and-its-measures-shared-by-many-reports).

### What is a dataset, and when should I use one?

A dataset defines a body of data once — its source, filters, what each field means (in English and Khmer) and named
measures like *Net sales* — under **Manage → Datasets**. Use it when several reports read the same data: a fix or a
new measure then reaches all of them, and its access rules cover all of them. See
[Datasets](building-a-report.md#datasets-one-source-its-filters-and-its-measures-shared-by-many-reports).

### My database isn't PostgreSQL, MySQL or MariaDB. Can I still use it?

Yes. Upload the vendor's JDBC driver (`.jar`) under **Manage → JDBC Drivers** for Oracle, SQL Server or Db2, then
choose it on the connection. Uploaded drivers run in a separate, isolated service, never inside the API. See
[Filters, a data source, and connections](building-a-report.md#filters-a-data-source-and-connections).

### My data is in several databases (one per service). Can one report read them all?

Yes. Use several queries in one database source and give a query a **Database** of its own on its card; the rest use
the default connection. The results come together as one object for the template. Each query only sees its own
database, so match records across them in the template, not in SQL. See
[Filters, a data source, and connections](building-a-report.md#filters-a-data-source-and-connections).

### Can a report call a stored procedure or a function?

Yes, on any database, written in the query's SQL box like any query: `EXEC dbo.GetSales @branch = :branch` on SQL
Server, `CALL hr.get_sales(:branch)` elsewhere, `SELECT * FROM dbo.fn_sales(:branch)` for a function. Nothing to set
up on the connection: the procedure runs as the connection's login, so give reports a login that may only read and run
what they need. Arguments are filters, numbers, `'text'` or `NULL`, always bound. See
[Filters, a data source, and connections](building-a-report.md#filters-a-data-source-and-connections).

### Can I explore the data without making a report?

Yes, with **Explore data** under **Dashboards** in the top bar: pick a dataset, put fields in rows and columns (a date can be grouped by
month or year) and measures in values, and read it as a table or a bar or line chart. Export it as PDF, Word or
Excel, or save the view to open it again. It needs the `analyze:use` permission. See
[Analyze](building-a-report.md#analyze-slice-a-dataset-as-a-table-or-a-chart).

### Can I get an email when a number crosses a line?

Yes — a data alert. In **Dashboards → Explore data**, set the view's filters, choose **Alert me**, pick the measure,
*below* or *above* and the threshold, how often to check, and who to email. It emails when the number first
crosses, not again until it recovers; it's a job under Manage → Jobs. See
[Dashboards and data alerts](building-a-report.md#dashboards-and-data-alerts).

## Output: PDF, Excel and big reports

### Which file types can a report give me?

A `.docx` template gives Word, PDF, PNG and **Excel tables** (its tables, one sheet each, keeping their look). An
`.xlsx` template gives Excel only, and an `.html` template PDF or PNG. Charts and images are for `.docx`. See
[Pick a format](create-a-template.md#1-pick-a-format).

### My report has thousands of rows. What happens?

A table with more than 1,000 rows (`MAX_ROWS_PER_FILE`) is split into several files with an equal share of the rows,
delivered as one ZIP — the preview shows them one at a time. One run makes at most 20 files (`MAX_REPORT_PARTS`); past
that, narrow the filters. See [Very long tables](building-a-report.md#very-long-tables-automatic-splitting-into-files).

### Can another system run a report and get the file?

Yes. Create an **API client** under **Manage → API Clients**, tick the reports it may run, and copy its client id and
secret (the secret is shown once). Your system then sends the filter values with those credentials to
`POST /api/v1/reports/{id}/embed-run`. See
[Running a report as an API client](building-a-report.md#running-a-report-as-an-api-client-client-id--secret).

## Schedules and email

### Can a report run on a schedule?

Yes. Under **Manage → Jobs**, a job runs a report with set filter values on a schedule — every hour, every day,
every weekday, every week, every month, or a cron expression — in the server's time zone (`REPORT_TIMEZONE`). See
[Job scheduling](deployment.md#job-scheduling).

### Can the result be emailed?

Yes. Add a mail server under **Manage → Connections** (*New Mail Server*, with presets for Google Workspace,
Microsoft 365 or any SMTP server), then choose **Email it** in the job's *Where it goes* section. The subject and
message can name the report, the date and each filter, Khmer included.

### Can each branch get its own file?

Yes — **One file per value** on a job splits the report by a filter with a list of choices: one run makes one file
per branch, each with only that branch's data and sent to that branch's recipients. A value with no data can be
skipped instead of sent empty.

### An email failed to send. Can I send it again?

Open the job's **Run history**: each run lists every file and who it went to (sent, saved, failed with the mail
server's reason, or skipped). **Re-send the ones that failed** sends the very same file again, without re-running the
report.

## Sign-in and access

### Someone forgot their password. What do I do?

An administrator resets it under **Manage → Users**: a temporary password is shown once, and the user picks their
own at the next sign-in. Directory (AD/LDAP) users change their password in the directory, not here.

### I'm locked out as the administrator.

If the break-glass login from `.env` (`PORTAL_USERNAME` / `PORTAL_PASSWORD`) is still set, sign in with it and reset
your account under **Manage → Users**. After editing `.env`, run `./deployment.sh up` so the change is read. See
[Deployment](deployment.md#environment-variables-reference).

### How do I turn on two-factor authentication?

Each person turns it on for their own account in **Settings → Access**, with an authenticator app. After that, signing in asks
for the 6-digit code. If someone loses their phone, an administrator clears their 2FA under **Manage → Users** and
they enrol again. See [Two-factor authentication](authentication.md#two-factor-authentication).

### Who can see or change what?

Roles carry permissions (**Manage → Roles**), and a report, folder or dataset can also be shared with one person or
role, optionally until a date. **Manage → Access Review** lists every such grant in one place, and **Manage → Audit
Log** records who changed what.

## Running the server

### How do I update to a new version?

Read the [CHANGELOG](../CHANGELOG.md) first, then `git pull` and `./deployment.sh update`. It takes a backup, pulls
the new images and restarts the app; database changes apply as the API starts. See
[Quick deployment](deployment.md#option-1--quick-deployment-deploymentsh).

### How do I back up and restore?

`./deployment.sh backup` saves the database and the data files together; `./deployment.sh restore <file>` puts them
back, after taking a safety backup of the current state. Keep the two files of a backup together: the encryption key
and the database belong to each other. See [Back up](deployment.md#back-up).
