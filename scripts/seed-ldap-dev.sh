#!/bin/sh
# Seeds the throwaway OpenLDAP container from docker-compose.ldap-dev.yml
# with test users/groups and the group-read ACL app/auth_ldap.py needs
# (see api/tests/fixtures/ldap-*.ldif for what and why). Idempotent
# against a fresh container; re-running against an already-seeded one
# will just report "Already exists" for the LDIF entries, harmless.
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="$(docker compose -f "$REPO_ROOT/docker-compose.yml" -f "$REPO_ROOT/docker-compose.ldap-dev.yml" ps -q openldap)"

if [ -z "$CONTAINER" ]; then
  echo "openldap service isn't running -- start it first:" >&2
  echo "  docker compose -f docker-compose.yml -f docker-compose.ldap-dev.yml up -d openldap" >&2
  exit 1
fi

echo "Waiting for slapd to accept connections..."
for i in $(seq 1 30); do
  docker exec "$CONTAINER" ldapsearch -x -H ldap://localhost -b "dc=aksor,dc=test" \
    -D "cn=admin,dc=aksor,dc=test" -w adminpass123 >/dev/null 2>&1 && break
  sleep 1
done

docker cp "$REPO_ROOT/api/tests/fixtures/ldap-seed.ldif" "$CONTAINER:/tmp/seed.ldif"
docker exec "$CONTAINER" ldapadd -c -x -H ldap://localhost \
  -D "cn=admin,dc=aksor,dc=test" -w adminpass123 -f /tmp/seed.ldif

docker cp "$REPO_ROOT/api/tests/fixtures/ldap-acl.ldif" "$CONTAINER:/tmp/acl.ldif"
docker exec "$CONTAINER" ldapmodify -Y EXTERNAL -H ldapi:/// -f /tmp/acl.ldif

echo "Seeded. Try: LDAP_TEST_URI=ldap://localhost:3389 python -m pytest api/tests -k ldap -v"
