# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
