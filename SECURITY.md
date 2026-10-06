# Security policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue:

- Email [aksorkhmerbi@gmail.com](mailto:aksorkhmerbi@gmail.com), or use GitHub's
  [private vulnerability reporting](https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/security/advisories/new).
- Include what you found, how to reproduce it, the version (portal footer) and the impact you see.
  Please don't include real credentials or personal data.

What to expect: an acknowledgement within 3 business days, an assessment and a plan within 10, and a
credit in the release notes if you'd like one. We ask for a reasonable period to fix a problem before
details are made public.

## Supported versions

Security fixes go to the latest release. Older releases are fixed on a best-effort basis; organisations
with a commercial support agreement can ask for a fix on the version they run.

## Scope

In scope: the API (`api/`), the portal (`portal/`), the JDBC driver service (`jdbc-worker/`), the
packaged Docker images and the documents' rendering pipeline.

Out of scope: problems that need an already-compromised server or administrator account, findings in
third-party dependencies with no demonstrated effect here (report those upstream), denial of service
by sheer traffic volume, and social engineering.

## How the project defends itself (so you can judge what's worth reporting)

- **Credentials:** database passwords, API tokens and connection secrets are stored encrypted
  (Fernet) in the database, are write-only, and never appear in responses, logs or the audit trail.
  The key is kept outside the database.
- **Access control:** per-organisation roles and fine-grained permissions; report and folder grants;
  every data-changing action is recorded in an audit trail.
- **Data sources:** REST calls never follow redirects and keep filter values out of the host part of a
  URL; database queries are a single read-only `SELECT` with filter values bound as parameters, a read-only
  session, time and row limits, and link-local/metadata addresses refused (`JDBC_ALLOWED_HOSTS` can restrict
  more).
- **Vendor JDBC drivers** (`.jar`) are code, so they only run in the isolated `jdbc-worker` container, which
  has no database access or keys, and only after a SHA-256 check.
- **Operators should:** serve the portal and API over TLS, set strong `PORTAL_PASSWORD` and
  `SECRETS_ENCRYPTION_KEY` values, use read-only database accounts for report connections, and back up
  `data/secrets/` with the database.
