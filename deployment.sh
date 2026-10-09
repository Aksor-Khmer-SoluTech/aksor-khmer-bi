#!/usr/bin/env bash
# Deploy and operate Aksor Khmer BI with Docker Compose.
#
# Three stacks, deliberately separate (see docs/deployment.md, "Install it", for the same steps by hand):
#   redis  docker-compose.redis.yml  redis                 project "aksor-redis"
#   db     docker-compose.db.yml     postgres              project "aksor-db"
#   app    docker-compose.yml        api, scheduler,       project "aksor-app"
#                                    worker, portal
# joined by one external network, "aksor-network". The app can be rebuilt, updated or
# rolled back without ever restarting the database or the queue.
#
#   ./deployment.sh init              first-time setup: network + .env (from .env.example) with generated secrets
#   ./deployment.sh up                start redis, then postgres (each waits until healthy), then the app. The app
#                                     runs the released images named in docker-compose.yml, PULLED from Docker Hub;
#                                     nothing is built here
#   ./deployment.sh update [--no-backup]
#                                     after `git pull`: back up, pull the images docker-compose.yml now names, recreate
#                                     the app (migrations run at api start); redis and postgres are left alone
#   ./deployment.sh doctor            check this machine (docker, compose, CPU, ports, disk); `up` runs it for you
#   ./deployment.sh down              stop the app, then postgres, then redis (volumes and data are kept)
#   ./deployment.sh restart [redis|db|app]
#   ./deployment.sh status
#   ./deployment.sh logs [service...] follow logs (default: api)
#   ./deployment.sh backup            pg_dump + templates, resources, avatars, JDBC drivers, secrets key -> ./backups/
#   ./deployment.sh restore <aksor-...sql.gz> [<aksor-...-files.tar.gz>] [--yes] [--no-backup]
#                                     put a backup back: stops the app, REPLACES the database and data/ with the backup
#                                     (the current data/ is moved aside, not deleted), then you run `up`
#   ./deployment.sh redis|db|app <up|down|status|logs ...>   operate one stack alone
#
# Settings come from ./.env (never committed): POSTGRES_PASSWORD, PORTAL_USERNAME,
# PORTAL_PASSWORD, CORS_ALLOWED_ORIGINS, ... -- see docs/deployment.md.

# `. deployment.sh up` runs this inside your own shell: its `set -e` and every `exit` would then close that shell on
# the first error. Refuse, loudly, before touching anything (tests source it on purpose with DEPLOYMENT_SH_NO_MAIN).
if [ -z "${DEPLOYMENT_SH_NO_MAIN:-}" ]; then
  _sourced=0
  if [ -n "${BASH_VERSION:-}" ] && [ "${BASH_SOURCE[0]}" != "$0" ]; then _sourced=1; fi
  case "${ZSH_EVAL_CONTEXT:-}" in *:file*) _sourced=1 ;; esac
  if [ "$_sourced" = 1 ]; then
    unset _sourced
    printf 'error: run it as  ./deployment.sh %s  -- not  . deployment.sh  (that runs it inside your shell, and an error would close it)\n' "$*" >&2
    return 1
  fi
  unset _sourced
fi

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

