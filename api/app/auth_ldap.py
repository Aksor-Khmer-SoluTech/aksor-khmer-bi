"""AD/LDAP login: three bind strategies against a directory configured
per-organization (app/db.py's LdapConfig), verified end-to-end against a
real Dockerized OpenLDAP (no real Active Directory is reachable from
this environment -- see docs/deployment.md's LDAP section for how to run
one and what's verified against it vs. what only real AD can exercise).

Bind methods (LdapConfig.bind_method):

  direct_bind -- bind directly as `direct_bind_dn_template.format(...)`
                 (default "uid={username},{base_dn}") -- plain
                 LDAP/OpenLDAP convention, one round trip.

  search_bind -- bind as a service account (service_bind_dn +
                 service_bind_password_env) first, search for the user's
                 DN using user_search_filter, then re-bind as *that* DN
                 with the caller's password. The standard method for
                 real AD, since AD usernames aren't DNs and there's no
                 fixed template that finds them.

  upn_bind    -- bind directly as f"{username}@{upn_domain}" (AD's User
                 Principal Name shortcut). This is an Active-Directory-
                 specific bind convenience -- plain OpenLDAP has no
                 built-in translation from "user@domain" to a DN and
                 will simply reject it as a malformed bind DN, so this
                 method's *success* path can only be verified against
                 real AD; against the local OpenLDAP test server it's
                 verified to fail closed (not crash, not silently
                 succeed) rather than verified to succeed. Documented
                 here rather than glossed over.

On a successful bind, the user's group membership is resolved
(_lookup_groups: prefer a `memberOf` attribute on the bound entry itself,
which real AD always populates; fall back to a reverse `(member=<dn>)`
search under `group_search_base` for directories -- most plain OpenLDAP
setups -- that don't maintain memberOf without an extra overlay) and
synced into internal role grants via LdapConfig's
`ldap_group_role_mappings` (app/rbac.py's UserRoleAssignment, tagged
granted_by="ldap-sync" so it's distinguishable from a manually-granted
role and safe to reconcile automatically on every login: added when
newly a member of a mapped group, deactivated when no longer one, a
manually-granted assignment of the same role is never touched).

The group lookup runs on the just-authenticated *user's own* connection,
not a privileged service account -- fine on real AD (users can read
their own `memberOf` by default), but confirmed by hand while building
this out that plain OpenLDAP's stock ACL (osixia/openldap's default:
"by self read ... by * none") blocks a regular user from searching
*anything*, including `group_search_base` itself ("32 No such object",
not just an empty result). Deploying against plain OpenLDAP needs an ACL
that grants authenticated users read on the group subtree specifically
(`by users read` on `group_search_base`, not a blanket loosening) -- see
`api/tests/fixtures/ldap-acl.ldif` for the exact rule this project's own
test server runs with.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from ldap3 import BASE, Connection, Server
from ldap3.core.exceptions import LDAPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import LdapConfig, LdapGroupRoleMapping, User, UserRoleAssignment

_log = logging.getLogger("aksor_khmer_bi.auth_ldap")

LDAP_SYNC_TAG = "ldap-sync"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LdapBindResult:
    dn: str
    groups: list[str]


class LdapConfigError(Exception):
    """Raised for a misconfigured LdapConfig (e.g. a missing env var for
    the service-bind password) -- distinct from a bind failure, which
    just means "this credential didn't work," not "the server admin
    forgot a setting."
    """


def resolve_service_bind_password(config: LdapConfig) -> str:
    if not config.service_bind_password_env:
        raise LdapConfigError(f"LdapConfig {config.id!r}: service_bind_password_env is not set")
    value = os.environ.get(config.service_bind_password_env)
    if not value:
        raise LdapConfigError(
            f"LdapConfig {config.id!r}: environment variable {config.service_bind_password_env!r} is not set"
        )
    return value


def find_ldap_config(session: Session, org_id: str | None) -> LdapConfig | None:
    """Org-specific config takes priority; an org_id=None ("system
    default") config is used as a fallback for orgs that have none of
    their own -- lets a small deployment share one corporate directory
    across every tenant, or a larger one point specific orgs elsewhere.
    """
    if org_id is not None:
        org_config = session.execute(
            select(LdapConfig).where(LdapConfig.org_id == org_id, LdapConfig.is_enabled.is_(True))
        ).scalar_one_or_none()
        if org_config is not None:
            return org_config
    return session.execute(
        select(LdapConfig).where(LdapConfig.org_id.is_(None), LdapConfig.is_enabled.is_(True))
    ).scalar_one_or_none()


def _bind(server_uri: str, dn: str, password: str) -> Connection | None:
    """Attempt one bind; returns the bound Connection on success (caller
    must unbind it) or None on any failure -- wrong credentials, DN
    doesn't exist, malformed DN, network/protocol error. Every failure
    mode is deliberately collapsed to "this didn't work" here, same as a
    wrong password would look from the caller's side; the reason is
    logged, not surfaced to the login response (never help an attacker
    distinguish "no such user" from "wrong password").
    """
    try:
        server = Server(server_uri)
        conn = Connection(server, user=dn, password=password, auto_bind=False)
        if conn.bind():
            return conn
        _log.warning("LDAP bind failed for dn=%r: %s", dn, conn.result.get("description") if conn.result else "?")
        return None
    except LDAPException as exc:
        _log.warning("LDAP bind raised for dn=%r: %s", dn, exc)
        return None


def _lookup_groups(conn: Connection, user_dn: str, group_search_base: str) -> list[str]:
    """Prefer `memberOf` on the bound entry (real AD always maintains
    this natively); fall back to a reverse group-membership search for
    directories that don't (most plain OpenLDAP setups without the
    memberOf overlay configured).
    """
    try:
        if conn.search(search_base=user_dn, search_filter="(objectClass=*)", search_scope=BASE, attributes=["memberOf"]):
            entry = conn.entries[0] if conn.entries else None
            if entry is not None and "memberOf" in entry and entry["memberOf"].values:
                return [str(v) for v in entry["memberOf"].values]
    except LDAPException as exc:
        _log.warning("memberOf lookup failed for dn=%r: %s", user_dn, exc)

    try:
        group_filter = (
            f"(&(|(objectClass=groupOfNames)(objectClass=groupOfUniqueNames))"
            f"(|(member={user_dn})(uniqueMember={user_dn})))"
        )
        if conn.search(search_base=group_search_base, search_filter=group_filter, attributes=["cn"]):
            return [str(entry.entry_dn) for entry in conn.entries]
    except LDAPException as exc:
        _log.warning("reverse group search failed for dn=%r under %r: %s", user_dn, group_search_base, exc)

    return []


def authenticate(config: LdapConfig, username: str, password: str) -> LdapBindResult | None:
    """Dispatch to the configured bind method. Pure LDAP I/O -- no
    database access, so no `session` parameter. Returns None on any
    failure (wrong password, unknown user, misconfigured method) --
    LdapConfigError propagates instead for a genuine configuration
    mistake (missing service-bind password env var), since that's an
    admin problem, not a "this login attempt failed" outcome.
    """
    group_search_base = config.group_search_base or config.base_dn

    if config.bind_method == "direct_bind":
        template = config.direct_bind_dn_template or "uid={username},{base_dn}"
        user_dn = template.format(username=username, base_dn=config.base_dn)
        conn = _bind(config.server_uri, user_dn, password)
        if conn is None:
            return None
        groups = _lookup_groups(conn, user_dn, group_search_base)
        conn.unbind()
        return LdapBindResult(dn=user_dn, groups=groups)

    if config.bind_method == "search_bind":
        if not config.service_bind_dn or not config.user_search_filter:
            raise LdapConfigError(f"LdapConfig {config.id!r}: search_bind requires service_bind_dn and user_search_filter")
        service_password = resolve_service_bind_password(config)
        service_conn = _bind(config.server_uri, config.service_bind_dn, service_password)
        if service_conn is None:
            raise LdapConfigError(f"LdapConfig {config.id!r}: service bind account itself failed to authenticate")

        search_filter = config.user_search_filter.format(username=username)
        found = service_conn.search(search_base=config.base_dn, search_filter=search_filter, attributes=["cn"])
        if not found or not service_conn.entries:
            service_conn.unbind()
            return None
        user_dn = str(service_conn.entries[0].entry_dn)
        service_conn.unbind()

        user_conn = _bind(config.server_uri, user_dn, password)
        if user_conn is None:
            return None
        groups = _lookup_groups(user_conn, user_dn, group_search_base)
        user_conn.unbind()
        return LdapBindResult(dn=user_dn, groups=groups)

    if config.bind_method == "upn_bind":
        if not config.upn_domain:
            raise LdapConfigError(f"LdapConfig {config.id!r}: upn_bind requires upn_domain")
        user_dn = f"{username}@{config.upn_domain}"
        conn = _bind(config.server_uri, user_dn, password)
        if conn is None:
            return None
        groups = _lookup_groups(conn, user_dn, group_search_base)
        conn.unbind()
        return LdapBindResult(dn=user_dn, groups=groups)

    raise LdapConfigError(f"LdapConfig {config.id!r}: unknown bind_method {config.bind_method!r}")


def _sync_group_roles(session: Session, config: LdapConfig, user: User, groups: list[str]) -> None:
    """Reconcile `user`'s ldap-sync-tagged role assignments against their
    current group membership for this config: grant roles for groups
    they're newly in, deactivate ldap-sync grants for groups they've left.
    Manually-granted assignments (granted_by != "ldap-sync") of the same
    role are never touched -- e.g. a role given by an org admin directly
    survives even if the matching group later disappears from `groups`.
    """
    member_of = {g.strip().lower() for g in groups}

    mappings = session.execute(
        select(LdapGroupRoleMapping).where(LdapGroupRoleMapping.ldap_config_id == config.id)
    ).scalars().all()

    for mapping in mappings:
        is_member = mapping.group_dn.strip().lower() in member_of
        existing = session.execute(
            select(UserRoleAssignment).where(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.role_id == mapping.role_id,
                UserRoleAssignment.granted_by == LDAP_SYNC_TAG,
            )
        ).scalar_one_or_none()

        if is_member and (existing is None or not existing.is_active):
            if existing is not None:
                existing.is_active = True
                existing.expires_at = None
            else:
                session.add(
                    UserRoleAssignment(
                        user_id=user.id,
                        role_id=mapping.role_id,
                        granted_at=_now_iso(),
                        granted_by=LDAP_SYNC_TAG,
                        expires_at=None,
                        is_active=True,
                    )
                )
        elif not is_member and existing is not None and existing.is_active:
            existing.is_active = False


def attempt_ldap_login(session: Session, user: User, password: str) -> bool:
    """Top-level entry point called from auth.get_current_user for a
    User row with auth_source="ldap". Returns True and updates
    user.external_dn/last_login_at plus synced role grants on success;
    False on any failure (no config found, wrong password, unknown
    directory user). Does not raise LdapConfigError to the caller -- a
    misconfigured directory should present as "this login didn't work,"
    same as everything else in app/auth.py's fail-closed design, with
    the actual reason left in the log for an operator to find.
    """
    config = find_ldap_config(session, user.org_id)
    if config is None:
        _log.warning("No enabled LdapConfig found for org_id=%r (user=%r)", user.org_id, user.username)
        return False

    try:
        result = authenticate(config, user.username, password)
    except LdapConfigError as exc:
        _log.error("LDAP configuration error for org_id=%r: %s", user.org_id, exc)
        return False

    if result is None:
        return False

    user.external_dn = result.dn
    user.last_login_at = _now_iso()
    _sync_group_roles(session, config, user, result.groups)
    session.commit()
    return True
