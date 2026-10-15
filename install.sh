#!/usr/bin/env bash
# Install Aksor Khmer BI on a server -- no copy of the repository needed, only Docker (with Compose v2) and curl or
# wget. It downloads the release's install kit, checks its checksum, unpacks it into ./aksor-khmer-bi, then runs
# `./deployment.sh init` (network, data folders, .env with generated passwords) and `./deployment.sh up`.
#
#   curl -fsSL https://raw.githubusercontent.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/main/install.sh | bash
#   bash install.sh [<version>] [--dir <folder>] [--no-start] [--from <kit.tar.gz>]
#
#   <version>        e.g. 1.0.0-beta.5 (default: the newest release, pre-releases included)
#   --dir <folder>   where to install (default: ./aksor-khmer-bi)
#   --no-start       stop after `init`, so .env can be edited first (CORS_ALLOWED_ORIGINS, PORTAL_API_BASE_URL...)
#   --from <file>    a kit copied to this machine, for a server without internet (checked against <file>.sha256
#                    when it is next to it)
# AKSOR_RELEASES_URL points it at a mirror of the release downloads (see docs/deployment.md).
#
# Already installed? Don't run this again: `./deployment.sh update` in that folder moves it to a new version.
set -euo pipefail

REPO_RELEASES="https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/releases/download"
RELEASES_API="https://api.github.com/repos/Aksor-Khmer-SoluTech/aksor-khmer-bi/releases?per_page=1"
RELEASES_URL="${AKSOR_RELEASES_URL:-$REPO_RELEASES}"
KIT_NAME="aksor-khmer-bi-deploy"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_off=$'\033[0m'
[ -t 1 ] || { c_red=; c_grn=; c_off=; }
info() { printf '%s==>%s %s\n' "$c_grn" "$c_off" "$*"; }
die()  { printf '%serror:%s %s\n' "$c_red" "$c_off" "$*" >&2; exit 1; }

version="" dir="aksor-khmer-bi" start=1 from=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) dir="${2:?--dir needs a folder}"; shift ;;
    --no-start) start=0 ;;
    --from) from="${2:?--from needs the kit file}"; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "unknown option $1 (see --help)" ;;
    *) version="${1#v}" ;;
  esac
  shift
done

download() {
  if command -v curl >/dev/null; then curl -fsSL --retry 2 -o "$2" "$1"
  elif command -v wget >/dev/null; then wget -q -O "$2" "$1"
  else die "install curl or wget first"; fi
}
sha256_of() { if command -v sha256sum >/dev/null; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi; }

command -v docker >/dev/null || die "Docker is not installed -- see https://docs.docker.com/engine/install/ (docs/deployment.md, \"Get Docker ready\")"
docker compose version >/dev/null 2>&1 || die "the Docker Compose v2 plugin is required (docker compose ...)"
[ ! -e "$dir/deployment.sh" ] || die "$dir is already installed -- to move it to a new version: cd $dir && ./deployment.sh update"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
expected=""
if [ -n "$from" ]; then
  [ -f "$from" ] || die "$from not found"
  tarball="$from"
  [ ! -f "$from.sha256" ] || expected="$(awk '{print $1; exit}' "$from.sha256")"
else
  if [ -z "$version" ]; then
    if [ -n "${AKSOR_RELEASES_URL:-}" ]; then
      download "$RELEASES_URL/LATEST" "$tmp/latest" || die "couldn't read $RELEASES_URL/LATEST -- name the version"
      version="$(tr -d ' \r\n' < "$tmp/latest")"
    else
      download "$RELEASES_API" "$tmp/latest" || die "couldn't ask GitHub for the newest release -- name the version: bash install.sh 1.0.0"
      version="$(sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' "$tmp/latest" | head -n1)"
    fi
    [ -n "$version" ] || die "couldn't find the newest release -- name the version"
  fi
  url="$RELEASES_URL/v$version/$KIT_NAME-$version.tar.gz"
  info "downloading Aksor Khmer BI $version"
  tarball="$tmp/kit.tar.gz"
  download "$url" "$tarball" || die "couldn't download $url -- is $version a released version?"
  download "$url.sha256" "$tmp/kit.sha256" || die "couldn't download $url.sha256"
  expected="$(awk '{print $1; exit}' "$tmp/kit.sha256")"
fi
if [ -n "$expected" ]; then
  [ "$(sha256_of "$tarball")" = "$expected" ] || die "the download's checksum doesn't match -- nothing was installed; try again"
  info "checksum ok"
fi

mkdir -p "$tmp/x"
tar -xzf "$tarball" -C "$tmp/x" || die "not a valid kit archive"
src="$(find "$tmp/x" -mindepth 1 -maxdepth 1 -type d | head -n1)"
[ -f "$src/deployment.sh" ] && [ -f "$src/VERSION" ] || die "that archive isn't an Aksor Khmer BI install kit"
mkdir -p "$dir"
cp -R "$src/." "$dir/"
chmod +x "$dir/deployment.sh"
info "installed $(cat "$dir/VERSION") into $dir"

cd "$dir"
./deployment.sh init
if [ "$start" = 1 ]; then
  ./deployment.sh up
  printf '\nNext: open .env and set CORS_ALLOWED_ORIGINS and PORTAL_API_BASE_URL to the addresses people will use,\nthen run ./deployment.sh up again (in %s). Later updates: ./deployment.sh update\n' "$PWD"
else
  printf '\nNext (in %s): edit .env -- CORS_ALLOWED_ORIGINS and PORTAL_API_BASE_URL -- then ./deployment.sh up\n' "$PWD"
fi