NETWORK="aksor-network"
REDIS_PROJECT="aksor-redis"
DB_PROJECT="aksor-db"
APP_PROJECT="aksor-app"
REDIS_FILE="docker-compose.redis.yml"
DB_FILE="docker-compose.db.yml"
APP_FILE="docker-compose.yml"
BACKUP_DIR="${BACKUP_DIR:-backups}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
# The data/ folder is written by the containers (as root), so a normal host user may not be able to read parts of
# it (the secrets key is mode 600). Backups archive it from inside a throwaway container instead; it needs only
# tar, gzip and chown, so the Postgres image -- already on this machine once the stack is up -- will do.
BACKUP_HELPER_IMAGE="${BACKUP_HELPER_IMAGE:-postgres:16-alpine}"
# Everything the api writes outside the database (all bind-mounted in docker-compose.yml).
DATA_DIRS=(data/report_templates data/secrets data/image_resources data/stylesheet_resources data/avatars data/jdbc_drivers data/font_resources)
# The database files (docker-compose.db.yml). Not in DATA_DIRS: a backup takes a pg_dump instead of copying them.
PG_DIR="data/postgres"
# Where the database lived before it moved to PG_DIR; moved across once by move_old_pg_volume.
OLD_PG_VOLUME="aksor-khmer-bi_pgdata"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_off=$'\033[0m'
[ -t 1 ] || { c_red=; c_grn=; c_ylw=; c_off=; }
info() { printf '%s==>%s %s\n' "$c_grn" "$c_off" "$*"; }
warn() { printf '%swarning:%s %s\n' "$c_ylw" "$c_off" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$c_red" "$c_off" "$*" >&2; exit 1; }

redis() { docker compose -p "$REDIS_PROJECT" -f "$REDIS_FILE" "$@"; }
db()    { docker compose -p "$DB_PROJECT"    -f "$DB_FILE"    "$@"; }
# The app stack runs the released, version-pinned images docker-compose.yml names; building them is not part of
# installing.
app()   { docker compose -p "$APP_PROJECT"   -f "$APP_FILE"   "$@"; }

# Building the images from source is not a supported way to install (the maintainers publish released images), so
# say so plainly instead of a bare usage line when an old instruction still passes --build / --pull.
no_build() { die "building from source isn't supported -- run a released version: git pull (it brings the image versions in docker-compose.yml), then ./deployment.sh ${1:-up}"; }

# Redis first, then Postgres, each waiting until healthy (the app needs both).
start_infra() {
  info "starting redis"
  redis up -d --wait
  move_old_pg_volume
  info "starting postgres"
  db up -d --wait
  check_db_password
}

# Older installs kept the database in the Docker volume $OLD_PG_VOLUME; it now lives in ./$PG_DIR. Move it across
# once -- with Postgres stopped, keeping ownership and permissions -- before Postgres starts on the folder (which would
# otherwise create a new, empty database). Copied to a temporary folder and renamed only when complete, so an
# interrupted copy can never pass for a finished one. The volume itself is left untouched as a fallback.
move_old_pg_volume() {
  docker volume inspect "$OLD_PG_VOLUME" >/dev/null 2>&1 || return 0
  # Postgres makes ./$PG_DIR private to itself, so the host user often can't look inside it: every check on its
  # contents runs in a helper container. 0 = the folder already holds a database, 3 = it holds something else, 10 = empty.
  local state=0
  docker run --rm -v "$PWD/data:/data:z" "$BACKUP_HELPER_IMAGE" sh -c \
    '[ -f /data/postgres/PG_VERSION ] && exit 0; [ -d /data/postgres ] && [ -n "$(ls -A /data/postgres)" ] && exit 3; exit 10' \
    || state=$?
  case "$state" in
    0) return 0 ;;
    3) die "./$PG_DIR has files but no database, and the old database is still in the Docker volume $OLD_PG_VOLUME -- move ./$PG_DIR aside, then run this again to bring the database across" ;;
    10) ;;
    *) die "couldn't check ./$PG_DIR (helper container failed: $state)" ;;
  esac
  info "moving the database from the Docker volume $OLD_PG_VOLUME into ./$PG_DIR (once; the volume is kept as a fallback)"
  db stop postgres >/dev/null 2>&1 || true
  docker run --rm -v "$OLD_PG_VOLUME:/from:ro" -v "$PWD/data:/data:z" "$BACKUP_HELPER_IMAGE" \
    sh -c 'set -e; rm -rf /data/postgres.moving; mkdir /data/postgres.moving; cp -a /from/. /data/postgres.moving/; rmdir /data/postgres 2>/dev/null || true; mv /data/postgres.moving /data/postgres' \
    || die "couldn't copy the database out of $OLD_PG_VOLUME -- the volume is unchanged; check disk space and run again"
  info "database moved. When everything works, the old copy can go: docker volume rm $OLD_PG_VOLUME"
}

