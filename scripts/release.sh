#!/usr/bin/env bash
# MAINTAINERS ONLY -- one release, end to end: push the Docker images, commit and push the release, publish it on
# GitHub. Not part of installing Aksor Khmer BI (installers use ./deployment.sh, which only pulls).
#
#   scripts/release.sh <version> [--latest] [--yes] [--dry-run]
#
# In order, stopping at the first failure:
#   1. checks   on main, nothing uncommitted, in step with origin/main; api/app/main.py, portal/package.json and
#               package-lock.json all say <version>; CHANGELOG.md has a "## [<version>]" heading; the tag
#               v<version> and the images <version> don't exist yet (a published version is never overwritten).
#   2. images   scripts/publish-images.sh <version> -- builds and pushes engine, portal and jdbc-worker for amd64 and
#               arm64, and writes their tags into docker-compose.yml. --latest also tags them `latest`.
#   3. git      commits docker-compose.yml ("<version>: docker-compose.yml names the published images") and pushes main.
#   4. GitHub   scripts/build-deploy-kit.sh <version> --upload -- creates release v<version> on that commit (the tag
#               with it) with the CHANGELOG section as notes and the install kit attached. Servers then get it with
#               `./deployment.sh update`.
#
# It asks before step 2 (the first thing others can see); --yes skips the question. --dry-run runs the checks and
# prints the plan, pushing nothing.
#
# Before: commit the release -- the version bump and the CHANGELOG heading -- and let CI pass on it; `docker login`
# as an account that can push to aksorkhmerbi; `gh auth login` for the GitHub release.
#
# If step 3 or 4 fails after the images are pushed, fix the cause and run the remaining step by hand (shown in the
# error) -- don't run this script again: the version's images exist now, so its checks refuse it.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[32m==>\033[0m %s\n' "$*"; }
usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

version="" latest="" yes=0 dry=0
while [ $# -gt 0 ]; do
  case "$1" in
    --latest)  latest="--latest"; shift ;;
    --yes|-y)  yes=1; shift ;;
    --dry-run) dry=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*)        die "unknown option $1 -- see scripts/release.sh --help" ;;
    *)         [ -z "$version" ] || die "one <version> only (got '$version' and '$1')"; version="$1"; shift ;;
  esac
done
[ -n "$version" ] || { usage; die "say which version to release, e.g. scripts/release.sh 1.0.0-beta.9"; }
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || die "'$version' isn't a version like 1.0.0 or 1.0.0-beta.9"

prefix="aksorkhmerbi/aksor-khmer-bi"
tag="v$version"

# --- 1. checks ---------------------------------------------------------------------------------------------------

info "checking the release $version"
problems=0
problem() { printf '\033[31m  ✗\033[0m %s\n' "$*" >&2; problems=1; }
ok()      { printf '\033[32m  ✓\033[0m %s\n' "$*"; }

command -v git >/dev/null || die "git is not installed"
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = main ] && ok "on main" || problem "on '$branch' -- release from main"

if [ -n "$(git status --porcelain)" ]; then
  problem "uncommitted changes -- commit the release (or stash the rest) first:"
  git status --short | head -n 10 | sed 's/^/        /' >&2
else
  ok "nothing uncommitted"
fi

git fetch --quiet origin main --tags || die "can't reach origin to compare with it"
ahead="$(git rev-list --count origin/main..HEAD)" behind="$(git rev-list --count HEAD..origin/main)"
if [ "$behind" != 0 ]; then problem "main is $behind commit(s) behind origin/main -- git pull first"
elif [ "$ahead" != 0 ]; then ok "main is $ahead commit(s) ahead of origin/main (pushed in step 3)"
else ok "in step with origin/main"; fi

