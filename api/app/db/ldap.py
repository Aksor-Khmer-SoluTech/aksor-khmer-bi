"""AD/LDAP login (Phase 2) -- see app/auth_ldap.py for the bind logic
that reads these. A `User` row with auth_source="ldap" has no
password_hash at all; its credential is verified against whichever
LdapConfig applies to its org at login time instead.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class LdapConfig(Base):
    """One directory configuration. `org_id` NULL means "system default" --
    consulted when a user's own org has no config of its own, since a
    small deployment may have exactly one corporate AD shared by every
    tenant, while a larger one can point different orgs at different
    directories (LdapConfig.org_id is the point of departure for that).

    `service_bind_password_env` is the *name* of an environment variable
    the real secret lives in, never the secret itself -- same pattern as
    this project's existing PORTAL_PASSWORD (see app/auth.py) rather than
    a new "store credentials in the app database" precedent.
    """

    __tablename__ = "ldap_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    server_uri: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "ldap://dc.corp.example.com:389"
    # "direct_bind" | "search_bind" | "upn_bind" -- see app/auth_ldap.py's module docstring.
    bind_method: Mapped[str] = mapped_column(String, nullable=False)
    base_dn: Mapped[str] = mapped_column(String, nullable=False)
    # direct_bind: e.g. "uid={username},{base_dn}" (OpenLDAP-style default).
    direct_bind_dn_template: Mapped[str | None] = mapped_column(String, nullable=True)
    # search_bind only: the service account that looks the user's DN up
    # before re-binding as them.
    service_bind_dn: Mapped[str | None] = mapped_column(String, nullable=True)
    service_bind_password_env: Mapped[str | None] = mapped_column(String, nullable=True)
    user_search_filter: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "(sAMAccountName={username})"
    # upn_bind only: the part after "@" -- bind DN becomes f"{username}@{upn_domain}".
    upn_domain: Mapped[str | None] = mapped_column(String, nullable=True)
    # Where to reverse-search "(member={user_dn})" for group membership
    # when the bound entry has no memberOf attribute of its own (real AD
    # always does; plain OpenLDAP generally doesn't without an overlay --
    # see auth_ldap.py's _lookup_groups). Defaults to base_dn if unset.
    group_search_base: Mapped[str | None] = mapped_column(String, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class LdapGroupRoleMapping(Base):
    """One directory group -> one internal role. On successful bind,
    every mapping for that config whose `group_dn` appears in the user's
    resolved group membership is synced into a non-expiring
    UserRoleAssignment tagged granted_by="ldap-sync" (app/auth_ldap.py) --
    added when newly a member, deactivated when no longer one, and never
    touching a manually-granted assignment of the same role.
    """

    __tablename__ = "ldap_group_role_mappings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    ldap_config_id: Mapped[str] = mapped_column(ForeignKey("ldap_configs.id"), nullable=False)
    group_dn: Mapped[str] = mapped_column(String, nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)
