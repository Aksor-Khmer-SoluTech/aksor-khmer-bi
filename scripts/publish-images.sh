#!/usr/bin/env bash
# MAINTAINERS ONLY -- not part of installing Aksor Khmer BI (installers use ./deployment.sh, which only pulls).
#
# Builds app images and pushes them to Docker Hub, so servers can deploy that version:
#   aksorkhmerbi/aksor-khmer-bi-engine        api, scheduler and worker   (built from api/Dockerfile)
#   aksorkhmerbi/aksor-khmer-bi-portal        the web console             (portal/Dockerfile)
#   aksorkhmerbi/aksor-khmer-bi-jdbc-worker   optional, uploaded drivers  (jdbc-worker/Dockerfile)
#
#   scripts/publish-images.sh <version> [--latest]          all three, at <version>
#   scripts/publish-images.sh --portal 1.0.1                only the portal, at 1.0.1
#   scripts/publish-images.sh --engine 1.0.2 --portal 1.0.1 only those two, each at its own version
#   scripts/publish-images.sh 1.0.2 --portal 1.0.3          all three, the portal at a different version
# Flags: --engine (or --api) <v>, --portal <v>, --jdbc-worker (or --jdbc) <v>, --latest (also tag each pushed image
# `latest`), --dry-run (print what would be built, build nothing).
#
# After pushing, it writes each published image's new tag into docker-compose.yml (only those images: a portal-only
# release changes only the portal's line). Commit that with the release's CHANGELOG.md heading and push -- servers
# then get it with `git pull` and `./deployment.sh update`.
#
# Before: `docker login` as an account that can push to aksorkhmerbi, publish only a commit CI passed on, and give
# the version its heading in CHANGELOG.md -- saying which image versions it uses when they differ. Keep the Docker
# Hub repositories Public so servers pull without a login.
#
# PLATFORMS (default linux/amd64,linux/arm64): every image is published for Intel/AMD servers and for ARM (Apple-silicon
# Macs, Graviton and other ARM servers), one tag covering both -- each machine pulls its own and runs it natively. On an
# Apple-silicon Mac the arm64 half builds natively and the amd64 half under emulation (the slow part), and the
# other way round on an Intel/AMD machine. PLATFORMS=linux/amd64 publishes Intel/AMD only.
# APT_MIRROR / APT_SCHEME / PIP_INDEX_URL / NPM_REGISTRY, when set, point the build's downloads at mirrors.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[32m==>\033[0m %s\n' "$*"; }
usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

needs_version() { [ $# -ge 2 ] && [ "${2#-}" = "$2" ] || die "$1 needs a version, e.g. $1 1.0.1"; }
valid_tag() { [[ "$1" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || die "'$1' isn't a valid image tag"; }

# One version per image; empty = not published this run. (Plain variables: macOS ships bash 3.2, no assoc arrays.)
all="" engine="" portal="" jdbc="" latest=0 dry=0
while [ $# -gt 0 ]; do
  case "$1" in
    --engine|--api)        needs_version "$@"; engine="$2"; shift 2 ;;
    --portal)              needs_version "$@"; portal="$2"; shift 2 ;;
    --jdbc-worker|--jdbc)  needs_version "$@"; jdbc="$2"; shift 2 ;;
    --latest)              latest=1; shift ;;
    --dry-run)             dry=1; shift ;;
    -h|--help)             usage; exit 0 ;;
    -*)                    die "unknown option $1 -- see scripts/publish-images.sh --help" ;;
    *)                     [ -z "$all" ] || die "one <version> only (got '$all' and '$1')"; all="$1"; shift ;;
  esac
done

# A plain <version> covers every image a flag didn't give its own version.
if [ -n "$all" ]; then
  engine="${engine:-$all}"; portal="${portal:-$all}"; jdbc="${jdbc:-$all}"
fi
[ -n "$engine$portal$jdbc" ] || { usage; die "say what to publish: a <version> for all three, or --engine / --portal / --jdbc-worker <version>"; }
for v in "$engine" "$portal" "$jdbc"; do [ -z "$v" ] || valid_tag "$v"; done

prefix="aksorkhmerbi/aksor-khmer-bi"
compose_file="docker-compose.yml"
platforms="${PLATFORMS:-linux/amd64,linux/arm64}"

plan=()
[ -n "$engine" ] && plan+=("engine:api/Dockerfile:$engine")
[ -n "$portal" ] && plan+=("portal:portal/Dockerfile:$portal")
[ -n "$jdbc" ]   && plan+=("jdbc-worker:jdbc-worker/Dockerfile:$jdbc")

info "publishing for $platforms$([ "$latest" = 1 ] && echo ', also tagged latest'):"
for item in "${plan[@]}"; do
  IFS=: read -r name _ version <<<"$item"
  printf '      %s-%s:%s\n' "$prefix" "$name" "$version"
done
[ "$dry" = 0 ] || { info "dry run: nothing built"; exit 0; }

command -v docker >/dev/null || die "docker is not installed"
docker buildx version >/dev/null 2>&1 || die "docker buildx is required"
docker info >/dev/null 2>&1 || die "can't reach the Docker daemon -- is Docker Desktop running?"

# Download mirrors for the build (the Dockerfiles' ARGs), passed through only when set here.
build_args=()
for arg in APT_MIRROR APT_SCHEME PIP_INDEX_URL NPM_REGISTRY; do
  [ -z "${!arg:-}" ] || build_args+=(--build-arg "$arg=${!arg}")
done

for item in "${plan[@]}"; do
  IFS=: read -r name file version <<<"$item"
  tags=(-t "$prefix-$name:$version")
  [ "$latest" = 1 ] && tags+=(-t "$prefix-$name:latest")
  info "building and pushing $prefix-$name:$version"
  # All build from the repo root: the portal bundles /docs (portal/Dockerfile).
  # No provenance/SBOM attestations: they add time and show up as extra "unknown/unknown" platforms on Docker Hub.
  docker buildx build --platform "$platforms" --provenance=false --sbom=false "${tags[@]}" ${build_args[@]+"${build_args[@]}"} -f "$file" --push .
done

# Point docker-compose.yml at what was just pushed -- each published image's tag, nothing else.
for item in "${plan[@]}"; do
  IFS=: read -r name _ version <<<"$item"
  sed -i.bak -E "s#(image: $prefix-$name):[A-Za-z0-9_.-]+#\1:$version#" "$compose_file" && rm -f "$compose_file.bak"
done

info "published. $compose_file now names:"
grep -E "image: $prefix-" "$compose_file" | sed 's/^ *image: /      /' | sort -u
echo "    commit it with the release's CHANGELOG.md heading and push; servers: git pull && ./deployment.sh update"