# A Postgres volume keeps the password it was created with, whatever .env says later -- and a mismatch otherwise shows
# up as the api crash-looping at its migrations behind pages of traceback. Log in the way the api does (over the
# network, as `postgres`, where the password is really checked -- connections from inside the container itself are
# trusted) and stop here with the fix instead. Skipped for your own database (DATABASE_URL).
check_db_password() {
  [ -z "$(env_value DATABASE_URL)" ] || return 0
  local pw; pw="$(env_value POSTGRES_PASSWORD)"; [ -n "$pw" ] || pw=aksor
  docker run --rm --pull=never --network "$NETWORK" -e PGPASSWORD="$pw" postgres:16-alpine \
      psql -h postgres -U aksor -d aksor_khmer_bi -tAc 'select 1' >/dev/null 2>&1 && return 0
  die "Postgres refuses POSTGRES_PASSWORD from .env: this database was created with a different password, and it keeps that one.
       Either put the original password back in .env, or give the database the one in .env:
         docker compose -p $DB_PROJECT -f $DB_FILE exec -T postgres psql -U aksor -d aksor_khmer_bi -c \"ALTER USER aksor PASSWORD '<the password in .env>'\"
       (on a throwaway machine you can instead delete the database: ./deployment.sh down, then sudo rm -rf $PG_DIR -- that erases every report and user)"
}

require_docker() {
  command -v docker >/dev/null || die "docker is not installed"
  docker compose version >/dev/null 2>&1 || die "the Docker Compose v2 plugin is required (docker compose ...)"
  docker info >/dev/null 2>&1 || die "can't reach the Docker daemon -- is it running?"
}

ensure_network() {
  docker network inspect "$NETWORK" >/dev/null 2>&1 || { info "creating network $NETWORK"; docker network create "$NETWORK" >/dev/null; }
}

env_value() { # env_value KEY -> value from .env, read the way Compose reads it (empty if absent)
  [ -f .env ] || return 0
  # Last assignment wins. Drops a Windows line ending, an inline " # comment" and one pair of surrounding quotes,
  # so `API_PORT="8000"  # default` is 8000 here exactly as it is for `docker compose`.
  sed -n "s/^$1=//p" .env | tail -n1 | tr -d '\r' | sed -e 's/[[:space:]]\{1,\}#.*$//' -e 's/[[:space:]]*$//' \
    -e "s/^\"\(.*\)\"\$/\1/" -e "s/^'\(.*\)'\$/\1/"
}

