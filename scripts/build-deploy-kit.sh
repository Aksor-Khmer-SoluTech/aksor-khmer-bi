#!/usr/bin/env bash
# MAINTAINERS ONLY -- builds the install kit for a release: everything a server needs to run Aksor Khmer BI, without
# the repository. Servers install it with install.sh and move between versions with `./deployment.sh update`.
#
#   scripts/build-deploy-kit.sh <version> [--ref <git ref>] [--out <dir>] [--upload]
#
#   dist-kit/aksor-khmer-bi-deploy-<version>.tar.gz          deployment.sh, the three compose files, .env.example,
#                                                            VERSION, config/ (examples and READMEs)
#   dist-kit/aksor-khmer-bi-deploy-<version>.tar.gz.sha256   its checksum (install.sh and update check it)
#
# Built from a commit (default HEAD), never from the working tree, so nothing uncommitted ends up in a kit -- run it
# after committing the docker-compose.yml that scripts/publish-images.sh rewrote. --upload then creates the GitHub
# release v<version> on that commit (a pre-release when the version has a "-", e.g. 1.0.0-beta.5; the notes are the
# version's CHANGELOG.md section) and attaches the kit, its checksum and install.sh -- needs `gh`, signed in.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[32m==>\033[0m %s\n' "$*"; }
usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

version="" ref="HEAD" out="dist-kit" upload=0
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) ref="${2:?--ref needs a git ref}"; shift ;;
    --out) out="${2:?--out needs a folder}"; shift ;;
    --upload) upload=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) die "unknown flag $1 (see --help)" ;;
    *) [ -z "$version" ] || die "one version only"; version="${1#v}" ;;
  esac
  shift
done
[ -n "$version" ] || { usage; exit 1; }
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || die "'$version' isn't a version like 1.2.0 or 1.2.0-beta.5"
commit="$(git rev-parse --verify "$ref^{commit}")" || die "no such commit: $ref"

name="aksor-khmer-bi-deploy-$version"
stage="$(mktemp -d)"; trap 'rm -rf "$stage"' EXIT
kit="$stage/$name"
mkdir -p "$kit"

info "building $name from $(git rev-parse --short "$commit")"
git archive "$commit" deployment.sh docker-compose.yml docker-compose.db.yml docker-compose.redis.yml .env.example | tar -x -C "$kit"
printf '%s\n' "$version" > "$kit/VERSION"

# The compose file this kit runs must name released images -- never a build.
grep -q '^ *build:' "$kit/docker-compose.yml" && die "docker-compose.yml has a build: section -- a kit only pulls released images"
grep -qE 'image: aksorkhmerbi/aksor-khmer-bi-engine:[0-9]' "$kit/docker-compose.yml" || die "docker-compose.yml names no released engine image"

mkdir -p "$kit/config/portal" "$kit/config/protected-terms" "$kit/config/protected-terms-exclude"
git show "$commit:portal/public/config.js" > "$kit/config/portal/config.js.example"
cat > "$kit/config/portal/README.md" <<'EOF'
# The portal's settings

Usually nothing goes here: set `PORTAL_API_BASE_URL` (and, if you like, the branding `PORTAL_*` settings) in `.env`,
then run `./deployment.sh up`.

To write the whole file yourself instead, copy `config.js.example` to `config.js` here and edit it. When
`config.js` exists, the portal uses it as it is and ignores every `PORTAL_*` setting in `.env`. Run
`./deployment.sh up` after changing it.
EOF
cat > "$kit/config/protected-terms/README.md" <<'EOF'
# Your own protected terms

Khmer terms the OCR must keep whole, on top of the lists that ship inside the release. Put one or more `*.txt` files
here: one term per line, `#` starts a comment. They are read at the next `./deployment.sh up`.
See the protected-terms guide in the documentation.
EOF
cat > "$kit/config/protected-terms-exclude/README.md" <<'EOF'
# Terms to stop protecting

The opposite of `../protected-terms/`: a term listed in a `*.txt` file here is no longer kept whole, even if a
shipped list protects it. Same format, read at the next `./deployment.sh up`.
EOF
cat > "$kit/README.md" <<EOF
# Aksor Khmer BI $version -- install kit

    ./deployment.sh init     # once: the network, the data folders and .env with generated passwords
    ./deployment.sh up       # start it (pulls the released images)
    ./deployment.sh update   # later: back up, then move to the newest release
    ./deployment.sh help     # everything else

Your settings: .env (see .env.example). Your own files: config/. Your data: data/ and backups/.
Full guide: https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/blob/v$version/docs/deployment.md
EOF

mkdir -p "$out"
tarball="$out/$name.tar.gz"
(cd "$stage" && tar -cf - "$name") | gzip -n > "$tarball"
(cd "$out" && if command -v sha256sum >/dev/null; then sha256sum "$name.tar.gz"; else shasum -a 256 "$name.tar.gz"; fi) > "$tarball.sha256"
info "kit: $tarball ($(du -h "$tarball" | cut -f1 | tr -d ' '))"
tar -tzf "$tarball" | sed 's/^/      /'

[ "$upload" = 1 ] || { echo "    upload it with --upload, or attach $tarball, its .sha256 and install.sh to the GitHub release v$version"; exit 0; }

command -v gh >/dev/null || die "--upload needs the GitHub CLI (gh), signed in"
tag="v$version"
notes="$stage/notes.md"
# This version's CHANGELOG.md section: from its heading to the next one.
git show "$commit:CHANGELOG.md" | awk -v v="$version" '
  /^## / { if (found) exit; if (index($0, "[" v "]") || index($0, " " v)) { found = 1; next } }
  found { print }' > "$notes"
[ -s "$notes" ] || die "CHANGELOG.md (at $ref) has no section for $version -- give the version its heading first"
if gh release view "$tag" >/dev/null 2>&1; then
  info "release $tag exists -- replacing its kit files"
else
  pre=(); case "$version" in *-*) pre=(--prerelease) ;; esac
  gh release create "$tag" --target "$commit" --title "$version" --notes-file "$notes" ${pre[@]+"${pre[@]}"}
fi
git show "$commit:install.sh" > "$stage/install.sh" || die "install.sh isn't in $ref"
gh release upload "$tag" --clobber "$tarball" "$tarball.sha256" "$stage/install.sh"
info "published: https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/releases/tag/$tag"