api_v="$(sed -n 's/^    version="\(.*\)",$/\1/p' api/app/main.py | head -n1)"
pkg_v="$(sed -n 's/^  "version": "\(.*\)",$/\1/p' portal/package.json | head -n1)"
lock_v="$(sed -n '3s/^  "version": "\(.*\)",$/\1/p' portal/package-lock.json)"
[ "$api_v" = "$version" ]  && ok "api/app/main.py says $version"        || problem "api/app/main.py says ${api_v:-?}, not $version"
[ "$pkg_v" = "$version" ]  && ok "portal/package.json says $version"    || problem "portal/package.json says ${pkg_v:-?}, not $version"
[ "$lock_v" = "$version" ] && ok "portal/package-lock.json says $version" || problem "portal/package-lock.json says ${lock_v:-?}, not $version"

if grep -q "^## \[$version\]" CHANGELOG.md; then
  ok "CHANGELOG.md has a $version heading"
  # The section's body, up to the next version heading: a release with no notes is almost always a mistake.
  notes="$(awk -v h="## [$version]" 'index($0,h)==1{on=1;next} on&&/^## \[/{exit} on' CHANGELOG.md | grep -c '[^[:space:]]' || true)"
  [ "$notes" -gt 0 ] || problem "CHANGELOG.md's $version section is empty"
else
  problem "CHANGELOG.md has no '## [$version] - <date>' heading"
fi

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null || git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
  problem "the tag $tag already exists -- $version is released; bump the version"
else
  ok "no tag $tag yet"
fi

for name in engine portal jdbc-worker; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "https://hub.docker.com/v2/repositories/$prefix-$name/tags/$version" || echo 000)"
  case "$code" in
    404) ok "$prefix-$name:$version isn't published yet" ;;
    200) problem "$prefix-$name:$version is already on Docker Hub -- a published version is never overwritten" ;;
    *)   problem "couldn't ask Docker Hub about $prefix-$name:$version (HTTP $code)" ;;
  esac
done

if [ "$dry" = 0 ]; then
  command -v docker >/dev/null || problem "docker is not installed"
  command -v gh >/dev/null && gh auth status >/dev/null 2>&1 && ok "gh is signed in" || problem "gh isn't installed or signed in (gh auth login) -- step 4 needs it"
fi

[ "$problems" = 0 ] || die "fix the above, then run it again"
scripts/publish-images.sh "$version" $latest --dry-run >/dev/null || die "scripts/publish-images.sh refused the version (run it with --dry-run to see why)"

info "plan for $version (commit $(git rev-parse --short HEAD)):"
echo "      2. build and push $prefix-{engine,portal,jdbc-worker}:$version${latest:+ (and latest)}"
echo "      3. commit docker-compose.yml and push main to origin"
echo "      4. create the GitHub release $tag with the install kit"
[ "$dry" = 0 ] || { info "dry run: nothing pushed"; exit 0; }

if [ "$yes" = 0 ]; then
  printf 'Publish %s now? Images and the release are public once pushed. [y/N] ' "$version"
  read -r answer
  case "$answer" in y|Y|yes|YES) ;; *) die "stopped -- nothing was pushed" ;; esac
fi

# --- 2. images ---------------------------------------------------------------------------------------------------

scripts/publish-images.sh "$version" $latest

# --- 3. git ------------------------------------------------------------------------------------------------------

info "committing docker-compose.yml and pushing main"
if git diff --quiet -- docker-compose.yml; then
  info "docker-compose.yml already named $version -- nothing to commit"
else
  git add docker-compose.yml
  git commit -q -m "$version: docker-compose.yml names the published images" \
    || die "the commit failed -- commit docker-compose.yml yourself, then: git push origin main && scripts/build-deploy-kit.sh $version --upload"
fi
git push origin main || die "the push failed -- fix it, then: git push origin main && scripts/build-deploy-kit.sh $version --upload"

# --- 4. GitHub ---------------------------------------------------------------------------------------------------

scripts/build-deploy-kit.sh "$version" --upload \
  || die "the GitHub release failed -- fix it, then: scripts/build-deploy-kit.sh $version --upload"

info "released $version: images on Docker Hub, $tag on GitHub. Servers update with ./deployment.sh update"
