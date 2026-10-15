#!/bin/sh
# The portal's runtime settings (config.js), decided at every container start -- nginx runs each script in
# /docker-entrypoint.d/ before it serves. So a server needs no copy of the repository to configure the portal:
#
#   1. /aksor-config/config.js (docker-compose.yml mounts ./config/portal there), when it exists, is used as it is.
#   2. Otherwise the image's own default (config.default.js) is used, with every PORTAL_* variable that is set
#      (PORTAL_API_BASE_URL, PORTAL_BRAND_NAME, ...; docker-compose.yml passes them on from .env) written after it.
#
# A config.js bind-mounted straight onto the served file (the old docker-compose.yml did that) is read-only here;
# it is left alone, so older compose files keep working with this image.
set -eu

html=/usr/share/nginx/html
target="$html/config.js"
custom=/aksor-config/config.js
keys="API_BASE_URL BRAND_NAME BRAND_MARK PRODUCT_NAME TAGLINE DESCRIPTION LOGO_URL LICENSE_NAME REPO_URL DATE_FORMAT TIME_FORMAT DATETIME_FORMAT"

# Opening it to append nothing (in a subshell: a failed redirection would end this script): `[ -w ]` says yes to
# root even on a read-only mount.
if ! (: >> "$target") 2>/dev/null; then
  echo "aksor: $target is mounted read-only -- serving it as it is"
  exit 0
fi

if [ -f "$custom" ]; then
  cp "$custom" "$target"
  echo "aksor: config.js from $custom"
  exit 0
fi

tmp="$target.tmp"
cp "$html/config.default.js" "$tmp"
set_keys=""
for key in $keys; do
  value="$(printenv "PORTAL_$key" || true)"
  [ -n "$value" ] || continue
  # A JavaScript string: backslashes and double quotes escaped, line breaks dropped.
  escaped="$(printf '%s' "$value" | tr -d '\r\n' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's#</#<\\/#g')"
  printf 'window.PORTAL_%s = "%s";\n' "$key" "$escaped" >> "$tmp"
  set_keys="$set_keys $key"
done
mv "$tmp" "$target"
echo "aksor: config.js = the image's default${set_keys:+, with PORTAL_*:$set_keys}"