set_env() { # set_env KEY VALUE -- fill KEY= in .env, or add it when the file has no such line (portable: no sed -i)
  if grep -q "^$1=" .env; then
    awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' .env > .env.tmp && mv .env.tmp .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

random_secret() { # URL/shell-safe, 32 chars
  # `|| true`: head closing the pipe SIGPIPEs tr, which pipefail would turn into a fatal error.
  LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 || true
}

# A password anyone would try first. Compared lower-case, so Admin / ADMIN / Pleasechangeit are caught too.
is_guessable() { # is_guessable VALUE -> 0 when it is empty-ish, too short or on the short list
  local v; v="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  [ "${#v}" -lt 8 ] && return 0
  case "$v" in
    password|password1|password123|pleasechangeit|changeme|changeit|change-me|letmein|administrator|admin1234|12345678|123456789|qwertyui|aksor|aksorkhmer) return 0 ;;
  esac
  return 1
}

preflight() {
  [ -f .env ] || die ".env not found -- run ./deployment.sh init first"
  local portal_pw; portal_pw="$(env_value PORTAL_PASSWORD)"
  if [ -z "$portal_pw" ]; then
    warn "PORTAL_PASSWORD is unset: admin routes answer 503 until a break-glass login is configured"
  elif is_guessable "$portal_pw" && [ -z "${ALLOW_WEAK_PASSWORDS:-}" ]; then
    # It is the full administrator login for the whole deployment: never start the stack with one anyone would guess.
    die "PORTAL_PASSWORD in .env is too easy to guess (under 8 characters, or a common one like 'admin'). Set a long random one (openssl rand -hex 16), or ALLOW_WEAK_PASSWORDS=1 on a throwaway machine"
  fi
  # Postgres isn't published on a host port, and an existing database keeps the password it was created with,
  # so this one warns instead of refusing.
  # Passwords may contain any character: the app escapes them when it builds the database and Redis addresses
  # (api/app/service_urls.py). The one trap is .env itself, where Compose reads `$` as the start of a variable unless
  # the value is in single quotes -- `p$ss` would silently become `p`.
  local key line
  for key in POSTGRES_PASSWORD REDIS_PASSWORD PORTAL_PASSWORD; do
    line="$(sed -n "s/^$key=//p" .env 2>/dev/null | tail -n1 | tr -d '\r')"
    case "$line" in
      "'"*) ;;
      *'$'*) die "$key in .env contains \$ -- wrap the value in single quotes so it is read literally, e.g. $key='your\$password'" ;;
    esac
  done
  if is_guessable "$(env_value POSTGRES_PASSWORD)"; then
    warn "POSTGRES_PASSWORD is empty or guessable (the compose default is 'aksor') -- fine for a throwaway machine, not for a server anyone else can reach"
  fi
  # The portal's config file is bind-mounted; if the path is wrong Docker invents a *directory* there and the portal
  # then serves nothing useful. And a config still pointing at localhost only works in a browser on this machine.
  local cfg; cfg="$(env_value PORTAL_CONFIG_FILE)"; cfg="${cfg:-./portal/public/config.js}"
  [ -f "$cfg" ] || die "PORTAL_CONFIG_FILE ($cfg) is not a file -- fix the path in .env (Docker would create a directory there)"
  case "$(env_value CORS_ALLOWED_ORIGINS)" in
    ""|*localhost*|*127.0.0.1*) ;;
    *) grep -q 'PORTAL_API_BASE_URL *= *"https\?://\(localhost\|127\.0\.0\.1\)' "$cfg" \
         && warn "CORS_ALLOWED_ORIGINS is a public address but $cfg still points the portal at http://localhost: -- other people's browsers would talk to themselves. Set PORTAL_API_BASE_URL there (see docs/deployment.md, \"A server with a domain name\")" ;;
  esac
  if [ -z "$(env_value CORS_ALLOWED_ORIGINS)" ]; then
    warn "CORS_ALLOWED_ORIGINS is unset (defaults to http://localhost:8080) -- set it to the portal's public URL"
  fi
}

