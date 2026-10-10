# Khmer Document Generation API

REST API (FastAPI, Swagger/OpenAPI auto-generated) exposing the
[`doc_engine`](../doc_engine) package over HTTP: **PDF, DOCX, PNG, XLSX**
from a single JSON payload. All rendering logic lives in `doc_engine`
itself — this package is only the HTTP layer.

SOAP was scoped out for now — no real consumer requires it. If one shows up
later, it's a thin adapter: wrap `doc_engine.render()` with `spyne` and
expose a second ASGI/WSGI mount alongside this FastAPI app, rather than
duplicating generation logic.

## Endpoints

| Method | Path                   | Returns                                                          |
| ------ | ---------------------- | ----------------------------------------------------------------- |
| GET    | `/api/v1/health`       | `{"status": "ok"}`                                                 |

### Generic reports (`/api/v1/reports`)

Register your own `.docx`, `.xlsx`, or `.html` template — placeholders are
Jinja2 (`{{ field }}`; docx via
[docxtpl](https://docxtpl.readthedocs.io/), xlsx via
[xltpl](https://github.com/zhangyu836/xltpl) — see
`doc_engine/engines/excel_engine.py`'s `render_xlsx_template` docstring
for the row-loop authoring recipe) — and render it against arbitrary
JSON, no fixed schema required:

| Method | Path                              | Auth? | Returns                                              |
| ------ | --------------------------------- | ----- | ----------------------------------------------------- |
| POST   | `/api/v1/reports`                 | yes   | registers a template (`multipart/form-data`: `file`, `name`, `description`) → `{report_id, ...}` |
| GET    | `/api/v1/reports`                 | no    | list registered reports                               |
| GET    | `/api/v1/reports/{report_id}`     | no    | one report's metadata                                 |
| GET    | `/api/v1/reports/{report_id}/schema` | no | best-effort list of Jinja2 placeholder field names the template expects |
| PATCH  | `/api/v1/reports/{report_id}`     | yes   | update `name`/`description`/`sample_context` (JSON body) |
| PATCH  | `/api/v1/reports/{report_id}/versions/{n}` | yes | edit a version's `version_label` / `note` (the file never changes) |
| PUT    | `/api/v1/reports/{report_id}/file`| yes   | replace the template file (`multipart/form-data`: `file`, optional `note` = what changed, optional `version_label` e.g. `1.0.1`, unique per report) — bumps `version`; the file it replaces is kept |
| GET    | `/api/v1/reports/{report_id}/file[?version=N]` | yes (manage) | download the template file itself, placeholders intact — the current one, or a retained version (`version=1` is the original upload). Recorded in the audit trail |
| GET    | `/api/v1/reports/{report_id}/changelog` | yes (manage) | the template's change log: every file version (who, when, note, size, checksum, placeholders added/removed) merged with every other recorded change, newest first |
| GET    | `/api/v1/audit`                   | yes (`audit:view`) | search the change audit trail — filters `entity_type`, `entity_id`, `action` (exact or prefix), `actor`, `q`, `since`, `until`; paged (`limit`/`offset`), newest first, scoped to the caller's organization |
| DELETE | `/api/v1/reports/{report_id}`     | yes   | remove a report                                       |
| POST   | `/api/v1/reports/{report_id}/render?format=docx\|pdf\|png\|xlsx[&part=N]` | no | rendered file, body = arbitrary JSON data. A table over `MAX_ROWS_PER_FILE` rows (default 1,000) is split into several files and returned as a ZIP (`X-Report-Parts` = how many); `part=N` returns just file N — see [`docs/building-a-report.md`](../docs/building-a-report.md#very-long-tables-automatic-splitting-into-files) |
| POST   | `/api/v1/reports/{report_id}/render/batch?format=docx\|pdf\|png\|xlsx` | no | rendered files as one ZIP, body = a JSON array of contexts (at most 30 for pdf/png, 1,000 for docx/xlsx — see `GET /api/v1/reports/batch-limits`) |
| GET    | `/api/v1/reports/batch-limits`    | no    | the per-format batch size limits and rough seconds per record |
| GET/PUT | `/api/v1/reports/{report_id}/data-config` | yes (manage) | the report's filter `parameters` (type, `required`, `default_value` — a literal or `now()`, a fixed choice list or an `options_source`) and its `data_source` (`type: "rest"`, a `connection` + path or a full `url`, method, headers, body, auth). PUT replaces both; see [`docs/building-a-report.md`](../docs/building-a-report.md#filters-a-data-source-and-connections) |
| POST   | `/api/v1/reports/{report_id}/data-config/preview-options` | yes (manage, own organization) | try an `options_source` — saved or not — and get the first choices its JSONPaths produce, or a readable reason it can't (`400` bad config, `502` the request failed) |
| POST   | `/api/v1/reports/data-preview` | yes (`report:manage`, own organization) | the New report wizard's **Run**: run a `data_source` once, unsaved, with test `values` — the data (lists cut to 20 items), its `fields`, and the filter `parameters` it uses (a `:name` / `{{ name }}` not yet defined is added). `missing` lists filters still without a test value (nothing fetched) |
| POST   | `/api/v1/reports/drafts` | yes (`report:manage`) | create a **draft** report from that data: source and filters saved, the data kept as its sample, and a generated starter template (`format`: docx, xlsx or html) with every field placed as version 1. A draft is listed for and runnable by only people who manage it |
| POST   | `/api/v1/reports/{report_id}/starter` | yes (manage) | replace the template with a freshly generated starter in another `format` (a new version) |
| GET    | `/api/v1/reports/{report_id}/template-check` | yes (manage) | the template's placeholders against the report's sample data: `matched`, `unknown` (each with the nearest real field), `unused`, and the data's `fields`. Follows loops |
| POST   | `/api/v1/reports/{report_id}/publish` | yes (manage) | publish a draft |

"Auth?" means a signed-in caller: an **access token** from `POST /api/v1/auth/login`
(`Authorization: Bearer …`, see "Signing in" below), or HTTP Basic for a script — both checked by
`app/auth.py` against either the break-glass `PORTAL_USERNAME`/`PORTAL_PASSWORD` env vars or a database
user's `report:manage` permission (see "Multi-tenant auth, roles & permissions" below) — reading and
rendering stay open to any caller (the "any developer can just curl this" design this API was built
around); deciding which templates exist at all is the administrative action that requires it.
`PATCH`/`PUT .../file`/`DELETE` additionally accept a report-specific `manage` grant
(`POST /api/v1/grants/reports`) as an alternative to holding `report:manage` globally. No credentials
configured at all (no break-glass, zero database users) fails every protected request closed (`503`), not
open; a wrong/unmatched credential once *something* is configured is a normal `401`.

### Signing in

People and programs sign in once and then carry a short-lived token — the full design, configuration and
security model are in [`../docs/authentication.md`](../docs/authentication.md):

```bash
# Sign in: the answer holds a 15-minute access token (a JWT); -c keeps the HttpOnly refresh cookie.
curl -s -c jar.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<PORTAL_PASSWORD>"}' > login.json
TOKEN=$(jq -r .access_token login.json)

curl http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"

# Renew it (the cookie rotates, so -b AND -c), and sign out (revokes the session at once).
curl -s -b jar.txt -c jar.txt -X POST http://localhost:8000/api/v1/auth/refresh -H "X-Aksor-Client: my-script"
curl -s -b jar.txt -c jar.txt -X POST http://localhost:8000/api/v1/auth/logout  -H "X-Aksor-Client: my-script"
```

| Route | Does |
|---|---|
| `POST /api/v1/auth/login` | user name + password (+ `totp_code`, once 2FA is on; `remember` for a 30-day session) → access token + refresh cookie |
| `POST /api/v1/auth/refresh` | refresh cookie → new access token; the cookie rotates (a replayed one revokes the session) |
| `POST /api/v1/auth/logout` | revokes the session, clears the cookie |
| `GET /api/v1/auth/me` | who the token is and its permissions |
| `GET /api/v1/auth/sessions` · `DELETE /api/v1/auth/sessions/{id}` · `POST /api/v1/auth/sessions/revoke-others` | your live sessions; sign one, or all the others, out |
| `GET /api/v1/auth/verify` | check a username and password with HTTP Basic (scripts); opens no session |

`curl -u user:password` (HTTP Basic) keeps working on every route — handy in a script — unless
`AUTH_ALLOW_BASIC=false`, and an account with two-factor authentication can't use it.

```bash
curl -X POST http://localhost:8000/api/v1/reports \
  -F "file=@invoice_template.docx" -F "name=Invoice"
# -> {"report_id": "…", ...}

curl -X POST "http://localhost:8000/api/v1/reports/<report_id>/render?format=pdf" \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "សុខ សុភា", "amount": 1500}' -o invoice.pdf

# Render the same template against many contexts in one call -- a ZIP of
# rendered files comes back. One synchronous request, so its size is bounded
# by time, per format: 30 records for pdf/png (~2 s each, every one a LibreOffice
# conversion), 1,000 for docx/xlsx (~10 ms each) -- see app/batch_limits.py and
# GET /api/v1/reports/batch-limits.
curl -X POST "http://localhost:8000/api/v1/reports/<report_id>/render/batch?format=pdf" \
  -H "Content-Type: application/json" \
  -d '[{"customer_name": "សុខ សុភា", "amount": 1500}, {"customer_name": "ចាន់ណារិទ្ធ", "amount": 900}]' \
  -o invoices.zip

# Ask what fields a template expects before rendering it -- best-effort,
# not a guaranteed-complete schema (see the route's docstring).
curl "http://localhost:8000/api/v1/reports/<report_id>/schema"
```

A `.docx` template can render to `docx`/`pdf`/`png` (LibreOffice backend
only — WeasyPrint has no notion of a user-supplied `.docx` template); a
`.xlsx` template only renders to `xlsx` (LibreOffice could convert it to
pdf/png too, but that path isn't wired up yet). Requesting a format your
template's file type doesn't support returns `400`. Every string in the
JSON body that contains Khmer is segmented before rendering (text without Khmer is left
exactly as sent), since a custom template
has no fixed field list to allowlist from (see
`doc_engine/segmentation.py`'s `segment_generic`).

Templates are stored under [`../data/report_templates/`](../data) (one
subfolder per `report_id`, gitignored — see `app/report_store.py`) —
deliberately outside this directory, since it's runtime data, not code;
in Docker this is bind-mounted (`docker-compose.yml`) so uploads survive
a container recreate. Every uploaded version is kept under
`<report_id>/versions/v<N>.<ext>` beside the live `template.<ext>` (that's
what makes "download the original" and the change log possible) — so this
directory grows with each replace, and **its backups should include the
`versions/` folders**. There is no automatic pruning.

### Addressing a report: by id or by code

A report's `report_id` is random and differs in every environment, so anything
that calls the public render API, embeds the viewer, or schedules a job has to be
told which id to use — and told again for dev, staging and production. Give the
report an optional **code** instead (`revenue-comparison`) and use it wherever
an id goes:

```bash
# the same call, two ways
curl -X POST "$API/api/v1/reports/1f094af3df23/render?format=pdf"        -d @data.json -H 'Content-Type: application/json'
curl -X POST "$API/api/v1/reports/revenue-comparison/render?format=pdf"  -d @data.json -H 'Content-Type: application/json'
# and the embed:  <portal>/#/embed/revenue-comparison
```

- **Every** `/api/v1/reports/{ref}/…` route accepts either — render, batch, schema,
  run, data-config, `…/file`, `…/changelog`, PATCH, DELETE — with the same permission
  checks (a grant on the report applies however it's addressed). A scheduled job's
  `render_report` config accepts a code in `report_id` too. Unknown → `404`, same as an unknown id.
- **Set it** with `code` on `POST /reports` (form field) or `PATCH /reports/{ref}`
  (`{"code": "revenue-comparison"}`; `null` or `""` removes it). Responses carry it as `code`.
- **Rules:** 3–64 characters, lowercase letters/digits with single hyphens between
  (`^[a-z0-9]+(?:-[a-z0-9]+)*$`); input is trimmed and lowercased. It can't look like an
  id (12 hex characters) or be `accessible`, `batch-limits`, `parse-template` or
  `analytics` (those are fixed paths). `400` says which rule.
- **Unique across the whole deployment** (the render routes are public, so there's no
  organization to scope by) — `409` if taken. A code an organization has ever used stays
  **reserved to that organization for good**, even after the report is renamed or deleted:
  otherwise another tenant could claim the freed code and start receiving the first one's
  integration traffic. (A superuser can release one by deleting its row in
  `report_code_reservations`.)
- **Changing or removing** a code breaks callers using the old one — there is no redirect;
  the id keeps working. It is audited (before/after).
- Register a template with the same code in every environment (the Register dialog's
  *Code* field, or `code=` on `POST /reports`) and the same address works everywhere.

Resolution happens once, in `app/report_ref.py` (a middleware that swaps a known code for
its id before routing), so everything downstream — auth, audit, logs — sees the id. Design
and threat notes: [`specs/report_codes_design.md`](../specs/report_codes_design.md).

### Change audit trail

Every administrative change — templates (register, replace file, edit,
data source / filters, protected terms, access grants, delete, and
*downloading* the template file), users (create, status, password and 2FA
resets, role and permission grants), roles and their permission sets,
organizations, AD/LDAP configuration and group→role mappings, protected
term sets (and edits to the deployment-wide term files, detected at
startup), jobs, folders, images and stylesheets — writes one row to
`audit_events` (`app/audit.py`): who, from which IP, what, when, and the
before/after of each field that changed. Read it at `GET /api/v1/audit`
(`audit:view`, the same permission as the security feed), or in the portal:
**Manage → Audit Log**, a template's **History** tab, a user's **Activity**
tab, and the Dashboard's "Recent changes".

- **Secrets are never stored.** Values under credential-shaped keys
  (`password`, `token`, `secret`, `api_key`, …), every HTTP header value
  in a data source, and free-text `body_template`s are recorded as
  *changed* with no before/after. The *name* of an environment variable
  or a Secret (`token_env`, `token_secret`, `service_bind_password_env`) is
  not a secret and stays visible -- a Secret's own value (Manage → Secrets,
  `app/secret_store.py`) never reaches the audit trail in the first place,
  by construction, not by this redaction.
- **Append-only.** Nothing in the API updates or deletes an audit row, and
  the table has no foreign keys, so a row outlives the user, report or
  organization it describes.
- **Best-effort.** Like the login and access-denied trails, a failure to
  write an audit row is logged and swallowed rather than failing the
  change itself. The template *file history* is not best-effort — it is
  written in the same transaction as the upload.
- **Not covered:** who *ran* a report is in `report_render_log`, sign-ins
  in `auth_events`, refused requests in `access_denied_events`, and job
  executions in `job_runs` — each already has its own trail.

### Multi-tenant auth, roles & permissions

Benchmarked against JasperReports Server's model (Organizations, Users,
Roles, resource ACLs) and extended with one thing Jasper doesn't have:
every grant below can optionally **expire**. See `app/db.py` for the
tables and `app/rbac.py` for the authorization logic.

- **Organizations** (tenants) — `/api/v1/organizations`. Creating one
  auto-seeds its standard role catalog (`ROLE_ORG_ADMIN`,
  `ROLE_REPORT_ADMIN`, `ROLE_REPORT_VIEWER`, `ROLE_JOB_OPERATOR`,
  `ROLE_USER`) so it's immediately usable. A single cross-org
  `ROLE_ADMINISTRATOR` also exists (not tied to any organization) —
  holding it makes a database user behave as a superuser, same as the
  break-glass credential.
- **Users** — `/api/v1/users`, scoped to the caller's own organization
  (a superuser may omit `org_id` to see/manage across all of them).
  `auth_source` is `local` (bcrypt-hashed password, checked here) or
  `ldap` (see below). Usernames are unique *within* an org, not globally
  — logging in as a username that exists in more than one org needs the
  `username|org_id` form (same convention JasperReports Server uses for
  the same reason). **Passwords:** a user an admin creates must choose
  their own at first sign-in (`must_change_password`, on by default;
  until they do, every endpoint but the `/auth` routes and `GET`/`PATCH
  /users/me` answers `403 PASSWORD_CHANGE_REQUIRED`). A password change or
  reset signs the account out of its other sessions; deactivating or
  locking it ends them all (a locked account can't sign in).
  `POST /users/{id}/reset-password` sets a new one -- yours, or a
  generated one returned once -- and re-flags the account;
  `PATCH /users/{id}` with `must_change_password` flags or unflags it
  without touching the password. Every path that sets a password
  requires 8+ printable-ASCII characters. The break-glass login has no
  database row, so it is never flagged.
- **Roles & permissions** — `GET /api/v1/permissions` (the fixed
  catalog), `/api/v1/roles` (per-org role list, `PUT .../permissions` to
  replace a role's grants).
- **Connections** — `/api/v1/connections` (`connection:manage`; list also
  for `report:manage`, without header values): named, per-organization
  base URLs with the headers and authentication every call to them needs.
  A report's data source or REST-backed choice list names one and adds
  only a path (`app/connections.py` swaps in the current base URL,
  headers and auth at run time), so an API that moves is one edit. The
  name is fixed once created; a connection a report still uses can't be
  deleted (`409`). Created, changed and deleted connections are audited.
- **Secrets** — `/api/v1/secrets` (`secret:manage` to create/rotate/
  revoke/delete; list also for `connection:manage`/`report:manage`,
  never a value): named credentials (`app/secrets.py`) a connection's
  authentication *or a report's own data source/choice list* refers to
  by `token_secret`/`password_secret` instead of an environment
  variable's `token_env`/`password_env` -- either is a per-credential
  choice. Encrypted at rest (`app/secret_store.py`), write-only (no
  endpoint returns the value), rotated in place (whatever names it needs
  no change), and revoked (`is_active=false`) rather than deleted while
  anything still refers to it: a revoked or missing credential fails the
  *run* with a readable `502`, not the save. Created, rotated, revoked
  and deleted secrets are audited -- never the value.
- **Expiring grants** — `/api/v1/grants/{roles,permissions,reports}`:
  grant a user a role, a direct permission, or access to one specific
  report, each with an optional `expires_at`. An expired or revoked
  (`is_active=false`) grant simply stops counting — no cleanup job
  required for correctness.
- **AD/LDAP login** — `/api/v1/ldap-configs`: point a `local`-free
  organization at a directory instead. Three bind methods
  (`app/auth_ldap.py`): `direct_bind` (fixed DN template, plain
  LDAP/OpenLDAP), `search_bind` (service account finds the user's DN,
  then re-binds as them — the standard method for real AD), `upn_bind`
  (`user@domain`, an AD-specific shortcut — plain OpenLDAP has no notion
  of this and will reject it, verified to fail closed against it rather
  than assumed). A directory group can be mapped to an internal role
  (`POST /api/v1/ldap-configs/{id}/group-mappings`); on every successful
  login the user's actual group membership is re-resolved and the
  matching non-expiring role grants (tagged `granted_by="ldap-sync"`) are
  added or deactivated to match — leaving a group revokes the role on the
  next login, not immediately, and never touches a role granted manually
  through `/api/v1/grants/roles` instead. `POST .../test` tries a bind
  with a real username/password against a saved config without creating
  a user, for validating the configuration itself.

```bash
curl -X POST http://localhost:8000/api/v1/organizations \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"id": "acme", "name": "Acme Corp"}'

curl -X POST "http://localhost:8000/api/v1/users?org_id=acme" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"username": "alice", "auth_source": "local", "password": "correcthorse123"}'

# Grant alice ROLE_REPORT_ADMIN in acme for 30 days.
curl -X POST http://localhost:8000/api/v1/grants/roles \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"user_id": "<alice-id>", "role_id": "<role-id>", "expires_at": "2026-10-14T00:00:00+00:00"}'

# Point acme at a directory instead of local passwords.
curl -X POST "http://localhost:8000/api/v1/ldap-configs?org_id=acme" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"server_uri": "ldap://dc.corp.example.com:389", "bind_method": "search_bind",
       "base_dn": "dc=corp,dc=example,dc=com", "service_bind_dn": "cn=svc-aksor,dc=corp,dc=example,dc=com",
       "service_bind_password_env": "CORP_LDAP_SERVICE_PASSWORD", "user_search_filter": "(sAMAccountName={username})"}'
```

Try the AD/LDAP login end to end without a real directory: `docker
compose -f docker-compose.yml -f docker-compose.ldap-dev.yml up -d openldap`
then `./scripts/seed-ldap-dev.sh` — see that compose file's header
comment for the seeded test users/groups.

### Fonts (`/api/v1/fonts`)

Fonts added at runtime, for the whole server (not per organization). Adding and removing need `font:manage`
(system administrators by default); listing, reading and previewing need that or `report:manage`.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/fonts` | the added fonts, each with identity, version, Khmer/Latin coverage, layout-table flag, license, warnings and `used_by` (the templates that name its family) |
| POST | `/api/v1/fonts` | add one (`multipart/form-data`: `file` = a `.ttf`/`.otf`, optional `note`); `400` for anything that isn't a usable font, `409` for the same file or the same family + style twice; warnings in the body |
| GET | `/api/v1/fonts/{id}`, `/file`, `/coverage` | one font; its bytes (for previewing); which characters it has, block by block |
| GET | `/api/v1/fonts/installed` | every family the server can draw with, `uploaded` or `system` |
| DELETE | `/api/v1/fonts/{id}` | remove it — `409` while a template names it, unless `?force=true` |
| GET | `/api/v1/reports/{id}/fonts` | the fonts a template names, each `uploaded`, `installed`, `substituted` or `missing` |

Files live in `data/font_resources/<id>.ttf|otf` (mounted into `api` and, read-only, `worker`; back it up with `data/`).
`DOC_ENGINE_FONT_DIRS` points the renderers at that folder: LibreOffice gets the fonts per conversion (linked into its
throw-away profile), WeasyPrint as inlined `@font-face` rules, charts through matplotlib — so an upload applies to the
next render, with no restart. Uploads are checked by their own signature and read with fontTools (pure Python), capped by
`FONT_MAX_MB` (default 20). **Note:** LibreOffice for macOS ignores a profile's `user/fonts`, so on a Mac development
machine install fonts for `.docx` in `~/Library/Fonts`; the Docker image (Linux) is unaffected.

### Resources: folder tree, images (`/api/v1/folders`, `/api/v1/images`)

A JasperReports-Server-style repository: nested folders hold report
templates and uploaded images, with per-folder `view`/`manage` grants an
admin can hand a role (or a specific user) instead of the blanket
`folder:manage` permission — the point being "let this role into this
whole folder" without report-by-report grants. Unlike
`Organization.parent_org_id` (explicitly non-inheriting — see `app/db.py`),
a folder grant **does** inherit down the tree: granting `view` on
"Finance" covers "Finance/Q1" too, with no separate grant needed there.

| Method | Path                                | Auth?          | Returns                                                     |
| ------ | ------------------------------------ | -------------- | ------------------------------------------------------------ |
| POST   | `/api/v1/folders`                    | yes            | create a folder (`name`, `org_id`, optional `parent_folder_id`) |
| GET    | `/api/v1/folders`                    | yes            | folders visible to the caller (`?org_id=`)                   |
| GET    | `/api/v1/folders/{id}`               | yes            | one folder                                                    |
| PATCH  | `/api/v1/folders/{id}`               | yes            | rename, and/or move to a different `parent_folder_id` (`null` = root) |
| DELETE | `/api/v1/folders/{id}`               | yes            | delete — `409` unless it holds no sub-folders, reports or images (shortcuts in it don't count; they are removed with it) |
| POST   | `/api/v1/images`                     | yes            | upload (`multipart/form-data`: `file`, `name`, `org_id`, optional `folder_id`) |
| GET    | `/api/v1/images`                     | yes            | images visible to the caller (`?org_id=`, `?folder_id=`)      |
| GET    | `/api/v1/images/{id}`                | yes            | one image's metadata                                          |
| GET    | `/api/v1/images/{id}/file`           | yes            | raw image bytes                                                |
| DELETE | `/api/v1/images/{id}`                | yes            | delete                                                          |
| GET    | `/api/v1/reports/shortcuts`          | yes            | shortcuts in folders the caller may open, for reports they can open |
| GET    | `/api/v1/reports/{id}/shortcuts`     | report `manage`| the folders a report is also listed in                         |
| POST   | `/api/v1/reports/{id}/shortcuts`     | report `manage` + folder `manage` | list a report in another folder (`{"folder_id"}`); `400` if it's already filed there, `409` if a shortcut exists |
| DELETE | `/api/v1/reports/shortcuts/{id}`     | report `manage` or folder `manage` | remove a shortcut — the report is untouched |
| POST   | `/api/v1/grants/folders`             | `folder:manage`| grant a user or role `view`/`manage` on one folder             |
| GET    | `/api/v1/grants/folders?folder_id=`  | `folder:manage`| list a folder's grants                                          |
| DELETE | `/api/v1/grants/folders/{grant_id}`  | `folder:manage`| revoke                                                           |

"Auth?" here means any authenticated caller with `view`-level access to
the folder in question for a `GET`, or `manage`-level for anything that
creates/renames/moves/deletes/uploads/deletes — either the global
`folder:manage` permission or a folder-specific grant
(`has_folder_access`, `app/rbac.py`, which walks up to any ancestor
folder's grants too). The grant endpoints themselves are the exception:
they deliberately require the global `folder:manage` permission, not a
narrower per-folder grant (same reasoning as report grants — creating a
*grant* is administration of the whole access-control system, not
management of one folder's own contents). Unlike `/api/v1/reports`'
list/get/render, folder and image listing are **not** public — Resources
is a new surface with no "stays open" precedent to preserve, and
per-folder visibility is the actual point of the grants above.

**Filing a report.** `POST /api/v1/reports` takes an optional `folder_id` form field, and `PATCH
/api/v1/reports/{id}` moves it (`null` = root). Either needs `manage` on the destination folder, and the folder
must exist in the report's own organization (otherwise `404`, the same answer for a missing and a foreign
folder). `GET /api/v1/folders` includes `can_manage` for each folder, so a client can offer only the folders the
caller may file into.

**Shortcuts.** *Why they exist: one report used by several departments or teams, each wanting it in its own folder
to arrange their own space — without copies.* A shortcut lists a report in a second folder (`report_shortcuts` table, one row per report and
folder). It is a *placement*, not a copy and not a permission: opening it opens the original, so access is only
ever decided from the report's own grants and its own folder chain. A grant on the folder that holds a shortcut
does **not** reach the report, and `GET /api/v1/reports/accessible` lists a shortcut (`shortcuts`, with the visible
folder path of each) only for a caller who already holds access to the original, and only in folders they may
open. `folder_path` on each accessible report likewise names only the folders the caller may open. Creating and
removing shortcuts is audited (`report.shortcut_create`, `report.shortcut_delete`).

An uploaded image can also be embedded directly into a rendered `.docx`
report — see [`docs/building-a-report.md`](../docs/building-a-report.md#images-docx-templates-only).

```bash
curl -X POST http://localhost:8000/api/v1/folders \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"org_id": "acme", "name": "Finance"}'
# -> {"id": "<folder_id>", ...}

curl -X POST http://localhost:8000/api/v1/images \
  -H "Authorization: Bearer $TOKEN" \
  -F "name=logo.png" -F "org_id=acme" -F "folder_id=<folder_id>" -F "file=@logo.png"
# -> {"id": "<image_id>", "width_px": ..., "height_px": ..., ...}

# File a report into that folder (folder_id: null moves it back to root).
curl -X PATCH http://localhost:8000/api/v1/reports/<report_id> \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"folder_id": "<folder_id>"}'

# Render it with the uploaded image embedded.
curl -X POST "http://localhost:8000/api/v1/reports/<report_id>/render?format=docx" \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Acme", "logo": {"image_id": "<image_id>", "width_mm": 30}}' \
  -o rendered.docx

# Let ROLE_REPORT_VIEWER see everything in Finance/ without a per-report grant.
curl -X POST http://localhost:8000/api/v1/grants/folders \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"subject_type": "role", "subject_id": "<role-id>", "folder_id": "<folder_id>", "permission_level": "view"}'
```

### Job scheduling (`/api/v1/jobs`)

A Quartz-style scheduler split into two pieces (`docker-compose.yml`'s
`scheduler` and `worker` services) specifically so retrying a failed job
doesn't depend on the same process that decides *when* things fire:

- **`app/scheduler.py`** (single replica, on purpose — more than one
  would fire every trigger once per replica) uses
  [APScheduler](https://apscheduler.readthedocs.io/) with a
  `SQLAlchemyJobStore` against the same Postgres database — the direct
  Python analog to Quartz's JobStore + CronTrigger, durable across
  restarts. It polls the `jobs` table every
  `SCHEDULER_RECONCILE_INTERVAL_SECONDS` (default 15) to pick up
  create/edit/pause/delete without a separate signaling protocol. On
  fire, it does **not** run the job — it enqueues a Celery task and
  returns.
- **`app/celery_app.py`**'s `run_job` task (consumed by the `worker`
  service, horizontally scalable) does the actual work
  (`app/job_executors.py`) and retries — with the *job's own*
  `max_retries`/`retry_backoff_seconds`, not a fixed policy — only for
  transient failures (`RetryableJobError`: network errors, 5xx); a bad
  config, a 4xx, or a permission error (`PermanentJobError`) fails
  immediately with no retry.

Four `job_type`s, each with its own `config` shape (see
`app/job_executors.py`'s module docstring for the exact keys):
`render_report` (render a registered template and write it to a file —
the common "just run this report on a schedule" case), `rest_call`
(Jinja2-templated body/headers, optional basic/bearer auth via an
env-var-referenced secret), `soap_call` (via
[zeep](https://docs.python-zeep.org/) — the "thin adapter" this
project's docs always said SOAP would need if a real consumer showed
up), `file_output` (write a static payload, or a freshly-rendered
report, to a configured path — a plain semaphore/flag file for a
downstream system counts).

```bash
curl -X POST "http://localhost:8000/api/v1/jobs?org_id=acme" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "Nightly invoice run", "job_type": "render_report",
       "config": {"report_id": "<report_id>", "format": "pdf", "context": {"customer_name": "Acme"},
                   "destination_path": "/data/scheduled/{job_id}/{timestamp}.pdf"},
       "trigger_type": "cron", "cron_expression": "0 2 * * *"}'

# Fire it right now -- a person clicking "run now," or any external
# system calling this same route with a job:trigger credential.
curl -X POST http://localhost:8000/api/v1/jobs/<job_id>/run -H "Authorization: Bearer $TOKEN"

curl http://localhost:8000/api/v1/jobs/<job_id>/runs -H "Authorization: Bearer $TOKEN"
```

Run the scheduler/worker locally without Docker (needs a running Redis —
`REDIS_URL`, default `redis://localhost:6379/0`):

```bash
python -m app.scheduler                                    # one terminal
celery -A app.celery_app worker --loglevel=info             # another
```

### Management portal

A small static web UI for the administrative side of the API above lives
at [`../portal`](../portal) — a **separate, independently deployable
instance** from this service (its own container, no LibreOffice/Python
weight), not something this service serves itself. It's just a browser
client for the same endpoints in the table above — no separate backend
logic of its own.

```bash
export PORTAL_USERNAME=admin
export PORTAL_PASSWORD='pick something real'
export CORS_ALLOWED_ORIGINS=http://localhost:8080   # wherever the portal is served from
uvicorn app.main:app --reload --port 8000 --env-file .env
```

If neither `PORTAL_USERNAME`/`PORTAL_PASSWORD` is set nor any user exists, every protected request (see
the "Auth?" column above) gets `503`, not a silent bypass — the portal is unusable until credentials are
configured, on purpose (see `app/auth.py`). `CORS_ALLOWED_ORIGINS` is separate: it's what lets the portal's
browser-side JS call this API at all, now that they're different origins — and, because the refresh cookie
rides along, it must name the portal's exact origin and the portal and API must share a site; see
`app/main.py`, [`../docs/authentication.md`](../docs/authentication.md) and
[`../docs/deployment.md`](../docs/deployment.md). Tokens and cookies — and HTTP Basic — need TLS in front
of this (a reverse proxy) before being exposed beyond a trusted network.

## Run

```bash
# from repo root, with the venv active and doc_engine/aksor_khmer_ocr_segmenter
# already `pip install -e`'d (see repo root README)
cd api
pip install -r requirements.txt

# Applies pending migrations -- see "Report metadata storage" below.
# Skippable for a first run against the SQLite default (auto-created),
# required once you point DATABASE_URL at a real Postgres.
alembic upgrade head

cp .env.example .env   # first time only -- then edit .env if you need to
uvicorn app.main:app --reload --port 8000 --env-file .env
```

[`.env.example`](.env.example) has the env vars a local dev run actually
needs: `PORTAL_USERNAME`/`PORTAL_PASSWORD` (the break-glass superuser --
unset means every admin route 503s closed) and `CORS_ALLOWED_ORIGINS`
(needs to include wherever the portal is running -- `:5173` for `npm run
dev`, `:4173` for `npm run preview`, `:8080` for the Dockerized portal).
`--env-file` is a real uvicorn flag (backed by `python-dotenv`, already
pulled in by `uvicorn[standard]`) -- no extra setup, and no more typing
three `export` lines by hand every time. `.env` itself is gitignored;
copy it from the committed `.env.example` instead of editing that
directly. The Khmer protected-terms env vars
(`AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE` etc., see below) are optional and
not in `.env.example` since most local runs don't need to override them.

### Report metadata storage

Report *metadata* (name, description, version, timestamps,
`sample_context`) lives in a database, managed via
[SQLAlchemy](https://www.sqlalchemy.org/) + [Alembic](https://alembic.sqlalchemy.org/)
migrations (`migrations/`) — see `app/db.py` for the full rationale. The
template *files themselves* (`.docx`/`.xlsx`) are unaffected: still plain
files under `../data/report_templates/<report_id>/`.

`DATABASE_URL` selects the backend:

```bash
# Default if unset -- zero setup, a local SQLite file (api/aksor_khmer_bi.db,
# gitignored). Fine for a quick local run or a single-instance deployment
# that doesn't need concurrent-write safety across replicas.
# export DATABASE_URL left unset

# Real deployments -- see docker-compose.yml's `postgres` service:
export DATABASE_URL=postgresql+psycopg://aksor:aksor@localhost:5432/aksor_khmer_bi
```

Whichever backend you're pointed at, run `alembic upgrade head` before
starting the API (the Docker image's entrypoint does this automatically
— see `../docker-entrypoint.sh`). Adding a column later means editing
`app/db.py`'s `ReportRow` model, then generating a new migration:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

`migrations/versions/` starts from one baseline, `0001_initial_schema`
(the whole schema, tables grouped by concern); every later change is a new
migration on top of it. It seeds nothing: the API creates the permission
catalog, the administrator role and each organization's standard roles on
startup (`app/rbac.py`'s `seed_defaults`).

The test suite never touches either of the above — `tests/conftest.py`'s
`isolated_report_store` fixture points every test at its own throwaway
SQLite file, so `pytest` needs no database running.

### Khmer protected terms for this project

Every string in a custom template's render payload that contains Khmer goes through
`aksor_khmer_ocr_segmenter.process_text()` (see
`doc_engine/segmentation.py`'s `segment_generic`) before rendering, so it
already benefits from the shared package's built-in protected-terms list
(countries, Cambodian districts, common banks/brands, legal vocabulary —
see
[`../../docs/protected-terms-guide.md`](../../docs/protected-terms-guide.md)
for the full catalog and the procedure for growing it).

Free-text fields like a customer's name or a bank list are open-ended user
input a shared, finite list can never fully cover (arbitrary Khmer given
names are combinatorially unbounded; any bank not already in the shared
package needs handling somewhere). `khmer_protected_terms.txt`
in this directory is where *this deployment* adds terms specific to real
production data it has actually observed mis-splitting, without touching
the shared open-source package — `khmer_protected_terms.exclude.txt` is
the inverse, for suppressing a shared term that's wrong for this
deployment's data. Both are empty scaffolds by default with the format and
procedure documented inline; set the environment variables above to wire
them in.

Once you have more than one or two of these (per-customer term lists, a
separate file per data source, etc.), prefer the directory form instead:
`khmer_protected_terms.d/` and `khmer_protected_terms.exclude.d/` — drop
any number of `*.txt` files into either folder and they're all merged in,
no env var edits needed per file. Both mechanisms can run at once; see
each directory's own `README.md` and
[`../../docs/protected-terms-guide.md`](../../docs/protected-terms-guide.md).

Then open:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Raw OpenAPI JSON: http://localhost:8000/openapi.json

## Tests

```bash
python -m pytest tests/ -v
```
