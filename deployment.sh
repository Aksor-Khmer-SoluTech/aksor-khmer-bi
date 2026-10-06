#!/usr/bin/env bash
# Deploy and operate Aksor Khmer BI with Docker Compose.
#
# Three stacks, deliberately separate (see DEPLOYMENT.md for the same steps by hand):
#   redis  docker-compose.redis.yml  redis                 project "aksor-redis"
#   db     docker-compose.db.yml     postgres              project "aksor-db"
#   app    docker-compose.yml        api, scheduler,       project "aksor-app"
#                                    worker, portal
# joined by one external network, "aksor-network". The app can be rebuilt, updated or
# rolled back without ever restarting the database or the queue.
#
#   ./deployment.sh init              first-time setup: network + .env (from .env.example) with generated secrets
#   ./deployment.sh up                start redis, then postgres (each waits until healthy), then the app
#   ./deployment.sh up --from-registry   pull AKSOR_VERSION images instead of building
#   ./deployment.sh update [--no-backup] [--pull] [--from-registry]
#                                     back up, rebuild the app, recreate it (migrations run at
#                                     api start); redis and postgres are left alone
#   ./deployment.sh publish <version> [--latest]
#                                     build api + portal for PLATFORMS (default linux/amd64) and push
#                                     to the registry named by AKSOR_IMAGE_PREFIX (Docker Hub: user/aksor-khmer-bi)
#   ./deployment.sh doctor [pull]     check this machine before building (docker, compose, ports, disk, and whether
#                                     a container can reach what the build downloads); `up` runs it for you
#   ./deployment.sh down              stop the app, then postgres, then redis (volumes and data are kept)
#   ./deployment.sh restart [redis|db|app]
#   ./deployment.sh status
#   ./deployment.sh logs [service...] follow logs (default: api)
#   ./deployment.sh backup            pg_dump + templates, resources, avatars, secrets key -> ./backups/
#   ./deployment.sh redis|db|app <up|down|status|logs ...>   operate one stack alone
#
# Settings come from ./.env (never committed): POSTGRES_PASSWORD, PORTAL_USERNAME,
# PORTAL_PASSWORD, CORS_ALLOWED_ORIGINS, ... -- see DEPLOYMENT.md and docs/deployment.md.
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
# Everything the api writes outside the database (all bind-mounted in docker-compose.yml).
DATA_DIRS=(data/report_templates data/secrets data/image_resources data/stylesheet_resources data/avatars)

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_off=$'\033[0m'
[ -t 1 ] || { c_red=; c_grn=; c_ylw=; c_off=; }
info() { printf '%s==>%s %s\n' "$c_grn" "$c_off" "$*"; }
warn() { printf '%swarning:%s %s\n' "$c_ylw" "$c_off" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$c_red" "$c_off" "$*" >&2; exit 1; }

redis() { docker compose -p "$REDIS_PROJECT" -f "$REDIS_FILE" "$@"; }
db()    { docker compose -p "$DB_PROJECT"    -f "$DB_FILE"    "$@"; }
app()   { docker compose -p "$APP_PROJECT"   -f "$APP_FILE"   "$@"; }

# Redis first, then Postgres, each waiting until healthy (the app needs both).
start_infra() {
  info "starting redis"
  redis up -d --wait
  info "starting postgres"
  db up -d --wait
}

require_docker() {
  command -v docker >/dev/null || die "docker is not installed"
  docker compose version >/dev/null 2>&1 || die "the Docker Compose v2 plugin is required (docker compose ...)"
  docker info >/dev/null 2>&1 || die "can't reach the Docker daemon -- is it running?"
}

ensure_network() {
  docker network inspect "$NETWORK" >/dev/null 2>&1 || { info "creating network $NETWORK"; docker network create "$NETWORK" >/dev/null; }
}

env_value() { # env_value KEY -> value from .env (empty if absent)
  [ -f .env ] || return 0
  sed -n "s/^$1=//p" .env | tail -n1
}

set_env() { # set_env KEY VALUE -- fill KEY= in .env (portable: no sed -i)
  awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' .env > .env.tmp && mv .env.tmp .env
}

random_secret() { # URL/shell-safe, 32 chars
  # `|| true`: head closing the pipe SIGPIPEs tr, which pipefail would turn into a fatal error.
  LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 || true
}

preflight() {
  [ -f .env ] || die ".env not found -- run ./deployment.sh init first"
  [ -n "$(env_value PORTAL_PASSWORD)" ] || warn "PORTAL_PASSWORD is unset: admin routes answer 503 until a break-glass login is configured"
  case "$(env_value POSTGRES_PASSWORD)" in
    ""|aksor) warn "POSTGRES_PASSWORD is the default ('aksor') -- fine for a throwaway machine, not for a server anyone else can reach" ;;
  esac
  if [ -z "$(env_value CORS_ALLOWED_ORIGINS)" ]; then
    warn "CORS_ALLOWED_ORIGINS is unset (defaults to http://localhost:8080) -- set it to the portal's public URL"
  fi
}

