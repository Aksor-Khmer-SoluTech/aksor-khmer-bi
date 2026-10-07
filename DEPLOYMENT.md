# Deploying Aksor Khmer BI

> **Start with [Before you start](#before-you-start-required-for-both-options)** (Docker + the code), then choose [Quick deployment](#option-1--quick-deployment-deploymentsh) or [Step by step](#option-2--step-by-step).

---

## Before you start (required for both options)

**Do these two things first, whichever way you deploy.**

### A. Get Docker ready (Ubuntu, Debian, CentOS / RHEL / Rocky / Alma, and others)

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

### B. Get the code (once)

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

## Choose how to deploy

With Docker and the code ready, pick an option — each jumps straight to its instructions:

| | [**Quick deployment**](#option-1--quick-deployment-deploymentsh) | [**Step by step**](#option-2--step-by-step) |
|---|---|---|
| How | One script, `deployment.sh`, does everything and generates the passwords | You start one compose file at a time and check it before moving on |
| Best for | A **first** install on a fresh server (it creates the network, the data folders and `.env`) | An **existing** deployment you update by hand, or when you want to see what runs and change a step |
| Jump to | [Option 1 — Quick deployment](#option-1--quick-deployment-deploymentsh) | [Option 2 — Step by step](#option-2--step-by-step) |

## How the stack is put together

Each step starts **one** compose file, then checks it before you move on, so if something is wrong you know exactly
which step it was.

| Step | Compose file | Compose project | Starts |
|---|---|---|---|
| 1 | `docker-compose.redis.yml` | `aksor-redis` | `redis` — job queue |
| 2 | `docker-compose.db.yml` | `aksor-db` | `postgres` — the database |
| 3 | `docker-compose.yml` | `aksor-app` | `api`, `scheduler`, `worker`, `portal` |
| 4 *(optional)* | `docker-compose.yml` `--profile jdbc` | `aksor-app` | `jdbc-worker` — only for Oracle / SQL Server / Db2 drivers |

They share one Docker network, `aksor-network`, which is how the app finds `postgres` and `redis` by name.
Each file has its **own project name** (`-p …`) — keep them, or stopping one stack could remove another's
containers.

Tested while writing this: steps 1 and 2 were run for real, and the step 3 images were built on macOS (Docker Desktop).
The full start of step 3, `deployment.sh up` / `update` on a Linux server, and step 4 (the JDBC worker) were not run end
to end — if one of them fails on your server, the Troubleshooting table at the end is the place to start.

---

## Option 1 — Quick deployment: `deployment.sh`

> **Best for a first deployment.** `./deployment.sh init` is the first-time setup: it creates the `aksor-network`
> network and the `data/` folders if they are missing, and writes a new `.env` **only when there isn't one**. It
> never overwrites an existing `.env`, and `update` / `up` never edit it either. But the script decides things for you,
> so **if this server is already running, or you manage `.env` and the compose commands by hand, use
> [Step by step](#option-2--step-by-step) instead.** On an existing install:
>
> - **Don't run `init` again.** It is for the first deployment only.
> - **Read the [CHANGELOG](CHANGELOG.md) before you update** — every entry between the version you run now and the one
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
[CHANGELOG.md](CHANGELOG.md) first). Then:

```bash
./deployment.sh doctor     # optional: checks Docker, ports and disk, in seconds
./deployment.sh up         # starts redis, then postgres, then pulls and starts the app images
```

No build happens, so no Node/npm is needed. To build from the source instead (a fork, or a version that isn't
published), run `./deployment.sh up --build` — the first build takes several minutes and needs internet for
Debian, Python and npm packages.

`up` runs `doctor` itself first, so a missing piece (a closed firewall, a busy port) is reported in
seconds with the fix. When it finishes it prints the portal and API-docs addresses. Open the
portal and sign in with the `admin` password from `init`.

Everything you do afterwards:

| I want to… | Command |
|---|---|
| see what is running | `./deployment.sh status` |
| read the logs | `./deployment.sh logs` (the API; add names for others: `logs api worker scheduler portal`) |
| update to the new version | read the [CHANGELOG](CHANGELOG.md) for every version up to the one you want **first**; set `AKSOR_VERSION` in `.env`, `git pull`, then `./deployment.sh update` — takes a **backup first**, pulls that version's images, restarts the app (database migrations run as the API starts); Postgres and Redis are not touched. Flags: `--no-backup`, `--build` (build from source instead), `--pull` (with `--build`: refresh the base images) |
| back up now | `./deployment.sh backup` — the database plus templates, images, avatars and the encryption key, into `./backups/` (the newest 14 are kept; `BACKUP_KEEP=30` changes that) |
| apply a change in `.env` | `./deployment.sh up` (recreates only what changed) |
| restart | `./deployment.sh restart` (everything), or `restart app` / `restart db` / `restart redis` |
| stop everything | `./deployment.sh down` — your data is kept |
| operate one stack alone | `./deployment.sh app status`, `./deployment.sh db logs`, `./deployment.sh redis restart`, … |
| use uploaded JDBC drivers (Oracle, SQL Server…) | set `JDBC_WORKER_TOKEN` in `.env` ([Step 4](#step-4-optional--jdbc-driver-service)), then `./deployment.sh app --profile jdbc up -d --build jdbc-worker api` |
| deploy prebuilt images (no build, no Node/npm on the server) | in `.env` set `AKSOR_IMAGE_PREFIX=ghcr.io/aksor-khmer-solutech/aksor-khmer-bi` and `AKSOR_VERSION=<released version>`, then `./deployment.sh up` (first time) or `update` (upgrade) — this is the default. Releases are published by pushing a `v*` git tag. |
| see every command | `./deployment.sh help` |

A command that fails stops with a one-line `error:` that says what to fix. `./deployment.sh init` never overwrites an
existing `.env`, so it is safe to run twice.

---

## Option 2 — Step by step

Docker and the code come first — see [Before you start](#before-you-start-required-for-both-options). Run every command from the repository folder.

### 0.1 Create the shared network

```bash
docker network create aksor-network
```

If it already exists Docker says so — that's fine.

### 0.2 Create your settings file

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

Make passwords with `openssl rand -hex 16`. `CORS_ALLOWED_ORIGINS` is **exactly what you type in the
browser** to open the portal — `http://localhost:8080` on your own machine, or
`https://reports.example.com` on a server. If it's wrong, the login silently fails.

**Ports.** The API is published on 8000 and the portal on 8080. If those are taken, add `API_PORT=…` and/or
`PORTAL_PORT=…` to `.env`. Then keep three things in step: `CORS_ALLOWED_ORIGINS` uses the portal's new port, and —
if you moved the API — `PORTAL_API_BASE_URL` in the portal config file (`portal/public/config.js`, or the file
`PORTAL_CONFIG_FILE` points to) uses the API's new port.

People sign in with a short-lived access token and a refresh cookie (see
[docs/authentication.md](docs/authentication.md)). Nothing to configure for that: the signing key is created for you in
`data/secrets/jwt.key` (it is covered by the `data/secrets` backup below). Two things must be true, or sign-in will
look like it works and then drop you on every reload: the portal and the API are on the **same site**
(`localhost` and `localhost` yes; `localhost` and `127.0.0.1` no), and `CORS_ALLOWED_ORIGINS` is the portal's exact
origin.

> `POSTGRES_PASSWORD` is applied when the database is **first created**. Changing it later in `.env` does not
> change an existing database's password (see Troubleshooting).

### 0.3 Create the data folders

The app stores templates, credentials' encryption key, images and logs on disk. Create the folders yourself so
they belong to you, not to root:

```bash
mkdir -p data/report_templates data/secrets data/image_resources data/stylesheet_resources data/avatars data/logs data/jdbc_drivers
```

**Back up `data/secrets/` together with the database** — without its key, saved credentials and users' 2FA secrets can't be decrypted. (It also holds the sign-in signing key; losing that only signs everyone out.)

---

## Step 1 — Redis

```bash
docker compose -p aksor-redis -f docker-compose.redis.yml up -d --wait
```

`--wait` returns when the container reports healthy. Expected: `Container aksor-redis-redis-1  Healthy`.

Check it:

```bash
docker compose -p aksor-redis -f docker-compose.redis.yml ps
docker run --rm --network aksor-network redis:7-alpine redis-cli -h redis ping      # PONG
```

## Step 2 — Postgres

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

## Step 3 — The application

Set `AKSOR_VERSION` in `.env` to the released version you want (read [CHANGELOG.md](CHANGELOG.md) first), then
pull the prebuilt images and start:

```bash
docker compose -p aksor-app -f docker-compose.yml pull
docker compose -p aksor-app -f docker-compose.yml up -d --wait
```

No build, so no Node/npm is needed. To build from the source instead (several minutes — it installs LibreOffice,
Tesseract and fonts; later builds reuse the cache), skip `pull` and run
`docker compose -p aksor-app -f docker-compose.yml up -d --build --wait`. What happens:

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

## Step 4 (optional) — JDBC driver service

Only needed if you upload vendor JDBC drivers (Oracle, SQL Server, Db2). PostgreSQL, MySQL and MariaDB
connections work without it.

1. Add to `.env` a long random token: `JDBC_WORKER_TOKEN=<openssl rand -hex 32>`
2. Start the worker (same project as the app) and recreate `api` so it picks the token up:

```bash
docker compose -p aksor-app -f docker-compose.yml --profile jdbc up -d --build jdbc-worker api
docker compose -p aksor-app -f docker-compose.yml --profile jdbc ps jdbc-worker       # running / healthy
```

Then upload a driver under **Admin → JDBC Drivers**.

---

## Running it every day

| I want to… | Command |
|---|---|
| see what's running | `docker compose -p aksor-app -f docker-compose.yml ps` (and `-p aksor-db`, `-p aksor-redis` with their files) |
| read the API log | `docker compose -p aksor-app -f docker-compose.yml logs -f api` |
| deploy new code | `git pull` then `docker compose -p aksor-app -f docker-compose.yml up -d --build --wait` — only the app restarts; migrations run as `api` starts; the database and Redis are untouched |
| restart one service | `docker compose -p aksor-app -f docker-compose.yml restart api` |
| apply a `.env` change | `docker compose -p aksor-app -f docker-compose.yml up -d` (recreates what changed) |

### Stop and start again

Stop in the **reverse** order, start in the **same** order as above:

```bash
docker compose -p aksor-app   -f docker-compose.yml       down
docker compose -p aksor-db    -f docker-compose.db.yml    down
docker compose -p aksor-redis -f docker-compose.redis.yml down
```

Your data is kept (named volumes and the `data/` folder). **Never add `-v`** to those commands unless you mean to
delete the database / queue.

### Back up

```bash
mkdir -p backups
docker compose -p aksor-db -f docker-compose.db.yml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip > backups/aksor-$(date +%Y%m%d-%H%M).sql.gz
tar -czf backups/aksor-files-$(date +%Y%m%d-%H%M).tar.gz data/report_templates data/secrets data/image_resources data/stylesheet_resources data/avatars data/jdbc_drivers
```

Keep the two files together — the encryption key in `data/secrets` and the database belong to each other.

---

## Variations

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

## Customizing

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
| build on a server with a restricted network | `BUILD_NETWORK`, `APT_MIRROR`, `PIP_INDEX_URL`, `NPM_REGISTRY` | `… up -d --build` (these only matter when building) |
| which prebuilt images to deploy (build from source with `--build`) | `AKSOR_IMAGE_PREFIX`, `AKSOR_VERSION` | `./deployment.sh up` |

`… up -d` is short for `docker compose -p aksor-app -f docker-compose.yml up -d`: it recreates only the services
whose settings changed, and leaves the database and Redis alone. After changing `POSTGRES_PASSWORD` read its note in
`.env.example` first — the database keeps the password it was created with.

Changing something that isn't a setting — a service's resources, extra volumes, another port mapping — don't edit
`docker-compose.yml` (your edit would clash with the next `git pull`). Put it in your own file and add it to the
command: `docker compose -p aksor-app -f docker-compose.yml -f docker-compose.custom.yml up -d`.

---

## Troubleshooting

| You see | Cause and fix |
|---|---|
| `network aksor-network declared as external, but could not be found` | Step by step, 0.1 wasn't run: `docker network create aksor-network` |
| `api` keeps restarting; its log says the database or password is wrong | Postgres isn't up (do step 2 first), or `.env`'s `POSTGRES_PASSWORD` differs from the one the database was created with. Fix: put the original password back, or change the database's: `docker compose -p aksor-db -f docker-compose.db.yml exec postgres psql -U aksor -c "ALTER USER aksor PASSWORD 'new'"` and use the same in `.env` |
| The portal loads but sign-in does nothing / "failed to fetch" | `CORS_ALLOWED_ORIGINS` doesn't match the address in your browser, or `PORTAL_API_BASE_URL` points at the wrong API. See "A server with a domain name" |
| You sign in, but a reload (or the next minutes) sends you back to the sign-in screen | The refresh cookie isn't reaching the API: the portal and the API are different *sites* (`localhost` vs `127.0.0.1`, or unrelated domains), or you're on plain `http` with `AUTH_COOKIE_SECURE=true`. See [docs/authentication.md](docs/authentication.md#troubleshooting) |
| `Unable to locate package …` / `Could not connect to deb.debian.org` / `npm ci` or `pip` times out during the build | The build can't download packages. First run the two checks under "Get Docker ready first" above: if the server has internet but containers don't, fix Docker's network (UFW forwarding is the usual cause on Ubuntu) or set `BUILD_NETWORK=host`. If the server itself is cut off, best: **build the images on a machine that can** and ship them — `./deployment.sh publish <version>` there, then `AKSOR_IMAGE_PREFIX=… AKSOR_VERSION=… ./deployment.sh up` here (or `docker save` / `docker load` the three images by hand). If you have internal mirrors instead, set `APT_MIRROR` (host name), `PIP_INDEX_URL` and `NPM_REGISTRY` in `.env` and build again. A proxy: configure it in Docker (`~/.docker/config.json` `proxies`) |
| `Image aksor-khmer-bi-engine … pull access denied` just before the build starts | Harmless: Compose tries to pull the image first, finds none, and builds it. Only the lines after it matter |
| `port is already allocated` on 8000 or 8080 | Something else uses it. Stop it, or set `API_PORT` / `PORTAL_PORT` in `.env` (then update `CORS_ALLOWED_ORIGINS`, and `PORTAL_API_BASE_URL` in the portal config file if you moved the API) and run `./deployment.sh up` again |
| Admin pages answer 503 | `PORTAL_PASSWORD` is empty in `.env`, and no user exists yet |
| "Found orphan containers" | A stack was started without its own `-p` name. Stop the extras, and always use the commands above |
| Uploaded JDBC driver: "isn't set up to run uploaded JDBC drivers" | Step 4 wasn't done (`JDBC_WORKER_TOKEN` and the `jdbc` profile). PostgreSQL/MySQL/MariaDB: choose "Built in" as the driver instead |
| A report fails with "source file could not be loaded" | The template was saved by a tool that writes a quirky Word file; current versions repair that automatically — rebuild the app (`up -d --build`) |

More detail on every setting is in [docs/deployment.md](docs/deployment.md) and `.env.example`.
