# Deployment

Everything below describes what's actually in the repo and was verified
by building and running it, not a hypothetical setup — see the root
[`Dockerfile`](../Dockerfile), [`portal/Dockerfile`](../portal/Dockerfile),
and [`docker-compose.yml`](../docker-compose.yml).

## Docker (recommended)

Six services: `api` (the FastAPI service, heavyweight:
LibreOffice/Tesseract/ICU), `portal` (the management console, a React
+ Vite app built in a Node stage and then served as static files by
`nginx:alpine` — the *runtime* image still has no Python/LibreOffice/Node
in it, see `portal/Dockerfile`'s multi-stage build), `postgres`
(report *metadata*, the multi-tenant auth/RBAC schema, and job
definitions/run history — the template files themselves stay on disk,
see [`api/app/db.py`](../api/app/db.py)), `redis` (Celery's broker),
and `scheduler`/`worker` (the job-scheduling split — see "Job scheduling"
below). `api` and `portal` can each be built, deployed, and scaled
independently.

### Three compose files, one script

The six services are split by lifecycle into three stacks that share an external
network, `aksor-network`:

| Stack | File | Compose project | Services |
|---|---|---|---|
| **redis** (stateful) | [`docker-compose.redis.yml`](../docker-compose.redis.yml) | `aksor-redis` | `redis` |
| **db** (stateful) | [`docker-compose.db.yml`](../docker-compose.db.yml) | `aksor-db` | `postgres` |
| **app** (stateless) | [`docker-compose.yml`](../docker-compose.yml) | `aksor-app` | `api`, `scheduler`, `worker`, `portal` |

The app can be rebuilt, updated or rolled back without the database or the queue being touched,
and Postgres/Redis can be swapped for managed ones (RDS, ElastiCache…) by not
starting their file and pointing `DATABASE_URL` / `REDIS_URL` at them. Containers
still reach each other as `postgres` and `redis` — a shared network resolves service
names across projects. A step-by-step walkthrough, one file at a time, is in
[`DEPLOYMENT.md`](../DEPLOYMENT.md).

[`deployment.sh`](../deployment.sh) runs all three in the right order:

```bash
./deployment.sh init      # once: creates the network and a .env with generated passwords
./deployment.sh up        # redis, then postgres (each waits until healthy), then the app
```

| Command | Does |
|---|---|
| `init` | Creates `aksor-network`, the `data/` folders, and a mode-600 `.env` with a random `POSTGRES_PASSWORD` and `PORTAL_PASSWORD` (shown once). Never overwrites an existing `.env`; if a Postgres volume already exists it does **not** invent a new database password. |
| `up` | Starts redis and postgres, waits for health, builds and starts the app. Warns about a default DB password, a missing `PORTAL_PASSWORD`, or unset `CORS_ALLOWED_ORIGINS`. |
| `update [--no-backup] [--pull]` | Backs up, rebuilds the app images, recreates the app (migrations run as the API starts). Redis and Postgres are not recreated. `--pull` refreshes base images. |
| `down` | Stops the app, then postgres, then redis. Named volumes and `./data` are kept. |
| `restart [redis\|db\|app]`, `status`, `logs [service…]` | Operate and inspect. |
| `backup` | `pg_dump` plus `data/` (templates and every version, uploaded images/stylesheets, avatars, the secrets key) into `./backups/`, newest 14 kept (`BACKUP_KEEP`). The secrets key and the database belong together — restore both or stored credentials can't be decrypted. |
| `redis …` / `db …` / `app …` | Pass any `docker compose` command to one stack, e.g. `./deployment.sh app up -d --scale worker=3`. |

By hand, without the script:

```bash
docker network create aksor-network
docker compose -p aksor-redis -f docker-compose.redis.yml up -d --wait
docker compose -p aksor-db    -f docker-compose.db.yml    up -d --wait
docker compose -p aksor-app   -f docker-compose.yml       up -d --build
```

Keep the three `-p` project names distinct: with a shared project, `--remove-orphans`
on one stack would remove the others' containers. All three stacks read the same `.env`,
so `POSTGRES_PASSWORD` always agrees.

Upgrading from the old single-file setup: the Postgres volume keeps its name
(`aksor-khmer-bi_pgdata`), so `./deployment.sh down` on the old stack, then
`init` and `up`, picks the existing database straight up. A plain
`docker compose up` no longer starts a database — use the script.

```bash
# .env (init writes this for you)
PORTAL_USERNAME=admin
PORTAL_PASSWORD='pick something real'
```

Then:
- Swagger UI: http://localhost:8000/docs
- Management portal: http://localhost:8080
- Health check: http://localhost:8000/api/v1/health

The portal's own Admin mode embeds that same `/docs` Swagger UI in an
iframe (API Explorer) rather than reimplementing it — `/docs` and
`/openapi.json` are intentionally unauthenticated (matches FastAPI's
default), so this needs no CORS/CSP changes; individual endpoint calls
still need Swagger's own **Authorize**, separate from the portal's own
session: call `POST /auth/login` there, then paste the `access_token` into
*HTTPBearer* (or use *HTTPBasic* with a username and password — not for an
account with 2FA).

`docker compose up` alone (without the env vars) still starts both
services fine — every endpoint except the administrative
`/api/v1/reports` routes works with no credentials configured. Those
specifically fail closed (`503`) until `PORTAL_USERNAME`/
`PORTAL_PASSWORD` are set on the `api` service — see
[`api/app/auth.py`](../api/app/auth.py). Put the `export` lines in a
`.env` file next to `docker-compose.yml` instead of your shell if you'd
rather not retype them (`docker compose` reads it automatically); either
way, **do not commit that file**.

[`.env.example`](../.env.example) lists every setting with its default; `./deployment.sh init` copies it to `.env`
and fills in the passwords. `api`, `scheduler` and `worker` receive every variable in `.env` (compose's `env_file`), so the optional
settings in the reference table below need no compose edit — `scheduler`/`worker` are given an empty
break-glass login regardless. Set `DATABASE_URL`/`REDIS_URL` there to use managed services.

Those two variables are the *break-glass* superuser: sign in with them
once, create real accounts under **Admin → Users**, and (once someone
holds the system administrator role) you can remove them again. Accounts
you create are flagged *must change password* — the new user is asked to
choose their own at first sign-in, and an admin can reset any local user's
password later from the same screen (a generated temporary password is
shown once, and the user must replace it on their next sign-in).

### Publishing images to Docker Hub

Two images are published: `<prefix>-engine` (the API; also runs `scheduler` and `worker`) and `<prefix>-portal`.

1. **Create the repositories** on hub.docker.com — `aksor-khmer-bi-engine` and `aksor-khmer-bi-portal` under your
   user or organization (or let the first push create them; choose *private* if the image shouldn't be public).
2. **Log in** with an access token, not your password (Account settings → Personal access tokens → *Read & Write*):
   ```bash
   docker login -u aksorkhmerbi
   ```
3. **Set the prefix** in `.env`: `AKSOR_IMAGE_PREFIX=aksorkhmerbi/aksor-khmer-bi`
4. **Publish**:
   ```bash
   ./deployment.sh publish 1.0.1 --latest     # --latest also moves the :latest tag
   ```
   which is, for each of engine (`Dockerfile`) and portal (`portal/Dockerfile`), both with context `.`:
   ```bash
   docker buildx build --platform linux/amd64 \
     -t aksorkhmerbi/aksor-khmer-bi-engine:1.0.1 -t aksorkhmerbi/aksor-khmer-bi-engine:latest --push .
   ```
   The platform defaults to **`linux/amd64`** because most servers are Intel/AMD even when you build on an
   Apple-silicon Mac — an arm64 image would die on them with `exec format error`. For both, set
   `PLATFORMS=linux/amd64,linux/arm64` (the api image is large — LibreOffice — so the arm64 half builds slowly
   under emulation).
5. **Deploy from the registry** on the server (it needs this repo's compose files and `.env`, not the source
   build):
   ```bash
   AKSOR_VERSION=1.0.1 ./deployment.sh up --from-registry        # first time
   AKSOR_VERSION=1.0.2 ./deployment.sh update --from-registry    # upgrade: backup, pull, recreate, migrate
   ```
   (Put `AKSOR_VERSION` in `.env` to make it stick.) A private repository needs `docker login` on the server too.

Notes:
- **Pin a version** (`1.0.1`) in `.env` rather than relying on `latest`, so a restart can never silently pick up a
  new release, and a rollback is just setting the old tag and running `up --from-registry`. Database migrations
  only move forward, so take the backup `update` makes before upgrading, and restore it to roll back across a
  schema change.
- **The portal's API URL is not in the image's control:** `portal/public/config.js` ships pointing at
  `http://localhost:8000`, so compose bind-mounts your own copy over it (`PORTAL_CONFIG_FILE`, default
  `./portal/public/config.js`). On a server with no checkout, copy that file there, edit
  `PORTAL_API_BASE_URL`, and point `PORTAL_CONFIG_FILE` at it.
- Never bake secrets into an image: passwords and keys come from `.env` at run time, and `.dockerignore` keeps
  `.env` out of the build context. Images on Docker Hub can be pulled by anyone if the repository is public.
- Images are not signed or scanned by this script; Docker Hub's Scout or `docker scout cves <image>` can do the
  latter.

### Two origins now — CORS and the portal's API URL

Since `portal` and `api` are separate instances, two things need to
agree on where each other are:

- **`api`'s `CORS_ALLOWED_ORIGINS`** — a comma-separated allowlist of
  origins the browser is allowed to call this API from. `docker-compose.yml`
  defaults it to `http://localhost:8080` (the `portal` service's
  published port); override it for any other deployment.
- **`portal/public/config.js`**'s `window.PORTAL_API_BASE_URL` — where the
  portal's JS sends its requests. Defaults to `http://localhost:8000`.
  Edit this file directly (or bind-mount a replacement over it) for a
  non-default `api` URL — it's deliberately loaded as a plain `<script>`
  before the app bundle and left out of the Vite build, so changing it
  doesn't require rebuilding the image.

Get either wrong and the symptom is the portal's login silently failing
— check the browser console for a CORS error before assuming the
credentials are wrong.

**A third condition, since sign-in uses a cookie:** the portal and the API
must be on the **same site** (the same registrable domain — ports and
subdomains don't matter), because the refresh cookie is `SameSite=Lax`.
`localhost:8080` → `localhost:8000` and `reports.example.com` →
`api.example.com` work; `localhost` → `127.0.0.1` does not. If you can't
share a domain, set `AUTH_COOKIE_SAMESITE=none` (HTTPS only), or put both
behind one reverse proxy. See [Sign-in and sessions](authentication.md#deploying-it).

### Report metadata database

`api` stores report *metadata* (name, description, version, timestamps,
`sample_context`) **and** the multi-tenant auth/RBAC schema
(organizations, users, roles, permissions, and three expiring
access-grant tables — see `api/README.md`'s "Multi-tenant auth, roles &
permissions") in the same Postgres database — see
[`api/app/db.py`](../api/app/db.py). No separate database or service is
needed for this; it's all one schema, migrated together
(`api/migrations/`). The template *files themselves* are unaffected:
still plain files under `./data/report_templates/` (see the volumes
table below). That directory also holds every earlier version of each
template (`<report_id>/versions/`) — back it up, and expect it to grow
with each replace; nothing prunes it.

`docker-compose.db.yml`'s `postgres` service uses `POSTGRES_PASSWORD` (default
`aksor`, override it for anything beyond local use) and a named volume
(`pgdata`) so data survives `down`; `deployment.sh up` waits for it to be healthy
before starting the app (and `api` restarts until it can connect), and `api`
gets `DATABASE_URL` wired to it automatically — no manual configuration
needed for the Docker path. `api`'s entrypoint
([`api/docker-entrypoint.sh`](../api/docker-entrypoint.sh)) runs
`alembic upgrade head` against `DATABASE_URL` before starting uvicorn on
every container start, so the schema is always current — a fully-migrated
database makes this a fast no-op, not a risk of running it repeatedly.

#### Migrations were squashed

The whole schema now lives in one migration, `0001_initial_schema` (the report version labels, uploaded JDBC
drivers and sign-in sessions that came after the first squash are folded into it too). A **new** database just runs
`alembic upgrade head`. A database that was created by one of the folded-in revisions can't be upgraded
by it — `alembic upgrade head` stops with *"Can't locate revision identified by '000N_…'"*. Check what yours holds
with `alembic current`, then:

| `alembic current` says | What to do |
|---|---|
| `0005_auth_sessions` | The schema is already complete. Just re-label it: `alembic stamp --purge 0001_initial_schema` |
| `0004_jdbc_drivers` or `0003_report_label_unique` | Create the one or two tables it lacks, then re-label: `python -c "from app import db; db.Base.metadata.create_all(db.engine)"` then `alembic stamp --purge 0001_initial_schema` (run both in `api/` with the same `DATABASE_URL` as the API) |
| anything older | Recreate the database — `alembic upgrade head` on an empty one — or ask for help migrating its data |

(`create_all` only adds tables that are missing; it never touches existing ones. Back up first: `./deployment.sh backup`.)
Nothing in the files under `data/` is affected — only the database's own bookkeeping.

Running `api` without Docker (or without the `postgres` service) falls
back to a local SQLite file (`api/aksor_khmer_bi.db`) if `DATABASE_URL` is
unset — fine for a single-instance/local setup, not for multiple `api`
replicas writing concurrently.

### AD/LDAP login

Configured entirely through the API, not environment variables — see
`api/README.md`'s "AD/LDAP login" section and
[`api/app/auth_ldap.py`](../api/app/auth_ldap.py) for the three bind
methods. The one thing that *is* environment-variable-based on purpose:
a `search_bind` config's service-account password is never stored in the
database, only the *name* of an environment variable it lives in
(`service_bind_password_env`) — set that variable on the `api` service
the same way `PORTAL_PASSWORD` is set today.

No real Active Directory is reachable from this project's own dev/CI
environment, so the bind logic is verified against a real (not mocked)
OpenLDAP server instead — same connection code targets a real AD in
production, just with different config values:

```bash
docker compose -f docker-compose.yml -f docker-compose.ldap-dev.yml up -d openldap
./scripts/seed-ldap-dev.sh
```

This gives you `ldap://localhost:3389`, base DN `dc=aksor,dc=test`, two
users (`jdoe`/`JaneSecret123`, `bsmith`/`BobSecret123`), and two groups
(`report-admins`, `report-viewers`) — see
[`api/tests/fixtures/ldap-seed.ldif`](../api/tests/fixtures/ldap-seed.ldif).
Plain OpenLDAP's default ACL only lets a bound user read *their own*
entry, which blocks group-membership lookups entirely (confirmed the
hard way, not assumed) — the seed step also applies
[`ldap-acl.ldif`](../api/tests/fixtures/ldap-acl.ldif), a realistic ACL
that opens read access to the group subtree specifically. `upn_bind`'s
*success* path can only be verified against real AD (`user@domain` bind
DNs are an AD-specific convenience with no OpenLDAP equivalent) — against
the dev server it's verified to fail closed instead.
`.github/workflows/ci.yml` runs the same setup in CI, so these aren't
just locally-verified claims.

### Job scheduling

Split into two services on purpose (see `api/README.md`'s "Job
scheduling" section and [`api/app/scheduler.py`](../api/app/scheduler.py)'s
module docstring for the full reasoning): `scheduler` decides *when* a
job fires (APScheduler, single replica — `depends_on: api:
condition: service_healthy` so it never queries the `jobs` table before
`api`'s entrypoint has finished migrating the schema) and `worker`
(Celery, horizontally scalable — `./deployment.sh app up -d --scale worker=3`)
actually runs it, with per-job retry/backoff. Both use the same
`DATABASE_URL` as `api` and a new `REDIS_URL` pointing at the `redis`
service.

Both `scheduler` and `worker` use
[`api/docker-entrypoint-no-migrate.sh`](../api/docker-entrypoint-no-migrate.sh)
instead of the image's default entrypoint — running `alembic upgrade
head` from three processes concurrently on every `docker compose up`
isn't a risk worth taking just to make each service independently
self-sufficient; `api`'s healthcheck is what the other two actually wait
on.

Verified against real infrastructure, not just unit-tested — and this
specifically caught two real bugs before they'd have shown up in
production: APScheduler's `SQLAlchemyJobStore` refusing to pickle a
scheduler instance passed as a job argument, and a naive reconcile loop
that reset an unchanged job's next-fire time on *every* poll (so a
10-second interval job polled every 5 seconds never actually reached its
fire time — invisible to a test that calls the reconcile function once,
only caught by watching the real poll loop run across real wall-clock
time). [`api/tests/test_scheduler_integration.py`](../api/tests/test_scheduler_integration.py)
runs real `scheduler`/`worker` subprocesses against a real Redis and
asserts a job fires **on its own** (not manually triggered) and that an
induced REST-call failure actually retries with backoff before failing
for good — skipped, not failed, if no Redis is reachable locally;
`.github/workflows/ci.yml` runs a `redis` service so it isn't skipped
there.

### What the image actually contains, and why it's large

`Dockerfile` is `python:3.12-slim` plus: `tesseract-ocr` + `tesseract-ocr-khm`
(OCR), `libicu-dev` (PyICU, for `aksor_khmer_ocr_segmenter`), `libreoffice`
(the docx/xlsx → pdf/png conversion engine), `poppler-utils` (`pdftoppm`,
for the png path), and WeasyPrint's runtime libs
(`libpango`/`libcairo`/etc.). LibreOffice alone accounts for most of the
image's size — there's no slimmer variant that keeps the `libreoffice`
backend's native Khmer justify working, which is the entire reason that
backend exists (see [`khmer-line-breaking.md`](khmer-line-breaking.md)).
If you only ever need the `weasyprint` backend and don't need the
`libreoffice` backend or xlsx templates at all, you could fork the
Dockerfile to drop `libreoffice` — not done here since it's the default,
recommended backend.

The bundled Khmer fonts (`templates/fonts/*.ttf`) are copied into
`/usr/share/fonts/truetype/aksor-khmer` and registered with `fc-cache` at
build time — this step exists because LibreOffice needs fonts installed
system-wide to find them by name during conversion; WeasyPrint doesn't
need this since it loads font files directly via `@font-face`. If you
register your own template (via `/api/v1/reports`) that references a
font by name and that font isn't one of the two bundled ones, install it
the same way in a derived image, or the docx→pdf/png path will silently
substitute a fallback font.

### Volumes — what's mounted and why

| Host path | Container path | Purpose |
|---|---|---|
| `./api/khmer_protected_terms.txt` | same, `:ro` | This deployment's Khmer protected-terms additions — see [`protected-terms-guide.md`](protected-terms-guide.md) |
| `./api/khmer_protected_terms.exclude.txt` | same, `:ro` | The inverse — suppress a shared built-in term |
| `./api/khmer_protected_terms.d` | same, `:ro` | Directory form of the first row — drop any number of `*.txt` exception files in here instead of editing one file |
| `./api/khmer_protected_terms.exclude.d` | same, `:ro` | Directory form of the second row |
| `./data/report_templates` | `/app/data/report_templates`, read-write | Templates registered via `/api/v1/reports` — deliberately outside `api/`'s own directory (runtime data, not code), same reasoning as `api`/`portal` being separate services. Without this mount, uploads are lost on `docker compose down` / container recreate, since they'd otherwise only live in the container's writable layer |
| `./data/image_resources`, `./data/stylesheet_resources`, `./data/avatars` | `/app/data/…`, read-write (`api`; the first two also `worker`) | The Resources library (images and stylesheets that html templates and docx image fields render from) and user avatars. These were **not mounted before** and were lost whenever the container was recreated — mounted now; back them up with the templates (`./deployment.sh backup` does) |
| `pgdata` (named volume, not a bind mount) | `/var/lib/postgresql/data` on the `postgres` service | Report metadata (see above) — a named volume rather than a host path since there's no reason to browse/edit Postgres's on-disk files directly the way you would a `.txt` exception list |

The first two are read-only bind mounts specifically so editing either
file on the host takes effect on container **restart**, without an
image rebuild — they're baked into the image too (so a fresh deploy has
sane defaults), the mount just lets you override them live.

### Environment variables reference

| Variable | Required? | Purpose |
|---|---|---|
| `PORTAL_USERNAME` / `PORTAL_PASSWORD` | For the admin surface | The break-glass superuser: signs in through `POST /api/v1/auth/login` like anyone, and is how the first real accounts get created. With neither this nor any user, every protected route returns `503`, not open access. Set on the `api` service. |
| `API_PORT` / `PORTAL_PORT` | No (defaults 8000 / 8080) | The host ports the `api` and `portal` services are published on. After changing them, keep `CORS_ALLOWED_ORIGINS` (portal port) and the portal config file's `PORTAL_API_BASE_URL` (API port) in step. |
| `BUILD_NETWORK` / `APT_MIRROR` / `PIP_INDEX_URL` / `NPM_REGISTRY` | No (defaults: `default`, the public Debian / PyPI / npm) | Where the image **build** downloads packages from. `BUILD_NETWORK=host` builds on the server's own network (a fix when Docker's bridge can't reach the internet, e.g. UFW forwarding on Ubuntu); the three mirror settings point it at internal mirrors. Only used by `up --build`. See DEPLOYMENT.md, "Get Docker ready first". |
| `CORS_ALLOWED_ORIGINS` | For the portal to work at all | Comma-separated origins allowed to call `api` cross-origin — the portal's **exact** origin. Also what lets the browser send the refresh cookie to `/api/v1/auth/*`, and the origins those cookie routes accept. Set on the `api` service. |
| `JWT_SECRET` | Only with more than one `api` replica | 32+ characters; the key access tokens are signed with. Unset: generated into `data/secrets/jwt.key` on first use (kept in the mounted `data/secrets`). All replicas must share one. Losing or changing it only signs everyone out. See [Sign-in and sessions](authentication.md). |
| `ACCESS_TOKEN_TTL_SECONDS` | No | Access-token lifetime, 60–3600 (default 900 = 15 minutes). |
| `REFRESH_TOKEN_SESSION_HOURS` / `REFRESH_TOKEN_TTL_DAYS` | No | How long a sign-in lasts: 12 hours by default, 30 days with "Keep me signed in". |
| `REFRESH_GRACE_SECONDS` | No | Default 10. Forgives two browser tabs refreshing in the same moment; a refresh token replayed after this revokes its session. |
| `LOGIN_ATTEMPTS_PER_MINUTE` | No | Default 10: sign-in attempts per minute per client address and user name (5× that per address) before `429`. Per `api` process. |
| `AUTH_ALLOW_BASIC` | No | Default `true`: scripts may send `curl -u user:password`. `false` forces every client through `/auth/login`. Accounts with 2FA can't use Basic either way. |
| `AUTH_COOKIE_SECURE` / `AUTH_COOKIE_SAMESITE` | No | The refresh cookie's `Secure` flag (`auto`: on when the request is HTTPS or a proxy sent `X-Forwarded-Proto: https`) and `SameSite` (`lax`, `strict`, `none`). |
| `SECRETS_ENCRYPTION_KEY` | No | A [Fernet](https://cryptography.io/en/latest/fernet/) key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) that encrypts every Secret and every user's two-factor (authenticator-app) secret (Admin → Secrets — a named credential a connection or a report's own data source refers to by name instead of an environment variable). Leave it unset and the API generates one into `data/secrets/master.key` on first use — `docker-compose.yml` mounts that directory, so it survives restarts. **Back the key up with the database**: without it those credentials can't be decrypted and must be re-entered, and users with 2FA must re-enrol (an administrator clears it under Admin → Users) — nothing else is lost. Set on the `api` service. |
| `JDBC_WORKER_TOKEN` | To use uploaded JDBC drivers | A long random string (at least 32 characters — generate with `openssl rand -hex 32`; there is no default or example value) shared by `api` and the `jdbc-worker` service; the worker refuses to start without it, and `api` sends it with every query that runs on an uploaded driver. Not needed for PostgreSQL/MySQL/MariaDB connections. See [Database connections](#database-connections-and-jdbc-drivers). |
| `JDBC_WORKER_URL` | No | Where `api` finds the driver service (default `http://jdbc-worker:9000`). |
| `JDBC_ALLOWED_HOSTS` | No | Comma-separated hosts, `*.suffix` patterns or CIDRs that a database connection may point at; unset allows any host except link-local and cloud-metadata addresses (always refused). Set on `api`. |
| `JDBC_MAX_ROWS` / `JDBC_TIMEOUT_SECONDS` / `JDBC_DRIVER_MAX_MB` | No | Largest result a report query may return (20000 rows), how long it may run (30 s), and the largest driver upload (80 MB). |
| `EMBED_TICKET_SECRET` | To embed a report that has a data source | 32+ characters, shared with the embedding app (partner-api calls it `AKSOR_EMBED_SECRET`). Verifies the short-lived signed tickets that authorize `POST /api/v1/reports/{id}/embed-run` — see [Embedding a report that fetches its own data](building-a-report.md#embedding-a-report-that-fetches-its-own-data). Unset = that route answers `503`, never open access. Set on the `api` service. |
| `CLIENT_RUN_LIMIT_PER_MINUTE` | No | Most `embed-run` calls per minute one **API client** (client id + secret, Admin → API Clients) may make; over it, `429`. Default 120. Clients themselves are created in the portal -- no environment variable per report. See [Running a report as an API client](building-a-report.md#running-a-report-as-an-api-client-client-id--secret). |
| `REPORT_TIMEZONE` | No | IANA time zone (e.g. `Asia/Phnom_Penh`; default `UTC`) that a parameter's `now()` default is read in when a run leaves that parameter out -- an API call or an embed. The portal's own run form fills `now()` from the viewer's browser clock instead. An unknown name is logged and falls back to UTC. See [Filters and a data source](building-a-report.md#filters-a-data-source-and-connections). Set on `api` |
| `AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE` / `AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE` | No | Extra Khmer terms this deployment has observed ICU mis-splitting, on top of the shared package's built-ins — see [`protected-terms-guide.md`](protected-terms-guide.md) |
| `AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR` / `AKSOR_KHMER_OCR_EXCLUDED_TERMS_DIR` | No | Directory form of the row above — every `*.txt` file inside is merged in |
| `DATABASE_URL` | No | Report metadata database connection string — `docker-compose.yml` sets this to the `postgres` service automatically; unset falls back to a local SQLite file (`api/aksor_khmer_bi.db`). See `api/app/db.py` |
| `POSTGRES_PASSWORD` | For the `postgres` service | Password for both the `postgres` service and `api`'s `DATABASE_URL` — change it in one place, `docker-compose.yml` threads it to both |
| `REDIS_URL` | No | Celery broker/result-backend connection string for `api` (enqueue only), `scheduler`, and `worker` — unset falls back to `redis://localhost:6379/0`. See `api/app/celery_app.py` |
| `SCHEDULER_RECONCILE_INTERVAL_SECONDS` | No | How often `scheduler` polls the `jobs` table for create/edit/pause/delete (default 15) — see `api/app/scheduler.py` |
| `LOG_LEVEL` | No | Root logging level for `api` and `scheduler` — `DEBUG`, `INFO` (default), `WARNING`/`WARN`, or `ERROR`. Set `DEBUG` to see per-request/job chatter; tracebacks logged via `_log.exception(...)` print at `ERROR` and above regardless. See `api/app/logging_config.py` |
| `LOG_DIR` | No | Directory for rotating log files, relative to the process's cwd (default `logs`, i.e. `api/logs` locally or `/app/api/logs` in the container — `docker-compose.yml` bind-mounts that to `./data/logs` on the host for both `api` and `scheduler`) |
| `LOG_MAX_BYTES` | No | Max size of one log file before it rolls to the next sequence number for the same date (default 25MB, i.e. `api-2026-09-15.log` → `api-2026-09-15.1.log`) — see `api/app/logging_config.py` |
| `MAX_ROWS_PER_FILE` | No | Most rows of a report's repeating table in one output file (default 1,000; values above 5,000 are clamped down). A larger table is rendered as several files and returned as a ZIP — see [`building-a-report.md`](building-a-report.md#very-long-tables-automatic-splitting-into-files). Set on `api` |
| `MAX_BATCH_PDF_PNG` / `MAX_BATCH_DOCX_XLSX` | No | Most records in one batch-render request: for `pdf`/`png` (default 30, at most 200 — each is a ~2 s LibreOffice conversion) and for `docx`/`xlsx` (default 1,000, at most 5,000 — ~10 ms each). Over the limit is a `400` before anything renders; `GET /api/v1/reports/batch-limits` reports the live values. Set on `api` |
| `MAX_REPORT_PARTS` | No | Most files one request may produce (default 20, at most 100) — the bound on how long a split report's single request can run. Set on `api` |
| `DOC_ENGINE_SOFFICE_BIN` | No | Override the `soffice` binary path if it's not resolvable via `PATH` (Linux/Docker) or the default macOS `.app` location — see `packages/doc_engine/src/doc_engine/config.py` |

`GET /api/v1/system/metrics` (host CPU/RAM/disk/thread metrics, backing
the portal's Monitor page) is gated on the existing `settings:manage`
permission rather than a new permission code — same sensitivity class as
the LDAP config endpoints, which use the same gate. It reports the host
`api` runs on, with no per-organization scoping.

## Database connections and JDBC drivers

A report can run a read-only SQL query against Oracle, PostgreSQL, MySQL, SQL Server, MariaDB or Db2
(Admin → Connections → *+ Database*; see docs/building-a-report.md). **PostgreSQL, MySQL and MariaDB need
nothing here** — their drivers ship in the `api` image. The other engines need the vendor's JDBC driver
uploaded in the portal (Admin → JDBC Drivers), and a driver is code the server runs, so it runs in a
separate, locked-down container instead of in `api`:

```bash
# in .env: JDBC_WORKER_TOKEN=<a long random string>
docker compose --profile jdbc up -d --build jdbc-worker api
```

The `jdbc-worker` service has no published port, a read-only filesystem and read-only drivers, no
capabilities, capped memory/CPU/processes, and its own network (`aksor-jdbc`, shared only with `api`) —
so a driver can't reach PostgreSQL or Redis. It holds no database credentials or encryption key: each
query carries the one connection's login, used and forgotten. Every query runs in a fresh JVM that is
killed at the timeout, and a driver is loaded only if its SHA-256 still matches the one recorded at
upload. The files live in `data/jdbc_drivers/` (mounted into both services — back it up with `data/`).

The worker can reach whatever the host's network can, because that is how it reaches your databases;
use the host firewall, or `JDBC_ALLOWED_HOSTS` on `api`, to limit which. Database passwords are
Secrets (encrypted with `SECRETS_ENCRYPTION_KEY` / `data/secrets/master.key`), and connections should use
a **read-only** database account.

## TLS — not included, add a reverse proxy

Neither Dockerfile terminates TLS. Sign-in sends the password to `/auth/login`, and every
call after it carries the access token in a header while the refresh cookie rides to
`/api/v1/auth/*` — none of that is encrypted on plain HTTP (and HTTP Basic, for scripts,
sends the password on every call), so running either service beyond a trusted internal
network without a TLS-terminating reverse proxy (nginx, Caddy, Traefik, a cloud load
balancer) in front would leak credentials in transit. On a trusted internal/VPN network
this is a reasonable tradeoff for how small the portal's scope is; it stops being one the
moment either service is reachable from the open internet.

Behind a proxy that terminates TLS, have it send `X-Forwarded-Proto: https` (and
`X-Forwarded-For`, which the sign-in log reads), so the refresh cookie is marked `Secure`
— or set `AUTH_COOKIE_SECURE=true`. `POST /auth/login` is throttled per client address and user name (`LOGIN_ATTEMPTS_PER_MINUTE`), per `api` process;
if the API is reachable from the internet, have the proxy limit it too, and consider `AUTH_ALLOW_BASIC=false`.

## Without Docker

The Dockerfile's apt-get list mirrors [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)'s
Ubuntu setup — same packages, same install order — so that workflow is
the reference for a bare-metal Linux install. On macOS for local
development, use [`packages/aksor_khmer_ocr_segmenter/scripts/setup_env.sh`](../packages/aksor_khmer_ocr_segmenter/scripts/setup_env.sh)
plus `brew install --cask libreoffice`, then:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -e packages/aksor_khmer_ocr_segmenter
pip install -e packages/doc_engine
pip install -r api/requirements.txt

cd api
export PORTAL_USERNAME=admin PORTAL_PASSWORD='pick something real'
export CORS_ALLOWED_ORIGINS=http://localhost:8080
# Optional: point at a real Postgres instead of the SQLite default --
# see "Report metadata database" above.
# export DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/aksor_khmer_bi
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For the portal:

```bash
cd portal
npm install
npm run build       # type-checks + bundles to dist/
npx serve dist -l 8080   # or any other static file server pointed at dist/
# or, for local development with hot-reload instead of a production build:
npm run dev
```

For job scheduling (needs a Redis reachable at `REDIS_URL`, e.g. `redis
run --name dev-redis -p 6379:6379 -d redis:7-alpine` or a native
install) -- from the same `api` directory/venv as above, no separate
migration step (the schema's already current from `api`'s own):

```bash
python -m app.scheduler                          # one process
celery -A app.celery_app worker --loglevel=info  # another
```

There's no process manager (systemd unit, supervisor config) included
for any of these — add one appropriate to your host if you're not
running this under Docker/an orchestrator that already restarts crashed
processes for you.