# Checks the machine before a long build, so a problem shows up in seconds with a fix instead of ten minutes in.
# Prints ok / warn / FAIL for each check; exits non-zero only on FAIL. SKIP_DOCTOR=1 skips it inside `up`.
cmd_doctor() {
  local building="${1:-build}" fails=0
  ok()   { printf '  %sok%s    %s\n' "$c_grn" "$c_off" "$*"; }
  bad()  { printf '  %sFAIL%s  %s\n' "$c_red" "$c_off" "$*"; fails=$((fails + 1)); }
  note() { printf '  %swarn%s  %s\n' "$c_ylw" "$c_off" "$*"; }
  info "checking this machine (details: DEPLOYMENT.md, \"Before you start\")"

  command -v docker >/dev/null && ok "docker: $(docker --version 2>/dev/null | head -n1)" || { bad "docker is not installed -- see DEPLOYMENT.md, \"Get Docker ready\""; return 1; }
  if docker compose version >/dev/null 2>&1; then ok "compose: $(docker compose version --short 2>/dev/null)"; else bad "the Docker Compose v2 plugin is missing (the old \`docker-compose\` command is not enough)"; fi
  docker info >/dev/null 2>&1 && ok "the Docker daemon answers" || { bad "can't reach the Docker daemon -- is it running, and are you in the docker group (or using sudo)?"; return 1; }

  local arch; arch="$(docker info --format '{{.Architecture}}' 2>/dev/null)"
  ok "CPU: ${arch:-unknown}"
  if [ "$building" = pull ] && [ "$arch" != x86_64 ] && [ "$arch" != amd64 ]; then
    note "images are published for linux/amd64 unless PLATFORMS says otherwise; on $arch pulling may fail with 'exec format error'"
  fi

  local free_kb; free_kb="$(df -Pk . 2>/dev/null | awk 'NR==2 {print $4}')"
  if [ -n "$free_kb" ] && [ "$free_kb" -lt 10485760 ]; then note "only $((free_kb / 1048576)) GB free here; a build needs about 10 GB (LibreOffice, Tesseract, fonts)"; else ok "disk space"; fi

  if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null)" = Enforcing ]; then
    ok "SELinux is enforcing -- the compose file labels its mounts (:z), nothing to do"
  fi

  local port name
  for name in API_PORT PORTAL_PORT; do
    port="$(env_value "$name" | grep . || { [ "$name" = API_PORT ] && echo 8000 || echo 8080; })"
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      # Our own containers answering is fine; anything else is a clash.
      if docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":$port->"; then ok "port $port is ours (already running)"; else bad "port $port is already in use -- set $name in .env"; fi
    else ok "port $port is free"; fi
  done

  if [ "$building" = build ]; then
    local net apt scheme pip npm
    net="$(env_value BUILD_NETWORK | grep . || echo default)"
    apt="$(env_value APT_MIRROR | grep . || echo deb.debian.org)"
    scheme="$(env_value APT_SCHEME | grep . || echo http)"
    pip="$(env_value PIP_INDEX_URL | grep . || echo https://pypi.org/simple)"
    npm="$(env_value NPM_REGISTRY | grep . || echo https://registry.npmjs.org/)"
    local before=$fails
    info "can a container reach what the build downloads? (network: $net)"
    local netarg=(); [ "$net" = host ] && netarg=(--network host)
    local result base=python:3.12-slim-trixie
    # The build needs this image anyway, so fetching it now costs nothing -- and if even that fails, that's the answer.
    if ! docker image inspect "$base" >/dev/null 2>&1 && ! docker pull -q "$base" >/dev/null 2>&1; then
      bad "can't download the base image $base from Docker Hub -- this machine can't reach the registry (a proxy, firewall or DNS problem)"
    fi
    result="$(docker run -i --rm ${netarg[@]+"${netarg[@]}"} "$base" python - "$scheme://$apt/" "$pip" "$npm" <<'PY' 2>/dev/null || true
