# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