# Checks the machine before anything starts, so a problem shows up in seconds with a fix.
# Prints ok / warn / FAIL for each check; exits non-zero only on FAIL. SKIP_DOCTOR=1 skips it inside `up`.
cmd_doctor() {
  local fails=0
  ok()   { printf '  %sok%s    %s\n' "$c_grn" "$c_off" "$*"; }
  bad()  { printf '  %sFAIL%s  %s\n' "$c_red" "$c_off" "$*"; fails=$((fails + 1)); }
  note() { printf '  %swarn%s  %s\n' "$c_ylw" "$c_off" "$*"; }
  info "checking this machine (details: docs/deployment.md, \"Before you start\")"

  command -v docker >/dev/null && ok "docker: $(docker --version 2>/dev/null | head -n1)" || { bad "docker is not installed -- see docs/deployment.md, \"Get Docker ready\""; return 1; }
  if docker compose version >/dev/null 2>&1; then ok "compose: $(docker compose version --short 2>/dev/null)"; else bad "the Docker Compose v2 plugin is missing (the old \`docker-compose\` command is not enough)"; fi
  docker info >/dev/null 2>&1 && ok "the Docker daemon answers" || { bad "can't reach the Docker daemon -- is it running, and are you in the docker group (or using sudo)?"; return 1; }

  local arch; arch="$(docker info --format '{{.Architecture}}' 2>/dev/null)"
  ok "CPU: ${arch:-unknown}"
  case "$arch" in
    x86_64|amd64|aarch64|arm64) ;;
    *) note "released images are built for Intel/AMD (linux/amd64) and ARM (linux/arm64); on $arch pulling will fail with 'no matching manifest'" ;;
  esac

  local free_kb; free_kb="$(df -Pk . 2>/dev/null | awk 'NR==2 {print $4}')"
  if [ -n "$free_kb" ] && [ "$free_kb" -lt 10485760 ]; then note "only $((free_kb / 1048576)) GB free here; the images take a few GB (LibreOffice, Tesseract, fonts), plus room for data and backups"; else ok "disk space"; fi

  if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null)" = Enforcing ]; then
    ok "SELinux is enforcing -- the compose file labels its mounts (:z), nothing to do"
  fi

  local port name
  for name in API_PORT PORTAL_PORT; do
    port="$(env_value "$name" | grep . || { [ "$name" = API_PORT ] && echo 8000 || echo 8080; })"
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      # Our own containers answering is fine; anything else is a clash.
      if docker ps --filter "label=com.docker.compose.project=$APP_PROJECT" --format '{{.Ports}}' 2>/dev/null | grep -q ":$port->"; then ok "port $port is ours (already running)"; else bad "port $port is already in use -- set $name in .env"; fi
    else ok "port $port is free"; fi
  done

  [ "$fails" -eq 0 ] && info "all good" || return 1
}

cmd_init() {
  require_docker
  ensure_network
  mkdir -p "${DATA_DIRS[@]}" data/logs "$BACKUP_DIR"
  if [ -f .env ]; then
    info ".env already exists -- leaving it untouched"
    return
  fi
  [ -f .env.example ] || die ".env.example is missing"
  umask 077
  cp .env.example .env
  # A database folder or the old volume means a database already exists (the folder itself may be unreadable here).
  if [ -d "$PG_DIR" ] || docker volume inspect "$OLD_PG_VOLUME" >/dev/null 2>&1; then
    # An existing database was initialised with a password we can't see; a new random one
    # in .env would make every connection fail. Leave it blank (= the compose default).
    set_env POSTGRES_PASSWORD ""
    warn "an existing database was found -- not generating POSTGRES_PASSWORD (the database keeps the password it was created with); it is left empty, i.e. the compose default 'aksor', which is what a database made by the old single-file setup has"
    warn "if the database was created with another password, set POSTGRES_PASSWORD in .env to it"
  else
    set_env POSTGRES_PASSWORD "$(random_secret)"
  fi
  set_env REDIS_PASSWORD "$(random_secret)"   # keeps the job queue closed to anything else on aksor-network
  local portal_pass; portal_pass="$(random_secret)"
  set_env PORTAL_PASSWORD "$portal_pass"
  info "wrote .env from .env.example (mode 600)"
  printf '    portal login:  admin / %s\n' "$portal_pass"
  warn "that password is only shown here; it is saved in .env. Set CORS_ALLOWED_ORIGINS before exposing the portal."
}

cmd_up() {
  for a in "$@"; do
    case "$a" in
      --build) no_build up ;;
      --from-registry) ;;   # the only way now; accepted so older instructions still work
      *) die "usage: up" ;;
    esac
  done
  require_docker
  preflight
  if [ -z "${SKIP_DOCTOR:-}" ]; then
    cmd_doctor || die "fix the above, or SKIP_DOCTOR=1 to go on anyway"
  fi
  ensure_network
  mkdir -p "${DATA_DIRS[@]}" data/logs
  start_infra
  info "starting app (api, scheduler, worker, portal) -- migrations run as the api starts"
  pull_app_images
  app up -d --wait || die "the app didn't come up healthy -- see why with: ./deployment.sh logs api"
  cmd_status
  printf '\n  portal   http://localhost:%s\n  api docs http://localhost:%s/docs\n' "$(env_value PORTAL_PORT | grep . || echo 8080)" "$(env_value API_PORT | grep . || echo 8000)"
}