import sys, urllib.request
for url in sys.argv[1:]:
    try:
        urllib.request.urlopen(url, timeout=8).close()
        print("ok", url)
    except Exception as exc:
        print("FAIL", url, type(exc).__name__)
PY
)"
    local line
    [ -n "$result" ] || bad "the network check could not start a container -- try: docker run --rm $base true"
    while IFS= read -r line; do
      case "$line" in
        ok\ *) ok "reachable: ${line#ok }" ;;
        FAIL\ *) bad "can't reach ${line#FAIL }" ;;
        "") ;;
        *) bad "network check could not run: $line" ;;
      esac
    done <<EOF2
$result
EOF2
    if [ "$fails" -gt "$before" ]; then
      printf '\n  The build would fail at the download step. Try, in this order:\n'
      printf '    1. BUILD_NETWORK=host in .env (build on the server'"'"'s own network)\n'
      printf '    2. fix Docker'"'"'s network (UFW forwarding, DNS) -- DEPLOYMENT.md, "Get Docker ready first"\n'
      printf '    3. APT_SCHEME=https if only port 80 is blocked; APT_MIRROR / PIP_INDEX_URL / NPM_REGISTRY for internal mirrors\n'
      printf '    4. build elsewhere and use ./deployment.sh up --from-registry\n\n'
    fi
  fi

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
  if docker volume inspect aksor-khmer-bi_pgdata >/dev/null 2>&1; then
    # An existing database was initialised with a password we can't see; a new random one
    # in .env would make every connection fail. Leave it blank (= the compose default).
    warn "an existing Postgres volume was found -- not generating POSTGRES_PASSWORD (the database keeps the password it was created with)"
    warn "if you know it, set POSTGRES_PASSWORD in .env"
  else
    set_env POSTGRES_PASSWORD "$(random_secret)"
  fi
  local portal_pass; portal_pass="$(random_secret)"
  set_env PORTAL_PASSWORD "$portal_pass"
  info "wrote .env from .env.example (mode 600)"
  printf '    portal login:  admin / %s\n' "$portal_pass"
  warn "that password is only shown here; it is saved in .env. Set CORS_ALLOWED_ORIGINS before exposing the portal."
}

