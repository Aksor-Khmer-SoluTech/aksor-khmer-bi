"""LDAP/AD directory configuration management -- see app/auth_ldap.py for
the bind logic these rows drive, and app/db.py's LdapConfig/
LdapGroupRoleMapping for the schema. Gated by `settings:manage`
(app/rbac.py), org-scoped like the other admin routers.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from .. import audit, db
from ..auth import ensure_org_scope, require_permission
from ..auth_ldap import LdapConfigError, authenticate
from ..models import (
    LdapConfigCreate,
    LdapConfigOut,
    LdapConfigUpdate,
    LdapGroupMappingCreate,
    LdapGroupMappingOut,
    LdapTestRequest,
    LdapTestResult,
)
from ..rbac import AuthContext

router = APIRouter(prefix="/api/v1/ldap-configs", tags=["ldap"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_out(row: db.LdapConfig) -> LdapConfigOut:
    return LdapConfigOut(
        id=row.id,
        org_id=row.org_id,
        server_uri=row.server_uri,
        bind_method=row.bind_method,
        base_dn=row.base_dn,
        direct_bind_dn_template=row.direct_bind_dn_template,
        service_bind_dn=row.service_bind_dn,
        service_bind_password_env=row.service_bind_password_env,
        user_search_filter=row.user_search_filter,
        upn_domain=row.upn_domain,
        group_search_base=row.group_search_base,
        is_enabled=row.is_enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_AUDITED_FIELDS = (
    "server_uri",
    "bind_method",
    "base_dn",
    "direct_bind_dn_template",
    "service_bind_dn",
    "service_bind_password_env",
    "user_search_filter",
    "upn_domain",
    "group_search_base",
    "is_enabled",
)


def _snapshot(row: db.LdapConfig) -> dict:
    return {f: getattr(row, f) for f in _AUDITED_FIELDS}


def _label(row: db.LdapConfig) -> str:
    return row.server_uri


def _validate_method_fields(body: LdapConfigCreate | LdapConfigUpdate, bind_method: str) -> None:
    if bind_method == "search_bind" and not (body.service_bind_dn and body.user_search_filter):
        raise HTTPException(status_code=400, detail="search_bind requires service_bind_dn and user_search_filter")
    if bind_method == "upn_bind" and not body.upn_domain:
        raise HTTPException(status_code=400, detail="upn_bind requires upn_domain")


@router.post("", summary="Create an LDAP/AD directory configuration", response_model=LdapConfigOut)
def create_ldap_config(
    body: LdapConfigCreate,
    request: Request,
    org_id: str | None = Query(None, description="Omit for a system-wide default config (superuser only)"),
    context: AuthContext = Depends(require_permission("settings:manage")),
) -> LdapConfigOut:
    if org_id is None and not context.is_superuser:
        raise HTTPException(status_code=403, detail="Only a superuser can create a system-wide default LDAP config")
    if org_id is not None:
        ensure_org_scope(context, org_id)
    _validate_method_fields(body, body.bind_method)

    now = _now_iso()
    with db.SessionLocal() as session:
        if org_id is not None and session.get(db.Organization, org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        row = db.LdapConfig(
            org_id=org_id,
            server_uri=body.server_uri,
            bind_method=body.bind_method,
            base_dn=body.base_dn,
            direct_bind_dn_template=body.direct_bind_dn_template,
            service_bind_dn=body.service_bind_dn,
            service_bind_password_env=body.service_bind_password_env,
            user_search_filter=body.user_search_filter,
            upn_domain=body.upn_domain,
            group_search_base=body.group_search_base,
            is_enabled=body.is_enabled,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "ldap_config.create", "ldap_config", row.id,
            label=_label(row), org_id=row.org_id, summary=f"Created directory configuration for {row.server_uri}",
            details=_snapshot(row),
        )
        return _row_to_out(row)


@router.get("", summary="List LDAP configs", response_model=list[LdapConfigOut])
def list_ldap_configs(
    org_id: str | None = Query(None, description="Superusers may omit this to list every org's configs"),
    context: AuthContext = Depends(require_permission("settings:manage")),
) -> list[LdapConfigOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    with db.SessionLocal() as session:
        query = select(db.LdapConfig)
        if org_id is not None:
            query = query.where(db.LdapConfig.org_id == org_id)
        rows = session.execute(query).scalars().all()
        return [_row_to_out(row) for row in rows]


@router.get("/{config_id}", summary="Get one LDAP config", response_model=LdapConfigOut)
def get_ldap_config(config_id: str, context: AuthContext = Depends(require_permission("settings:manage"))) -> LdapConfigOut:
    with db.SessionLocal() as session:
        row = session.get(db.LdapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="LDAP config not found")
        if row.org_id is not None:
            ensure_org_scope(context, row.org_id)
        elif not context.is_superuser:
            raise HTTPException(status_code=404, detail="LDAP config not found")
        return _row_to_out(row)


@router.patch("/{config_id}", summary="Update an LDAP config", response_model=LdapConfigOut)
def update_ldap_config(
    config_id: str, body: LdapConfigUpdate, request: Request, context: AuthContext = Depends(require_permission("settings:manage"))
) -> LdapConfigOut:
    with db.SessionLocal() as session:
        row = session.get(db.LdapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="LDAP config not found")
        if row.org_id is not None:
            ensure_org_scope(context, row.org_id)
        elif not context.is_superuser:
            raise HTTPException(status_code=404, detail="LDAP config not found")

        before = _snapshot(row)
        for field in _AUDITED_FIELDS:
            value = getattr(body, field)
            if value is not None:
                setattr(row, field, value)

        _validate_method_fields(body, row.bind_method)
        row.updated_at = _now_iso()
        session.commit()
        # Where users are sent to prove who they are -- a changed server or
        # base DN is the edit an investigation most wants to be able to find.
        changes = audit.diff(before, _snapshot(row), list(_AUDITED_FIELDS))
        if changes:
            audit.record(
                audit.Actor.of(context, request), "ldap_config.update", "ldap_config", row.id,
                label=_label(row), org_id=row.org_id,
                summary="Changed directory configuration (" + ", ".join(c["field"] for c in changes) + ")",
                changes=changes,
            )
        return _row_to_out(row)


@router.delete("/{config_id}", status_code=204, summary="Delete an LDAP config")
def delete_ldap_config(
    config_id: str, request: Request, context: AuthContext = Depends(require_permission("settings:manage"))
) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.LdapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="LDAP config not found")
        if row.org_id is not None:
            ensure_org_scope(context, row.org_id)
        elif not context.is_superuser:
            raise HTTPException(status_code=404, detail="LDAP config not found")
        session.delete(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "ldap_config.delete", "ldap_config", config_id,
            label=_label(row), org_id=row.org_id, summary=f"Deleted directory configuration for {row.server_uri}",
            details=_snapshot(row),
        )


@router.post(
    "/{config_id}/test",
    summary="Test a bind against this config with a real username/password, without creating a user",
    response_model=LdapTestResult,
)
def test_ldap_config(
    config_id: str, body: LdapTestRequest, request: Request, context: AuthContext = Depends(require_permission("settings:manage"))
) -> LdapTestResult:
    with db.SessionLocal() as session:
        row = session.get(db.LdapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="LDAP config not found")
        if row.org_id is not None:
            ensure_org_scope(context, row.org_id)
        elif not context.is_superuser:
            raise HTTPException(status_code=404, detail="LDAP config not found")

        # Trying a real person's directory credentials is worth a record
        # whichever way it turns out -- the username, never the password.
        def _record(success: bool) -> None:
            audit.record(
                audit.Actor.of(context, request), "ldap_config.test", "ldap_config", row.id,
                label=_label(row), org_id=row.org_id,
                summary=f"Tested a directory bind as {body.username} ({'succeeded' if success else 'failed'})",
                details={"username": body.username, "success": success},
            )

        try:
            result = authenticate(row, body.username, body.password)
        except LdapConfigError as exc:
            _record(False)
            return LdapTestResult(success=False, detail=str(exc))

        if result is None:
            _record(False)
            return LdapTestResult(success=False, detail="Bind failed (wrong credentials or user not found)")
        _record(True)
        return LdapTestResult(success=True, dn=result.dn, groups=result.groups)


# --- group -> role mappings ------------------------------------------


@router.post(
    "/{config_id}/group-mappings",
    summary="Map a directory group to an internal role",
    response_model=LdapGroupMappingOut,
)
def create_group_mapping(
    config_id: str, body: LdapGroupMappingCreate, request: Request, context: AuthContext = Depends(require_permission("settings:manage"))
) -> LdapGroupMappingOut:
    with db.SessionLocal() as session:
        config = session.get(db.LdapConfig, config_id)
        if config is None:
            raise HTTPException(status_code=404, detail="LDAP config not found")
        if config.org_id is not None:
            ensure_org_scope(context, config.org_id)
        elif not context.is_superuser:
            raise HTTPException(status_code=404, detail="LDAP config not found")

        role = session.get(db.Role, body.role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        if role.org_id != config.org_id:
            raise HTTPException(status_code=400, detail="Role must belong to the same organization as the LDAP config")

        row = db.LdapGroupRoleMapping(ldap_config_id=config_id, group_dn=body.group_dn, role_id=body.role_id)
        session.add(row)
        session.commit()
        # Anyone in this directory group now gets this role at sign-in -- a
        # privilege assignment that no individual grant will ever show.
        audit.record(
            audit.Actor.of(context, request), "ldap_config.mapping_add", "ldap_config", config_id,
            label=_label(config), org_id=config.org_id,
            summary=f"Mapped directory group {row.group_dn} to role {role.name}",
            details={"mapping_id": row.id, "group_dn": row.group_dn, "role_id": role.id, "role_name": role.name},
        )
        return LdapGroupMappingOut(id=row.id, ldap_config_id=row.ldap_config_id, group_dn=row.group_dn, role_id=row.role_id)


@router.get(
    "/{config_id}/group-mappings", summary="List group->role mappings for a config", response_model=list[LdapGroupMappingOut]
)
def list_group_mappings(
    config_id: str, context: AuthContext = Depends(require_permission("settings:manage"))
) -> list[LdapGroupMappingOut]:
    with db.SessionLocal() as session:
        config = session.get(db.LdapConfig, config_id)
        if config is None:
            raise HTTPException(status_code=404, detail="LDAP config not found")
        if config.org_id is not None:
            ensure_org_scope(context, config.org_id)
        elif not context.is_superuser:
            raise HTTPException(status_code=404, detail="LDAP config not found")

        rows = session.execute(
            select(db.LdapGroupRoleMapping).where(db.LdapGroupRoleMapping.ldap_config_id == config_id)
        ).scalars().all()
        return [
            LdapGroupMappingOut(id=r.id, ldap_config_id=r.ldap_config_id, group_dn=r.group_dn, role_id=r.role_id)
            for r in rows
        ]


@router.delete("/{config_id}/group-mappings/{mapping_id}", status_code=204, summary="Remove a group->role mapping")
def delete_group_mapping(
    config_id: str, mapping_id: str, request: Request, context: AuthContext = Depends(require_permission("settings:manage"))
) -> None:
    with db.SessionLocal() as session:
        config = session.get(db.LdapConfig, config_id)
        if config is None:
            raise HTTPException(status_code=404, detail="LDAP config not found")
        if config.org_id is not None:
            ensure_org_scope(context, config.org_id)
        elif not context.is_superuser:
            raise HTTPException(status_code=404, detail="LDAP config not found")

        row = session.get(db.LdapGroupRoleMapping, mapping_id)
        if row is None or row.ldap_config_id != config_id:
            raise HTTPException(status_code=404, detail="Mapping not found")
        role = session.get(db.Role, row.role_id)
        session.delete(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "ldap_config.mapping_remove", "ldap_config", config_id,
            label=_label(config), org_id=config.org_id,
            summary=f"Removed mapping of directory group {row.group_dn} to role {role.name if role else row.role_id}",
            details={"mapping_id": row.id, "group_dn": row.group_dn, "role_id": row.role_id},
        )
