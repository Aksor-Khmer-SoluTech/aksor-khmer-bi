# Deployment

This page has two halves. **[Install it](#install-it)** is the how-to: get Docker and the code, then start the stack
with one script or step by step, run it day to day, and fix what goes wrong. Everything from
**[Docker (recommended)](#docker-recommended)** onward is the reference: how it is built, the settings, volumes,
database, LDAP, scheduling, TLS and running without Docker.

---

## Install it

---

### Before you start (required for both options)

**Do these two things first, whichever way you deploy.**

#### A. Get Docker ready (Ubuntu, Debian, CentOS / RHEL / Rocky / Alma, and others)

**The application itself doesn't depend on your server's Linux.** It runs in containers built on a pinned Debian
release (`python:3.12-slim-trixie`), so CentOS, Ubuntu and Debian hosts all run the *same* image. What differs
between hosts is only (1) how Docker was installed, (2) whether containers can get out to the internet while
**building**, and (3) host security features such as SELinux and firewalls. That is what this section covers, and
`./deployment.sh doctor` checks the lot for you in seconds — `./deployment.sh up` runs it before every start.

Skip the installation if `docker --version` and `docker compose version` already answer. Otherwise install Docker
Engine and the Compose plugin from **Docker's own repository** — not the distribution's `docker.io` / `podman-docker`
packages or the snap, which are the usual source of odd networking problems. Only Docker Engine with Compose v2 is
supported; Podman is not tested.

**Ubuntu** (24.04 and others; for **Debian** replace `linux/ubuntu` with `linux/debian` in both URLs):

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"      # then log out and back in, so `docker` works without sudo
```

**CentOS Stream / RHEL / Rocky / AlmaLinux** (for Fedora use `…/linux/fedora/docker-ce.repo`, for RHEL `…/linux/rhel/…`):

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"      # then log out and back in
```

On these systems two things are different, and both are already handled or flagged for you:

- **SELinux** (enforcing by default) blocks a container from reading a mounted folder unless it is labelled. Every
  bind mount in `docker-compose.yml` carries the `z` label for exactly this, so `data/` just works. If you replace
  `PORTAL_CONFIG_FILE` with a file elsewhere, it is relabelled too.
- **firewalld** can stop containers reaching the internet and can block the published ports. Allow forwarding with
  `sudo firewall-cmd --permanent --zone=public --add-masquerade && sudo firewall-cmd --reload && sudo systemctl restart docker`,
  and open the ports people use: `sudo firewall-cmd --permanent --add-port=8080/tcp --add-port=8000/tcp && sudo firewall-cmd --reload`.

**macOS and Windows** (Docker Desktop) need none of this; give Docker Desktop at least 4 GB of memory.

**Before the first build, check that containers can reach the internet** — the build downloads Debian, Python and
npm packages, and this is where most first deployments fail:

```bash
curl -sI http://deb.debian.org | head -1                                   # the server itself
docker run --rm alpine wget -q -T 5 -O /dev/null http://deb.debian.org && echo "containers: ok"
```

| Server | Container | Meaning and fix |
|---|---|---|
| ok | ok | Nothing to do — go on to B. (`./deployment.sh doctor` does this check and more.) |
| ok | **fails** | Docker's network can't get out. Check, in this order: `sysctl net.ipv4.ip_forward` must print `1` (`sudo sysctl -w net.ipv4.ip_forward=1`); **UFW** drops forwarded traffic by default — set `DEFAULT_FORWARD_POLICY="ACCEPT"` in `/etc/default/ufw` and `sudo ufw reload`; Docker installed as a **snap** (`snap list docker`) — remove it and use the steps above; a DNS that containers can't use — put `{"dns": ["1.1.1.1", "8.8.8.8"]}` in `/etc/docker/daemon.json` and `sudo systemctl restart docker`. A quick workaround while you sort that out: `BUILD_NETWORK=host` in `.env` makes the **build** use the server's own network. |
| **fails** | fails | The server itself is cut off (a firewall, or an offline network). Build the images somewhere that has internet and ship them, or use internal mirrors — see the Troubleshooting row "`Unable to locate package`". |

#### B. Get the code (once)

You need Docker with the Compose v2 plugin, and ports **8000** (API) and **8080** (portal) free — or choose others with `API_PORT` / `PORTAL_PORT` in `.env` (see below).

```bash
git clone --depth 1 https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi.git
cd aksor-khmer-bi
docker --version && docker compose version     # both must answer
```

`--depth 1` downloads only the latest version (a few MB, no history); `git pull` still updates it later. The
repository is public, so **no username or password is needed**. If git asks for one anyway:

- Add `GIT_TERMINAL_PROMPT=0` in front (`GIT_TERMINAL_PROMPT=0 git clone --depth 1 …`) so it fails with the real
  error instead of a login prompt.
- Check the URL is spelled exactly as above (GitHub asks for a login when a repository name is wrong).
- Run `git config --global --list | grep -i -E "insteadof|credential"` -- a URL-rewrite rule or a stale saved
  credential on that machine is the usual cause. A proxy that intercepts GitHub can do the same.
- Or skip git: `curl -L https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/archive/refs/heads/main.tar.gz | tar xz`
  then `cd aksor-khmer-bi-main`. (No history, so no `git pull` -- download again to update.)

Run every command below **from this folder** (the one containing `docker-compose.yml`).

---

### Choose how to deploy

With Docker and the code ready, pick an option — each jumps straight to its instructions:

| | [**Quick deployment**](#option-1--quick-deployment-deploymentsh) | [**Step by step**](#option-2--step-by-step) |
|---|---|---|
| How | One script, `deployment.sh`, does everything and generates the passwords | You start one compose file at a time and check it before moving on |
| Best for | A **first** install on a fresh server (it creates the network, the data folders and `.env`) | An **existing** deployment you update by hand, or when you want to see what runs and change a step |
| Jump to | [Option 1 — Quick deployment](#option-1--quick-deployment-deploymentsh) | [Option 2 — Step by step](#option-2--step-by-step) |

### How the stack is put together

Each step starts **one** compose file, then checks it before you move on, so if something is wrong you know exactly
which step it was.

| Step | Compose file | Compose project | Starts |
|---|---|---|---|
| 1 | `docker-compose.redis.yml` | `aksor-redis` | `redis` — job queue |
| 2 | `docker-compose.db.yml` | `aksor-db` | `postgres` — the database |
| 3 | `docker-compose.yml` | `aksor-app` | `api`, `scheduler`, `worker`, `portal` |
| 4 *(optional)* | `docker-compose.yml` `--profile jdbc` | `aksor-app` | `jdbc-worker` — only for Oracle / SQL Server / Db2 drivers |

**Where the app's images come from.** `docker-compose.yml` has no build instructions: each app service runs a
prebuilt, version-pinned image from Docker Hub, so nothing is compiled on your server.

| Service | Image (`$AKSOR_IMAGE_PREFIX` = `aksorkhmerbi/aksor-khmer-bi`) |
|---|---|
| `api`, `scheduler`, `worker` | `$AKSOR_IMAGE_PREFIX-engine:$AKSOR_VERSION` (one image, three commands) |
| `portal` | `$AKSOR_IMAGE_PREFIX-portal:$AKSOR_VERSION` |
| `jdbc-worker` *(optional)* | `$AKSOR_IMAGE_PREFIX-jdbc-worker:$AKSOR_VERSION` |

| | **Prebuilt images** *(default, recommended)* | Build from source *(advanced)* |
|---|---|---|
| You set | `AKSOR_VERSION` in `.env` — a released version | nothing extra |
| Command | `./deployment.sh up` / `update` | `./deployment.sh up --build` / `update --build` |
| Compose files | `docker-compose.yml` | `docker-compose.yml` + `docker-compose.build.yml` |
| Needs | Docker and access to Docker Hub | internet for Debian, Python and npm packages, ~10 GB of disk, several minutes |
| Choose it for | every normal deployment and update | a fork, local changes, or an unreleased commit |

They share one Docker network, `aksor-network`, which is how the app finds `postgres` and `redis` by name.
Each file has its **own project name** (`-p …`) — keep them, or stopping one stack could remove another's
containers.

Tested while writing this: steps 1 and 2 were run for real, and the step 3 images were built on macOS (Docker Desktop).
The full start of step 3, `deployment.sh up` / `update` on a Linux server, and step 4 (the JDBC worker) were not run end
to end — if one of them fails on your server, the Troubleshooting table at the end is the place to start.

---

### Option 1 — Quick deployment: `deployment.sh`

> **Best for a first deployment.** `./deployment.sh init` is the first-time setup: it creates the `aksor-network`
> network and the `data/` folders if they are missing, and writes a new `.env` **only when there isn't one**. It
> never overwrites an existing `.env`, and `update` / `up` never edit it either. But the script decides things for you,
> so **if this server is already running, or you manage `.env` and the compose commands by hand, use
> [Step by step](#option-2--step-by-step) instead.** On an existing install:
>
> - **Don't run `init` again.** It is for the first deployment only.
> - **Read the [CHANGELOG](../CHANGELOG.md) before you update** — every entry between the version you run now and the one
>   you are upgrading to. Look for changes to `.env` settings, database migrations and anything marked breaking or
>   "upgrade note", and do what they say first.
> - **`up` and `update` pull prebuilt images by default.** Set `AKSOR_VERSION` in `.env` to the released version you
> read the changelog for, then `./deployment.sh update`: nothing is built, so the server needs no Node/npm and no
> access to npm or Debian. (Compose files and `deployment.sh` still come from `git pull`.) To build from the
> source instead, add `--build`.
> - **Back up `.env` yourself before updating** (`cp -p .env ../aksor.env.bak` — keep it outside the repository folder): it holds the database password and the portal
>   login. If `.env` is lost, `init` generates a *new* one, and the existing database keeps its old password.
> - A new version may add settings to `.env.example` that your `.env` doesn't have. They are never merged in
>   automatically; compare with `diff .env.example .env` after `git pull` and copy over what you want.

`deployment.sh` (in the repository folder) does the setup and steps 1–3 below for you, and is also how you update, back up and stop
the stack later. Docker and the code come first — see [Before you start](#before-you-start-required-for-both-options).

```bash
cd aksor-khmer-bi          # the folder from "Get the code"
./deployment.sh init       # once: creates the network, the data folders and .env with generated passwords
```

`init` prints the generated sign-in (`admin` and a random password — **shown only once, it is also saved in `.env`**).
Before you start, open `.env` and check `CORS_ALLOWED_ORIGINS` is the address people will type in the browser, and
change `API_PORT` / `PORTAL_PORT` if 8000 / 8080 are taken (every setting is explained in `.env.example`; see also
[Customizing](#customizing)). Then:

In `.env`, set `AKSOR_VERSION` to the released version you want (the image prefix is already set; read
[CHANGELOG.md](../CHANGELOG.md) first). Then:

```bash
./deployment.sh doctor     # optional: checks Docker, ports and disk, in seconds
./deployment.sh up         # starts redis, then postgres, then pulls and starts the app images
```

No build happens, so no Node/npm is needed. To build from the source instead (a fork, or a version that isn't
published), run `./deployment.sh up --build` (this adds `docker-compose.build.yml`) — the first build takes several minutes and needs internet for
Debian, Python and npm packages.

`up` runs `doctor` itself first, so a missing piece (a closed firewall, a busy port) is reported in
seconds with the fix. When it finishes it prints the portal and API-docs addresses. Open the
portal and sign in with the `admin` password from `init`.

Everything you do afterwards:

| I want to… | Command |
|---|---|
| see what is running | `./deployment.sh status` |
| read the logs | `./deployment.sh logs` (the API; add names for others: `logs api worker scheduler portal`) |
| update to the new version | read the [CHANGELOG](../CHANGELOG.md) for every version up to the one you want **first**; set `AKSOR_VERSION` in `.env`, `git pull`, then `./deployment.sh update` — takes a **backup first**, pulls that version's images, restarts the app (database migrations run as the API starts); Postgres and Redis are not touched. Flags: `--no-backup`, `--build` (build from source instead), `--pull` (with `--build`: refresh the base images) |
| back up now | `./deployment.sh backup` — the database plus templates, images, avatars and the encryption key, into `./backups/` (the newest 14 are kept; `BACKUP_KEEP=30` changes that) |
| apply a change in `.env` | `./deployment.sh up` (recreates only what changed) |
| restart | `./deployment.sh restart` (everything), or `restart app` / `restart db` / `restart redis` |
| stop everything | `./deployment.sh down` — your data is kept |
| operate one stack alone | `./deployment.sh app status`, `./deployment.sh db logs`, `./deployment.sh redis restart`, … |
| use uploaded JDBC drivers (Oracle, SQL Server…) | set `JDBC_WORKER_TOKEN` in `.env` ([Step 4](#step-4-optional--jdbc-driver-service)), then `./deployment.sh app --profile jdbc up -d --build jdbc-worker api` |
| deploy prebuilt images (no build, no Node/npm on the server) | in `.env` set `AKSOR_IMAGE_PREFIX=aksorkhmerbi/aksor-khmer-bi` and `AKSOR_VERSION=<released version>`, then `./deployment.sh up` (first time) or `update` (upgrade) — this is the default. Releases are published with `./deployment.sh publish <version>`. |
| see every command | `./deployment.sh help` |

A command that fails stops with a one-line `error:` that says what to fix. `./deployment.sh init` never overwrites an
existing `.env`, so it is safe to run twice.

---

### Option 2 — Step by step

Docker and the code come first — see [Before you start](#before-you-start-required-for-both-options). Run every command from the repository folder.

#### 0.1 Create the shared network

```bash
docker network create aksor-network
```

If it already exists Docker says so — that's fine.

#### 0.2 Create your settings file

```bash
cp .env.example .env
```

Open `.env` and fill in the three required lines:

```env
POSTGRES_PASSWORD=<a long random password>
PORTAL_USERNAME=admin
PORTAL_PASSWORD=<a long random password>
CORS_ALLOWED_ORIGINS=http://localhost:8080
```

Make passwords with `openssl rand -hex 16` (letters and digits only: `POSTGRES_PASSWORD` is placed inside a database URL, where `@ : / # %` would break it). `./deployment.sh up` refuses a guessable `PORTAL_PASSWORD` — under 8 characters, or `admin`, `password`, `changeme`… — because it is the full administrator login. `CORS_ALLOWED_ORIGINS` is **exactly what you type in the
browser** to open the portal — `http://localhost:8080` on your own machine, or
`https://reports.example.com` on a server. If it's wrong, the login silently fails.

**Ports.** The API is published on 8000 and the portal on 8080. If those are taken, add `API_PORT=…` and/or
`PORTAL_PORT=…` to `.env`. Then keep three things in step: `CORS_ALLOWED_ORIGINS` uses the portal's new port, and —
if you moved the API — `PORTAL_API_BASE_URL` in the portal config file (`portal/public/config.js`, or the file
`PORTAL_CONFIG_FILE` points to) uses the API's new port.

People sign in with a short-lived access token and a refresh cookie (see
[authentication.md](authentication.md)). Nothing to configure for that: the signing key is created for you in
`data/secrets/jwt.key` (it is covered by the `data/secrets` backup below). Two things must be true, or sign-in will
look like it works and then drop you on every reload: the portal and the API are on the **same site**
(`localhost` and `localhost` yes; `localhost` and `127.0.0.1` no), and `CORS_ALLOWED_ORIGINS` is the portal's exact
origin.

> `POSTGRES_PASSWORD` is applied when the database is **first created**. Changing it later in `.env` does not
> change an existing database's password (see Troubleshooting).

#### 0.3 Create the data folders

The app stores templates, credentials' encryption key, images and logs on disk. Create the folders yourself so
they belong to you, not to root:

```bash
mkdir -p data/report_templates data/secrets data/image_resources data/stylesheet_resources data/avatars data/logs data/jdbc_drivers data/font_resources
```

**Back up `data/secrets/` together with the database** — without its key, saved credentials and users' 2FA secrets can't be decrypted. (It also holds the sign-in signing key; losing that only signs everyone out.)

---

### Step 1 — Redis

```bash
docker compose -p aksor-redis -f docker-compose.redis.yml up -d --wait
```

`--wait` returns when the container reports healthy. Expected: `Container aksor-redis-redis-1  Healthy`.

Check it:

```bash
docker compose -p aksor-redis -f docker-compose.redis.yml ps
docker run --rm --network aksor-network redis:7-alpine redis-cli -h redis ping      # PONG
```

If you set `REDIS_PASSWORD` in `.env` (recommended; `./deployment.sh init` generates one), Redis refuses everything without it, so only the app can use the queue — and the check becomes `docker run --rm --network aksor-network -e REDISCLI_AUTH=<the password> redis:7-alpine redis-cli -h redis ping`. Set it **before** step 3 (or recreate Redis and the app after adding it: `./deployment.sh up`). Without it, any container on `aksor-network` can use Redis, and anything that can reach the queue can enqueue jobs.

### Step 2 — Postgres

```bash
docker compose -p aksor-db -f docker-compose.db.yml up -d --wait
```

Check it:

```bash
docker compose -p aksor-db -f docker-compose.db.yml ps
docker run --rm --network aksor-network -e PGPASSWORD="$(grep ^POSTGRES_PASSWORD= .env | cut -d= -f2-)" \
  postgres:16-alpine psql -h postgres -U aksor -d aksor_khmer_bi -tAc "select 'postgres ok'"      # postgres ok
```

Postgres is deliberately **not** published on a host port; only containers on `aksor-network` reach it.

### Step 3 — The application

Set `AKSOR_VERSION` in `.env` to the released version you want (read [CHANGELOG.md](../CHANGELOG.md) first), then
pull the prebuilt images and start:

```bash
docker compose -p aksor-app -f docker-compose.yml pull
docker compose -p aksor-app -f docker-compose.yml up -d --wait
```

No build, so no Node/npm is needed. To build from the source instead (several minutes — it installs LibreOffice,
Tesseract and fonts; later builds reuse the cache), skip `pull` and run
`docker compose -p aksor-app -f docker-compose.yml -f docker-compose.build.yml up -d --build --wait`. What happens:

1. `api` starts, **runs the database migrations**, then serves on port 8000. Its health check gates the next two.
2. `scheduler` and `worker` start once `api` is healthy.
3. `portal` serves the web console on port 8080.

Check it:

```bash
docker compose -p aksor-app -f docker-compose.yml ps                 # api, scheduler, worker, portal: running / healthy
curl http://localhost:8000/api/v1/health                              # {"status":"ok"}
```

Then open **http://localhost:8080** and sign in with `PORTAL_USERNAME` / `PORTAL_PASSWORD` from `.env`.
Create real accounts under **Admin → Users**, then delete the two `PORTAL_*` lines from `.env` and run
`docker compose -p aksor-app -f docker-compose.yml up -d` to apply it.

API docs are at http://localhost:8000/docs.

### Step 4 (optional) — JDBC driver service

Only needed if you upload vendor JDBC drivers (Oracle, SQL Server, Db2). PostgreSQL, MySQL and MariaDB
connections work without it.

1. Add to `.env` a long random token: `JDBC_WORKER_TOKEN=<openssl rand -hex 32>`
2. Start the worker (same project as the app) and recreate `api` so it picks the token up:

```bash
docker compose -p aksor-app -f docker-compose.yml --profile jdbc pull jdbc-worker
docker compose -p aksor-app -f docker-compose.yml --profile jdbc up -d jdbc-worker api
docker compose -p aksor-app -f docker-compose.yml --profile jdbc ps jdbc-worker       # running / healthy
```

Then upload a driver under **Admin → JDBC Drivers**.

---

### Running it every day

| I want to… | Command |
|---|---|
| see what's running | `docker compose -p aksor-app -f docker-compose.yml ps` (and `-p aksor-db`, `-p aksor-redis` with their files) |
| read the API log | `docker compose -p aksor-app -f docker-compose.yml logs -f api` |
| deploy a new version | read the [CHANGELOG](../CHANGELOG.md), set the new `AKSOR_VERSION` in `.env`, then `docker compose -p aksor-app -f docker-compose.yml pull` and `… up -d --wait` — only the app restarts; migrations run as `api` starts; the database and Redis are untouched |
| restart one service | `docker compose -p aksor-app -f docker-compose.yml restart api` |
| apply a `.env` change | `docker compose -p aksor-app -f docker-compose.yml up -d` (recreates what changed) |

#### Stop and start again

Stop in the **reverse** order, start in the **same** order as above:

```bash
docker compose -p aksor-app   -f docker-compose.yml       down
docker compose -p aksor-db    -f docker-compose.db.yml    down
docker compose -p aksor-redis -f docker-compose.redis.yml down
```

Your data is kept (named volumes and the `data/` folder). **Never add `-v`** to those commands unless you mean to
delete the database / queue.

#### Back up

```bash
mkdir -p backups
docker compose -p aksor-db -f docker-compose.db.yml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip > backups/aksor-$(date +%Y%m%d-%H%M).sql.gz
sudo tar -czf backups/aksor-files-$(date +%Y%m%d-%H%M).tar.gz data/report_templates data/secrets data/image_resources data/stylesheet_resources data/avatars data/jdbc_drivers data/font_resources
```

Keep the two files together — the encryption key in `data/secrets` and the database belong to each other. (`sudo` because the containers write `data/` as root, and the key inside `data/secrets` is mode 600; `./deployment.sh backup` handles that for you.)

#### Restore a backup

With the script: `./deployment.sh restore backups/aksor-<time>.sql.gz` (it finds `aksor-<time>-files.tar.gz` next to it, or name it as a second argument). It shows what it will replace and asks you to type `restore`; it takes a **safety backup of the current state** first (`--no-backup` skips that), stops the app, recreates the database from the dump, and moves the current `data/` folders to `data.before-restore-<time>/` (kept, not deleted) before unpacking the archive. Then start it: `./deployment.sh up`. Set `AKSOR_VERSION` in `.env` to the version the backup was made with, or newer — migrations only go forward, so a newer database under older code isn't supported. `--yes` skips the question (for scripts).

By hand: `./deployment.sh down` (or stop `aksor-app`), then
`docker compose -p aksor-db -f docker-compose.db.yml exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'`,
`gunzip -c backups/aksor-<time>.sql.gz | docker compose -p aksor-db -f docker-compose.db.yml exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q'`, and `sudo tar -xzf backups/aksor-files-<time>.tar.gz` from the repository folder.

---

### Variations

**Managed Postgres / Redis (RDS, ElastiCache, …).** Skip steps 1 and 2, and put these in `.env`:

```env
DATABASE_URL=postgresql+psycopg://user:password@db.example.com:5432/aksor_khmer_bi
REDIS_URL=redis://redis.example.com:6379/0
```

You still need the network (0.1) because the app joins it.

**A server with a domain name.** Two settings must name your public address:

1. `CORS_ALLOWED_ORIGINS=https://reports.example.com` in `.env`.
2. The portal's `window.PORTAL_API_BASE_URL` (on the **same site** as the portal — e.g. `reports.example.com` and `api.example.com`, or one domain behind a proxy — because sign-in uses a cookie) — copy `portal/public/config.js` somewhere, change that line to your API's
   public URL, and set `PORTAL_CONFIG_FILE=/path/to/that/config.js` in `.env`. Recreate the portal with
   `docker compose -p aksor-app -f docker-compose.yml up -d portal`.

TLS is not included — put a reverse proxy (Caddy, nginx, Traefik) in front of ports 8080 and 8000.

**Try LDAP / Active Directory login locally.** `docker compose -f docker-compose.yml -f docker-compose.ldap-dev.yml up -d openldap`
starts a throwaway test directory (see the comments at the top of that file). Never use it on a real server.

---

### Customizing

Everything you can change is in **`.env`**, and `.env.example` explains every setting and shows its default — read it
top to bottom once. Edit `.env`, then apply it:

| I want to… | Setting in `.env` | Then run |
|---|---|---|
| use other ports | `API_PORT`, `PORTAL_PORT` (also `CORS_ALLOWED_ORIGINS`; and `PORTAL_API_BASE_URL` in the portal config file if the API moved) | `docker compose -p aksor-app -f docker-compose.yml up -d` |
| serve it on a domain name | `CORS_ALLOWED_ORIGINS`, and the portal config file — see "A server with a domain name" | `… up -d` |
| change the portal's name, logo or API address | the file `PORTAL_CONFIG_FILE` points to (default `portal/public/config.js`) | `… up -d portal` |
| keep people signed in longer / shorter | `REFRESH_TOKEN_SESSION_HOURS`, `REFRESH_TOKEN_TTL_DAYS`, `ACCESS_TOKEN_TTL_SECONDS` | `… up -d` |
| allow more or fewer sign-in attempts | `LOGIN_ATTEMPTS_PER_MINUTE` | `… up -d` |
| read dates in my time zone when a run omits them | `REPORT_TIMEZONE` (e.g. `Asia/Phnom_Penh`) | `… up -d` |
| raise or lower report size and speed limits | `MAX_ROWS_PER_FILE`, `MAX_REPORT_PARTS`, `MAX_BATCH_*`, `JDBC_MAX_ROWS`, `JDBC_TIMEOUT_SECONDS` | `… up -d` |
| lock database connections to certain hosts | `JDBC_ALLOWED_HOSTS` | `… up -d` |
| log more or less | `LOG_LEVEL` (`DEBUG` while investigating), `LOG_MAX_BYTES` | `… up -d` |
| use my own database or Redis | `DATABASE_URL`, `REDIS_URL` (and skip steps 1–2) | `… up -d` |
| keep the signing / encryption keys outside `data/` | `JWT_SECRET`, `SECRETS_ENCRYPTION_KEY` | `… up -d` |
| build on a server with a restricted network | `BUILD_NETWORK`, `APT_MIRROR`, `PIP_INDEX_URL`, `NPM_REGISTRY` | `… -f docker-compose.yml -f docker-compose.build.yml up -d --build` (these only matter when building from source) |
| which prebuilt images to deploy (build from source with `--build`) | `AKSOR_IMAGE_PREFIX`, `AKSOR_VERSION` | `./deployment.sh up` |

`… up -d` is short for `docker compose -p aksor-app -f docker-compose.yml up -d`: it recreates only the services
whose settings changed, and leaves the database and Redis alone. After changing `POSTGRES_PASSWORD` read its note in
`.env.example` first — the database keeps the password it was created with.

Changing something that isn't a setting — a service's resources, extra volumes, another port mapping — don't edit
`docker-compose.yml` (your edit would clash with the next `git pull`). Put it in your own file and add it to the
command: `docker compose -p aksor-app -f docker-compose.yml -f docker-compose.custom.yml up -d`.

---

### Troubleshooting

| You see | Cause and fix |
|---|---|
| `network aksor-network declared as external, but could not be found` | Step by step, 0.1 wasn't run: `docker network create aksor-network` |
| `api` keeps restarting; its log says the database or password is wrong | Postgres isn't up (do step 2 first), or `.env`'s `POSTGRES_PASSWORD` differs from the one the database was created with. Fix: put the original password back, or change the database's: `docker compose -p aksor-db -f docker-compose.db.yml exec postgres psql -U aksor -c "ALTER USER aksor PASSWORD 'new'"` and use the same in `.env` |
| The portal loads but sign-in does nothing / "failed to fetch" | `CORS_ALLOWED_ORIGINS` doesn't match the address in your browser, or `PORTAL_API_BASE_URL` points at the wrong API. See "A server with a domain name" |
| You sign in, but a reload (or the next minutes) sends you back to the sign-in screen | The refresh cookie isn't reaching the API: the portal and the API are different *sites* (`localhost` vs `127.0.0.1`, or unrelated domains), or you're on plain `http` with `AUTH_COOKIE_SECURE=true`. See [authentication.md](authentication.md#troubleshooting) |
| `Unable to locate package …` / `Could not connect to deb.debian.org` / `npm ci` or `pip` times out during the build | The build can't download packages. First run the two checks under "Get Docker ready" above: if the server has internet but containers don't, fix Docker's network (UFW forwarding is the usual cause on Ubuntu) or set `BUILD_NETWORK=host`. If the server itself is cut off, best: **build the images on a machine that can** and ship them — `./deployment.sh publish <version>` there, then `AKSOR_IMAGE_PREFIX=… AKSOR_VERSION=… ./deployment.sh up` here (or `docker save` / `docker load` the three images by hand). If you have internal mirrors instead, set `APT_MIRROR` (host name), `PIP_INDEX_URL` and `NPM_REGISTRY` in `.env` and build again. A proxy: configure it in Docker (`~/.docker/config.json` `proxies`) |
| `Image aksor-khmer-bi-engine … pull access denied` just before the build starts | Harmless: Compose tries to pull the image first, finds none, and builds it. Only the lines after it matter |
| `port is already allocated` on 8000 or 8080 | Something else uses it. Stop it, or set `API_PORT` / `PORTAL_PORT` in `.env` (then update `CORS_ALLOWED_ORIGINS`, and `PORTAL_API_BASE_URL` in the portal config file if you moved the API) and run `./deployment.sh up` again |
| `error: PORTAL_PASSWORD in .env is too easy to guess` | `up` / `update` refuse a guessable administrator password. Put a long random one in `.env` (`openssl rand -hex 16`), or set `ALLOW_WEAK_PASSWORDS=1` on a throwaway machine |
| `backup` says it couldn't archive `data/` | The archive is made in a throwaway container using the `postgres:16-alpine` image (present once the stack is up). Start the stack first, or set `BACKUP_HELPER_IMAGE` to any image that has `tar` |
| Admin pages answer 503 | `PORTAL_PASSWORD` is empty in `.env`, and no user exists yet |
| "Found orphan containers" | A stack was started without its own `-p` name. Stop the extras, and always use the commands above |
| Uploaded JDBC driver: "isn't set up to run uploaded JDBC drivers" | Step 4 wasn't done (`JDBC_WORKER_TOKEN` and the `jdbc` profile). PostgreSQL/MySQL/MariaDB: choose "Built in" as the driver instead |
| A report fails with "source file could not be loaded" | The template was saved by a tool that writes a quirky Word file; current versions repair that automatically — rebuild the app (`up -d --build`) |

More detail on every setting is in the reference sections below and in `.env.example`.

---

## Reference

Everything in the reference describes what's actually in the repo and was verified
by building and running it, not a hypothetical setup — see the root
[`Dockerfile`](../Dockerfile), [`portal/Dockerfile`](../portal/Dockerfile),
and [`docker-compose.yml`](../docker-compose.yml).

### Docker (recommended)

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

#### Three compose files, one script

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
names across projects. A step-by-step walkthrough, one file at a time, is under [Option 2 — Step by step](#option-2--step-by-step).

[`deployment.sh`](../deployment.sh) runs all three in the right order:

```bash
./deployment.sh init      # once: creates the network and a .env with generated passwords
./deployment.sh up        # redis, then postgres (each waits until healthy), then the app
```

| Command | Does |
|---|---|
| `init` | Creates `aksor-network`, the `data/` folders, and a mode-600 `.env` with a random `POSTGRES_PASSWORD` and `PORTAL_PASSWORD` (shown once). Never overwrites an existing `.env`; if a Postgres volume already exists it does **not** invent a new database password. |
| `up [--build]` | Starts redis and postgres, waits for health, pulls the prebuilt images for `AKSOR_VERSION` and starts the app (`--build` builds them from the source instead). Warns about a default DB password, a missing `PORTAL_PASSWORD`, or unset `CORS_ALLOWED_ORIGINS`. |
| `update [--no-backup] [--build] [--pull]` | Backs up, pulls the images for `AKSOR_VERSION` (or `--build`s them), recreates the app (migrations run as the API starts). Redis and Postgres are not recreated. `--pull` (with `--build`) refreshes base images. |
| `down` | Stops the app, then postgres, then redis. Named volumes and `./data` are kept. |
| `restart [redis\|db\|app]`, `status`, `logs [service…]` | Operate and inspect. |
| `restore <dump> [<files>] [--yes] [--no-backup]` | Puts a backup back (see "Restore a backup"): safety backup, stop the app, replace the database and `data/` (the old `data/` is moved aside, not deleted). |
| `backup` | `pg_dump` plus `data/` (templates and every version, uploaded images/stylesheets, avatars, uploaded JDBC drivers, the secrets key — archived from inside a container so root-owned files are readable; a half-finished backup is removed, never left behind) into `./backups/`, newest 14 kept (`BACKUP_KEEP`). The secrets key and the database belong together — restore both or stored credentials can't be decrypted. |
| `redis …` / `db …` / `app …` | Pass any `docker compose` command to one stack, e.g. `./deployment.sh app up -d --scale worker=3`. |

By hand, without the script:

```bash
docker network create aksor-network
docker compose -p aksor-redis -f docker-compose.redis.yml up -d --wait
docker compose -p aksor-db    -f docker-compose.db.yml    up -d --wait
docker compose -p aksor-app   -f docker-compose.yml       up -d --wait      # AKSOR_VERSION in .env; add -f docker-compose.build.yml --build to build from source
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

#### Publishing images to Docker Hub

Three images are published: `<prefix>-engine` (the API; also runs `scheduler` and `worker`), `<prefix>-portal`
and `<prefix>-jdbc-worker` (only used with the `jdbc` profile). The prefix is
`aksorkhmerbi/aksor-khmer-bi`.

Images are published by hand with `./deployment.sh publish`, from a machine with internet, logged in with
`docker login` as an account that can push to `aksorkhmerbi`. Publish a commit CI has passed on:
```bash
./deployment.sh publish 1.0.2      # publishes ...-engine:1.0.2, ...-portal:1.0.2, ...-jdbc-worker:1.0.2
```
It uses `AKSOR_IMAGE_PREFIX` from `.env` (or the environment); add `--latest` to tag `latest` as well. The first
push creates each repository; keep them **Public** on Docker Hub so servers can pull without logging in.
The platform defaults to **`linux/amd64`** because most servers are Intel/AMD even when you build on an
Apple-silicon Mac — an arm64 image would die on them with `exec format error`. For both, set
`PLATFORMS=linux/amd64,linux/arm64` (the api image is large — LibreOffice — so the arm64 half builds slowly
under emulation).

**Deploy from the registry** on the server (it needs this repo's compose files and `.env`, not the source build).
Read `CHANGELOG.md` for every version up to the one you want first:
```bash
AKSOR_VERSION=1.0.2 ./deployment.sh up        # first time
AKSOR_VERSION=1.0.3 ./deployment.sh update    # upgrade: backup, pull, recreate, migrate
```
Put `AKSOR_IMAGE_PREFIX` and `AKSOR_VERSION` in `.env` to make them stick. A private repository needs
`docker login` on the server too.

Notes:
- **Pin a version** (`1.0.1`) in `.env` rather than relying on `latest`, so a restart can never silently pick up a
  new release, and a rollback is just setting the old tag and running `up`. Database migrations
  only move forward, so take the backup `update` makes before upgrading, and restore it to roll back across a
  schema change.
- **The portal's API URL is not in the image's control:** `portal/public/config.js` ships pointing at
  `http://localhost:8000`, so compose bind-mounts your own copy over it (`PORTAL_CONFIG_FILE`, default
  `./portal/public/config.js`). On a server with no checkout, copy that file there, edit
  `PORTAL_API_BASE_URL`, and point `PORTAL_CONFIG_FILE` at it.
- Never bake secrets into an image: passwords and keys come from `.env` at run time, and `.dockerignore` keeps
  `.env` out of the build context. Public images can be pulled by anyone.
- Images are not signed or scanned by this script; `docker scout cves <image>` or Trivy can do the
  latter.

#### Two origins now — CORS and the portal's API URL

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

#### Report metadata database

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

##### Migrations since the squash

`0002_report_shortcuts` adds the `report_shortcuts` table (a report listed in a second folder). A database already at
`0001_initial_schema` needs nothing but `alembic upgrade head`, which the Docker deployment runs as the API starts;
if you run the API yourself, run it from `api/` after pulling — until then the Reports page lists no shortcuts and
adding one fails.

##### Migrations were squashed

The schema's first migration is `0001_initial_schema` (the report version labels, uploaded JDBC
drivers and sign-in sessions that came after the first squash are folded into it too). A **new** database just runs
`alembic upgrade head`. A database that was created by one of the folded-in revisions can't be upgraded
by it — `alembic upgrade head` stops with *"Can't locate revision identified by '000N_…'"*. Check what yours holds
with `alembic current`, then:

| `alembic current` says | What to do |
|---|---|
| `0005_auth_sessions` | The schema is already complete as of `0001`. Re-label it, then bring it up to date: `alembic stamp --purge 0001_initial_schema` then `alembic upgrade head` |
| `0004_jdbc_drivers` or `0003_report_label_unique` | Create the one or two tables it lacks, then re-label: `python -c "from app import db; db.Base.metadata.create_all(db.engine)"` then `alembic stamp --purge head` (run both in `api/` with the same `DATABASE_URL` as the API — `create_all` builds every current table, so the label is the newest migration) |
| anything older | Recreate the database — `alembic upgrade head` on an empty one — or ask for help migrating its data |

(`create_all` only adds tables that are missing; it never touches existing ones. Back up first: `./deployment.sh backup`.)
Nothing in the files under `data/` is affected — only the database's own bookkeeping.

Running `api` without Docker (or without the `postgres` service) falls
back to a local SQLite file (`api/aksor_khmer_bi.db`) if `DATABASE_URL` is
unset — fine for a single-instance/local setup, not for multiple `api`
replicas writing concurrently.

#### AD/LDAP login

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

#### Job scheduling

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

#### What the image actually contains, and why it's large

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
build time (these exact files, not Debian's `fonts-khmeros`: that package's Siemreap
is the older version 1.00 with different glyphs and line metrics, and the same Khmer
paragraph breaks and justifies differently — measured, not assumed) — this step exists because LibreOffice needs fonts installed
system-wide to find them by name during conversion; WeasyPrint doesn't
need this since it loads font files directly via `@font-face`. If you
register your own template (via `/api/v1/reports`) that references a
font by name and that font isn't one of the two bundled ones, add it under
**Admin → Resources → Fonts** (no rebuild or restart — see
[create-a-template.md](create-a-template.md#65-fonts)); otherwise the docx→pdf/png
path substitutes a fallback font. (Fonts installed in a derived image still work too.)

#### Volumes — what's mounted and why

| Host path | Container path | Purpose |
|---|---|---|
| `./api/khmer_protected_terms.txt` | same, `:ro` | This deployment's Khmer protected-terms additions — see [`protected-terms-guide.md`](protected-terms-guide.md) |
| `./api/khmer_protected_terms.exclude.txt` | same, `:ro` | The inverse — suppress a shared built-in term |
| `./api/khmer_protected_terms.d` | same, `:ro` | Directory form of the first row — drop any number of `*.txt` exception files in here instead of editing one file |
| `./api/khmer_protected_terms.exclude.d` | same, `:ro` | Directory form of the second row |
| `./data/report_templates` | `/app/data/report_templates`, read-write | Templates registered via `/api/v1/reports` — deliberately outside `api/`'s own directory (runtime data, not code), same reasoning as `api`/`portal` being separate services. Without this mount, uploads are lost on `docker compose down` / container recreate, since they'd otherwise only live in the container's writable layer |
| `./data/image_resources`, `./data/stylesheet_resources`, `./data/avatars` | `/app/data/…`, read-write (`api`; the first two also `worker`) | The Resources library (images and stylesheets that html templates and docx image fields render from) and user avatars. These were **not mounted before** and were lost whenever the container was recreated — mounted now; back them up with the templates (`./deployment.sh backup` does) |
| `./data/font_resources` | `/app/data/font_resources`, read-write (`api`) and read-only (`worker`) | Fonts added under **Resources → Fonts** — server-wide, used from the next render with no restart. Back it up with the templates (`./deployment.sh backup` does). |
| `pgdata` (named volume, not a bind mount) | `/var/lib/postgresql/data` on the `postgres` service | Report metadata (see above) — a named volume rather than a host path since there's no reason to browse/edit Postgres's on-disk files directly the way you would a `.txt` exception list |

The first two are read-only bind mounts specifically so editing either
file on the host takes effect on container **restart**, without an
image rebuild — they're baked into the image too (so a fresh deploy has
sane defaults), the mount just lets you override them live.

#### Environment variables reference

| Variable | Required? | Purpose |
|---|---|---|
| `PORTAL_USERNAME` / `PORTAL_PASSWORD` | For the admin surface | The break-glass superuser: signs in through `POST /api/v1/auth/login` like anyone, and is how the first real accounts get created. With neither this nor any user, every protected route returns `503`, not open access. Set on the `api` service. |
| `API_PORT` / `PORTAL_PORT` | No (defaults 8000 / 8080) | The host ports the `api` and `portal` services are published on. After changing them, keep `CORS_ALLOWED_ORIGINS` (portal port) and the portal config file's `PORTAL_API_BASE_URL` (API port) in step. |
| `BUILD_NETWORK` / `APT_MIRROR` / `PIP_INDEX_URL` / `NPM_REGISTRY` | No (defaults: `default`, the public Debian / PyPI / npm) | Where the image **build** downloads packages from. `BUILD_NETWORK=host` builds on the server's own network (a fix when Docker's bridge can't reach the internet, e.g. UFW forwarding on Ubuntu); the three mirror settings point it at internal mirrors. Only used by `up --build`. See [Get Docker ready](#a-get-docker-ready-ubuntu-debian-centos--rhel--rocky--alma-and-others). |
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
| `CLIENT_RUN_LIMIT_PER_MINUTE` | No | Most `embed-run` calls per minute one **API client** (client id + secret, Admin → API Clients) may make; over it, `429`. Default 120. Clients themselves are created in the portal -- no environment variable per report. See [Running a report as an API client](building-a-report.md#running-a-report-as-an-api-client-client-id--secret). |
| `REPORT_TIMEZONE` | No | IANA time zone (e.g. `Asia/Phnom_Penh`; default `UTC`) that a parameter's `now()` default is read in when a run leaves that parameter out -- an API call or an embed. The portal's own run form fills `now()` from the viewer's browser clock instead. An unknown name is logged and falls back to UTC. See [Filters and a data source](building-a-report.md#filters-a-data-source-and-connections). Set on `api` |
| `AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE` / `AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE` | No | Extra Khmer terms this deployment has observed ICU mis-splitting, on top of the shared package's built-ins — see [`protected-terms-guide.md`](protected-terms-guide.md) |
| `AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR` / `AKSOR_KHMER_OCR_EXCLUDED_TERMS_DIR` | No | Directory form of the row above — every `*.txt` file inside is merged in |
| `DATABASE_URL` | No | Report metadata database connection string — `docker-compose.yml` sets this to the `postgres` service automatically; unset falls back to a local SQLite file (`api/aksor_khmer_bi.db`). See `api/app/db.py` |
| `POSTGRES_PASSWORD` | For the `postgres` service | Password for both the `postgres` service and `api`'s `DATABASE_URL` — change it in one place, `docker-compose.yml` threads it to both |
| `REDIS_URL` | No | Celery broker/result-backend connection string for `api` (enqueue only), `scheduler`, and `worker` — unset falls back to `redis://localhost:6379/0`. See `api/app/celery_app.py` |
| `SCHEDULER_RECONCILE_INTERVAL_SECONDS` | No | How often `scheduler` polls the `jobs` table for create/edit/pause/delete (default 15) — see `api/app/scheduler.py` |
| `REDIS_PASSWORD` | No (recommended; `init` generates one) | Makes Redis (the job queue) require a password, so only the app can use it; the app builds its `REDIS_URL` from it. Letters and digits only. Empty = Redis open to every container on `aksor-network`. Ignored when `REDIS_URL` is set. Read by the `redis` stack and by `api`, `scheduler` and `worker`. |
| `ALLOW_WEAK_PASSWORDS` | No | Shell variable for `deployment.sh`, not a `.env` setting: `ALLOW_WEAK_PASSWORDS=1 ./deployment.sh up` lets a guessable `PORTAL_PASSWORD` through on a throwaway machine. |
| `BACKUP_HELPER_IMAGE` | No (default `postgres:16-alpine`) | Shell variable for `deployment.sh backup` / `restore`: the image of the throwaway container that archives `data/` as root. Any image with `tar` works. |
| `FONT_MAX_MB` | No (default `20`) | The largest font file Resources → Fonts accepts. Set on the `api` service. |
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

### Database connections and JDBC drivers

A report can run a read-only SQL query against Oracle, PostgreSQL, MySQL, SQL Server, MariaDB or Db2
(Admin → Connections → *+ Database*; see docs/building-a-report.md). **PostgreSQL, MySQL and MariaDB need
nothing here** — their drivers ship in the `api` image. The other engines need the vendor's JDBC driver
uploaded in the portal (Admin → JDBC Drivers), and a driver is code the server runs, so it runs in a
separate, locked-down container instead of in `api`:

```bash
# in .env: JDBC_WORKER_TOKEN=<a long random string>
docker compose --profile jdbc up -d jdbc-worker api     # pulls the prebuilt jdbc-worker image (AKSOR_VERSION in .env)
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

### TLS — not included, add a reverse proxy

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

### Without Docker

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