cmd_up() {
  require_docker
  local build=(--build)
  for a in "$@"; do
    case "$a" in
      --from-registry) build=() ;;
      *) die "up [--from-registry]" ;;
    esac
  done
  preflight
  if [ -z "${SKIP_DOCTOR:-}" ]; then
    if [ ${#build[@]} -eq 0 ]; then cmd_doctor pull || die "fix the above, or SKIP_DOCTOR=1 to go on anyway"; else cmd_doctor build || die "fix the above, or SKIP_DOCTOR=1 to go on anyway"; fi
  fi
  ensure_network
  mkdir -p "${DATA_DIRS[@]}" data/logs
  start_infra
  info "starting app (api, scheduler, worker, portal) -- migrations run as the api starts"
  if [ ${#build[@]} -eq 0 ]; then app pull; fi
  app up -d "${build[@]}" --wait
  cmd_status
  printf '\n  portal   http://localhost:%s\n  api docs http://localhost:%s/docs\n' "$(env_value PORTAL_PORT | grep . || echo 8080)" "$(env_value API_PORT | grep . || echo 8000)"
}

cmd_down() {
  require_docker
  info "stopping app"
  app down
  info "stopping postgres (named volumes are kept)"
  db down
  info "stopping redis"
  redis down
}

cmd_restart() {
  require_docker
  case "${1:-all}" in
    all)   app restart; db restart; redis restart ;;
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
  if [ ${#app_svcs[@]} -gt 0 ];   then app   logs --tail=100 -f "${app_svcs[@]}"   & pids+=($!); fi
  wait "${pids[@]}"
}

cmd_backup() {
  require_docker
  mkdir -p "$BACKUP_DIR"
  local stamp; stamp="$(date +%Y%m%d-%H%M%S)"
  local sql="$BACKUP_DIR/aksor-$stamp.sql.gz" files="$BACKUP_DIR/aksor-$stamp-files.tar.gz"
  db ps --status running --services 2>/dev/null | grep -qx postgres || die "postgres isn't running -- nothing to back up"
  info "dumping database -> $sql"
  # -T: no TTY, so the dump isn't mangled; credentials come from the container's own env.
  db exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip > "$sql"
  [ -s "$sql" ] || { rm -f "$sql"; die "pg_dump produced nothing"; }
  info "archiving templates, resources, avatars and the secrets key -> $files"
  # The key is useless without the database and vice versa: back both up together.
  tar -czf "$files" "${DATA_DIRS[@]}"
  chmod 600 "$sql" "$files"
  # Retention: keep the newest $BACKUP_KEEP of each kind.
  local kind
  for kind in '*.sql.gz' '*-files.tar.gz'; do
    # shellcheck disable=SC2012
    ls -1t "$BACKUP_DIR"/$kind 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | while read -r f; do rm -f -- "$f"; done
  done
  info "done (keeping the newest $BACKUP_KEEP of each)"
}

cmd_update() {
  require_docker
  local backup=1 pull=() registry=0
  for a in "$@"; do
    case "$a" in
      --no-backup) backup=0 ;;
      --pull) pull=(--pull) ;;
      --from-registry) registry=1 ;;
      *) die "update [--no-backup] [--pull] [--from-registry]" ;;
    esac
  done
  preflight
  ensure_network
  # Redis and Postgres untouched: brought up only if they aren't (a fresh host), never recreated.
  start_infra
  if [ "$backup" = 1 ]; then cmd_backup; else warn "skipping backup (--no-backup)"; fi
  if [ "$registry" = 1 ]; then
    info "pulling app images ($(image_prefix)-{engine,portal}:${AKSOR_VERSION:-$(env_value AKSOR_VERSION)})"
    app pull
  else
    info "building app images"
    app build "${pull[@]}"
  fi
  info "recreating the app (alembic upgrade head runs as the api starts)"
  app up -d --wait
  cmd_status
}

image_prefix() { echo "${AKSOR_IMAGE_PREFIX:-$(env_value AKSOR_IMAGE_PREFIX)}"; }

cmd_publish() {
  require_docker
  docker buildx version >/dev/null 2>&1 || die "docker buildx is required to publish"
  local version="${1:-}" latest=0
  [ -n "$version" ] || die "publish <version> [--latest]   e.g. publish 1.0.1 --latest"
  [ "${2:-}" = "--latest" ] && latest=1
  [[ "$version" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || die "'$version' isn't a valid image tag"
  local prefix; prefix="$(image_prefix)"
  case "$prefix" in
    */*) ;;
    *) die "set AKSOR_IMAGE_PREFIX (in .env or the environment) to <dockerhub-user>/aksor-khmer-bi -- got '${prefix:-<empty>}'" ;;
  esac
  local platforms="${PLATFORMS:-linux/amd64}"
  info "publishing $prefix-{engine,portal}:$version for $platforms (docker login first if the push is denied)"
  local name file tags
  for name in engine portal; do
    # Both build from the repo root: the portal bundles /docs (portal/Dockerfile).
    if [ "$name" = engine ]; then file=Dockerfile; else file=portal/Dockerfile; fi
    tags=(-t "$prefix-$name:$version")
    [ "$latest" = 1 ] && tags+=(-t "$prefix-$name:latest")
    info "building and pushing $prefix-$name"
    docker buildx build --platform "$platforms" "${tags[@]}" -f "$file" --push .
  done
  info "published. On the server: AKSOR_IMAGE_PREFIX=$prefix AKSOR_VERSION=$version ./deployment.sh up --from-registry"
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
    update)  cmd_update "$@" ;;
    publish) cmd_publish "$@" ;;
    doctor)  cmd_doctor "${1:-build}" ;;
    redis)   require_docker; ensure_network; redis "${@:-ps}" ;;
    db)      require_docker; ensure_network; db "${@:-ps}" ;;
    app)     require_docker; ensure_network; app "${@:-ps}" ;;
    help|-h|--help) usage ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