cmd_down() {
  require_docker
  info "stopping app"
  app down
  info "stopping postgres (the database in ./$PG_DIR is kept)"
  db down
  info "stopping redis"
  redis down
}

cmd_restart() {
  require_docker
  case "${1:-all}" in
    all)   redis restart; db restart; app restart ;;   # dependencies first, so the app doesn't lose them mid-restart
    app)   app restart ;;
    db)    db restart ;;
    redis) redis restart ;;
    *) die "restart [redis|db|app]" ;;
  esac
}

cmd_status() {
  require_docker
  info "redis";    redis ps
  info "postgres"; db ps
  info "app";      app ps
}

cmd_logs() {
  require_docker
  if [ $# -eq 0 ]; then set -- api; fi
  # Services belong to different stacks; follow each stack's share.
  local redis_svcs=() db_svcs=() app_svcs=() s
  for s in "$@"; do
    case "$s" in redis) redis_svcs+=("$s") ;; postgres) db_svcs+=("$s") ;; *) app_svcs+=("$s") ;; esac
  done
  local pids=()
  if [ ${#redis_svcs[@]} -gt 0 ]; then redis logs --tail=100 -f "${redis_svcs[@]}" & pids+=($!); fi
  if [ ${#db_svcs[@]} -gt 0 ];    then db    logs --tail=100 -f "${db_svcs[@]}"    & pids+=($!); fi
  if [ ${#app_svcs[@]} -gt 0 ]; then
    # jdbc-worker only exists under the `jdbc` profile; without it compose says "no such service".
    local prof=(); case " ${app_svcs[*]} " in *" jdbc-worker "*) prof=(--profile jdbc) ;; esac
    app ${prof[@]+"${prof[@]}"} logs --tail=100 -f "${app_svcs[@]}" & pids+=($!)
  fi
  wait "${pids[@]}"
}

cmd_backup() {
  require_docker
  mkdir -p "$BACKUP_DIR" "${DATA_DIRS[@]}"
  local backup_abs; backup_abs="$(cd "$BACKUP_DIR" && pwd)"   # BACKUP_DIR may be relative or absolute
  local stamp; stamp="$(date +%Y%m%d-%H%M%S)"
  local sql="$BACKUP_DIR/aksor-$stamp.sql.gz" files="$BACKUP_DIR/aksor-$stamp-files.tar.gz"
  db ps --status running --services 2>/dev/null | grep -qx postgres || die "postgres isn't running -- nothing to back up"
  # Each file is written under a temporary name and only renamed once it checks out, so a failure never leaves a
  # truncated archive that looks like a backup (and counts toward the retention below).
  info "dumping database -> $sql"
  # -T: no TTY, so the dump isn't mangled; credentials come from the container's own env.
  if ! db exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip > "$sql.part"; then
    rm -f "$sql.part"; die "pg_dump failed -- no backup was made"
  fi
  [ -s "$sql.part" ] && gzip -t "$sql.part" 2>/dev/null || { rm -f "$sql.part"; die "pg_dump produced nothing usable -- no backup was made"; }
  mv "$sql.part" "$sql"

  info "archiving templates, resources, avatars, JDBC drivers and the secrets key -> $files"
  # The key is useless without the database and vice versa: back both up together. The archive is made inside a
  # container because data/ is written by the containers as root (the key is mode 600 in a mode-700 folder), which
  # the host user may be unable to read; the file is handed back to the host user afterwards. Paths in it stay
  # data/<folder>, as before.
  if ! docker run --rm --pull=never -v "$PWD/data:/work/data:ro,z" -v "$backup_abs:/out:z" \
      -e "OWNER=$(id -u):$(id -g)" -e "OUT=aksor-$stamp-files.tar.gz.part" "$BACKUP_HELPER_IMAGE" \
      sh -c 'tar -czf "/out/$OUT" -C /work "$@" && chown "$OWNER" "/out/$OUT" && chmod 600 "/out/$OUT"' sh "${DATA_DIRS[@]}"; then
    rm -f "$files.part" "$sql"
    die "couldn't archive data/ -- is the image $BACKUP_HELPER_IMAGE on this machine (it is once the stack is up)? Set BACKUP_HELPER_IMAGE to any image that has tar. The database dump was removed too: a backup is the pair."
  fi
  tar -tzf "$files.part" >/dev/null 2>&1 || { rm -f "$files.part" "$sql"; die "the data archive didn't verify -- no backup was made"; }
  mv "$files.part" "$files"
  chmod 600 "$sql" "$files"
  # Retention: keep the newest $BACKUP_KEEP of each kind.
  local kind
  for kind in '*.sql.gz' '*-files.tar.gz'; do
    # shellcheck disable=SC2012
    ls -1t "$BACKUP_DIR"/$kind 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | while read -r f; do rm -f -- "$f"; done
  done
  info "done (keeping the newest $BACKUP_KEEP of each)"
}

# Put a backup made by `backup` back. Destructive on purpose -- it REPLACES the database and data/ -- so it asks first,
# takes a safety backup of what is there now (unless --no-backup), and moves the current data/ folders aside
# (data.before-restore-<time>/) instead of deleting them.
cmd_restore() {
  require_docker
  local sql="" files="" yes=0 safety=1 a
  for a in "$@"; do
    case "$a" in
      --yes) yes=1 ;;
      --no-backup) safety=0 ;;
      *.sql.gz) sql="$a" ;;
      *-files.tar.gz) files="$a" ;;
      *) die "restore <backups/aksor-...sql.gz> [<backups/aksor-...-files.tar.gz>] [--yes] [--no-backup]" ;;
    esac
  done
  [ -n "$sql" ] || die "restore <backups/aksor-...sql.gz> [<...-files.tar.gz>] -- name the database dump to restore (ls $BACKUP_DIR)"
  [ -f "$sql" ] || die "$sql not found"
  # The two halves of a backup share a time stamp: find the data archive next to the dump unless one was named.
  [ -n "$files" ] || { files="${sql%.sql.gz}-files.tar.gz"; [ -f "$files" ] || files=""; }
  gzip -t "$sql" 2>/dev/null || die "$sql is not a valid gzip file"
  if [ -n "$files" ]; then
    [ -f "$files" ] || die "$files not found"
    tar -tzf "$files" >/dev/null 2>&1 || die "$files is not a valid archive"
  else
    warn "no data archive found next to $sql -- only the database will be restored (templates, images and the secrets key stay as they are)"
  fi
  [ -f .env ] || die ".env not found -- restore needs the same .env the backup was made with (POSTGRES_PASSWORD...)"

  printf '\nThis will REPLACE the database%s with:\n    %s\n' "$([ -n "$files" ] && echo ' and data/')" "$sql"
  [ -n "$files" ] && printf '    %s\n' "$files"
  printf 'The app is stopped first. Everything changed after that backup is lost%s.\n' "$([ "$safety" = 1 ] && echo ' (a safety backup of the current state is taken first)')"
  if [ "$yes" != 1 ]; then
    [ -t 0 ] || die "not a terminal: add --yes to restore without being asked"
    local answer; read -r -p "Type restore to go on: " answer
    [ "$answer" = restore ] || die "cancelled -- nothing was changed"
  fi

  ensure_network
  start_infra
  if [ "$safety" = 1 ]; then info "safety backup of the current state"; cmd_backup || die "the safety backup failed -- nothing was changed (--no-backup to restore anyway)"; fi
  info "stopping the app"
  app down
  info "replacing the database"
  db exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"' || die "couldn't recreate the database"
  gzip -dc "$sql" | db exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q -o /dev/null' || die "loading $sql failed -- the database is now empty; fix the cause and run restore again (the safety backup is in $BACKUP_DIR)"

  if [ -n "$files" ]; then
    local stamp aside; stamp="$(date +%Y%m%d-%H%M%S)"; aside="data.before-restore-$stamp"
    info "restoring data/ (the current folders are kept in $aside/)"
    local files_abs backup_abs; backup_abs="$(cd "$(dirname "$files")" && pwd)"; files_abs="$(basename "$files")"
    docker run --rm --pull=never -v "$PWD:/work:z" -v "$backup_abs:/in:ro,z" -e "ASIDE=$aside" -e "FILE=$files_abs" "$BACKUP_HELPER_IMAGE" \
      sh -c 'set -e; cd /work; mkdir -p "$ASIDE"; for d in "$@"; do if [ -e "$d" ]; then mkdir -p "$ASIDE/$(dirname "$d")"; mv "$d" "$ASIDE/$d"; fi; done; tar -xzf "/in/$FILE" -C /work' sh "${DATA_DIRS[@]}" \
      || die "couldn't restore data/ -- the previous folders are in $aside/ (move them back)"
  fi
  info "restored. Start it again with ./deployment.sh up (with the version the backup was made with, or newer -- migrations only go forward)"
}

cmd_update() {
  local backup=1
  for a in "$@"; do
    case "$a" in
      --no-backup) backup=0 ;;
      --build|--pull) no_build update ;;
      --from-registry) ;;   # the only way now; accepted so older instructions still work
      *) die "usage: update [--no-backup]" ;;
    esac
  done
  require_docker
  preflight
  ensure_network
  # Redis and Postgres untouched: brought up only if they aren't (a fresh host), never recreated.
  start_infra
  if [ "$backup" = 1 ]; then cmd_backup; else warn "skipping backup (--no-backup)"; fi
  pull_app_images
  info "recreating the app (alembic upgrade head runs as the api starts)"
  app up -d --wait || die "the app didn't come up healthy -- see why with: ./deployment.sh logs api"
  cmd_status
}

pull_app_images() {
  # Each image can be at its own version (a release may update only the portal), so say exactly what is pulled.
  info "pulling app images:"
  app config --images 2>/dev/null | sort -u | sed 's/^/      /'
  app pull || die "couldn't pull the images -- see the lines above: 'no matching manifest' means there is no image for this CPU yet (Intel/AMD and ARM are published); a timeout or 'pull access denied' means this server can't reach Docker Hub (docs/deployment.md, \"Get Docker ready\")"
}

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

main() {
  local cmd="${1:-help}"; shift || true
  case "$cmd" in
    init)    cmd_init "$@" ;;
    up)      cmd_up "$@" ;;
    down)    cmd_down "$@" ;;
    restart) cmd_restart "$@" ;;
    status)  cmd_status "$@" ;;
    logs)    cmd_logs "$@" ;;
    backup)  cmd_backup "$@" ;;
    restore) cmd_restore "$@" ;;
    update)  cmd_update "$@" ;;
    doctor)  cmd_doctor ;;
    redis)   require_docker; ensure_network; redis "${@:-ps}" ;;
    db)      require_docker; ensure_network; db "${@:-ps}" ;;
    app)     require_docker; ensure_network; app "${@:-ps}" ;;
    help|-h|--help) usage ;;
    *) usage; exit 1 ;;
  esac
}

# Always runs -- unless DEPLOYMENT_SH_NO_MAIN is set, which lets the functions above be sourced and tested on their own.
# (Deliberately not "run only when executed": comparing $0 to the script path can silently do nothing under an
# unusual way of starting it, and a deploy script that prints nothing and changes nothing is the worst failure.)
[ -n "${DEPLOYMENT_SH_NO_MAIN:-}" ] || main "$@"
