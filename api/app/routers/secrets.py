"""Secrets: named credentials a report's data source or a connection refers to
by name instead of an environment variable. See app/secrets.py for what a
secret is, how it's resolved, and the revoke/delete distinction.

Scoped to the caller's own organization unless the caller is a superuser,
the same model as routers/connections.py. Writing needs `secret:manage` --
distinct from `connection:manage`/`report:manage`, since holding either of
those only lets someone *pick* a secret to reference, not create, rotate or
revoke one. Reading the list (no values, ever) needs one of the three: a
connection or report author has to see which secrets exist to pick one.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit, db, secret_store, secrets
from ..auth import ensure_org_scope, get_current_user, require_permission
from ..models import SecretCreate, SecretOut, SecretRef, SecretRotate, SecretSummary, SecretUpdate
from ..rbac import ROOT_ORG_ID, AuthContext

router = APIRouter(prefix="/api/v1/secrets", tags=["secrets"])

_manage = require_permission("secret:manage")


def _require_view(context: AuthContext = Depends(get_current_user)) -> AuthContext:
    if context.has_permission("secret:manage") or context.has_permission("connection:manage") or context.has_permission(
        "report:manage"
    ):
        return context
    raise HTTPException(status_code=403, detail="Missing required permission: secret:manage, connection:manage or report:manage")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_scoped(session, secret_id: str, context: AuthContext) -> db.Secret:
    row = session.get(db.Secret, secret_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    ensure_org_scope(context, row.org_id)
    return row


def _refs(entries: list[dict]) -> list[SecretRef]:
    return [
        SecretRef(
            kind=e["kind"],
            name=e["name"],
            report_id=e.get("report_id"),
            code=e.get("code"),
            connection_id=e.get("connection_id"),
        )
        for e in entries
    ]


def _summary(row: db.Secret, used_by_count: int) -> SecretSummary:
    return SecretSummary(
        id=row.id, org_id=row.org_id, name=row.name, description=row.description, is_active=row.is_active,
        used_by_count=used_by_count, created_at=row.created_at, updated_at=row.updated_at,
    )


def _out(row: db.Secret, used_by: list[dict]) -> SecretOut:
    return SecretOut(**_summary(row, len(used_by)).model_dump(), used_by=_refs(used_by))


@router.post("", summary="Create a secret", response_model=SecretOut)
def create_secret(body: SecretCreate, request: Request, context: AuthContext = Depends(_manage)) -> SecretOut:
    org_id = body.org_id or context.org_id or ROOT_ORG_ID
    ensure_org_scope(context, org_id)
    try:
        name = secrets.validate_name(body.name)
        value = secrets.check_value(body.value.get_secret_value())
    except secrets.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        encrypted = secret_store.encrypt(value)
    except secret_store.SecretError as exc:
        raise HTTPException(status_code=500, detail=f"The secret can't be saved: {exc}") from exc

    now = _now()
    with db.SessionLocal() as session:
        if session.get(db.Organization, org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        row = db.Secret(
            org_id=org_id, name=name, description=(body.description or "").strip() or None,
            value_encrypted=encrypted, is_active=True, created_at=now, updated_at=now,
            created_by=context.user.id if context.user else None,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=f"A secret named {name!r} already exists in this organization") from exc
        audit.record(
            audit.Actor.of(context, request), "secret.create", "secret", row.id,
            label=row.name, org_id=row.org_id, summary=f"Created the credential {row.name!r}",
        )
        return _out(row, [])


@router.get("", summary="List secrets visible to the caller", response_model=list[SecretSummary])
def list_secrets(
    org_id: str | None = Query(None, description="Superusers may omit this to list every organization's secrets"),
    context: AuthContext = Depends(_require_view),
) -> list[SecretSummary]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    with db.SessionLocal() as session:
        query = select(db.Secret).order_by(db.Secret.name)
        if org_id is not None:
            query = query.where(db.Secret.org_id == org_id)
        rows = session.scalars(query).all()
        usage = {org: secrets.used_by(session, org) for org in {row.org_id for row in rows}}
        return [_summary(row, len(usage[row.org_id].get(row.name, []))) for row in rows]


@router.get("/{secret_id}", summary="Get one secret, with what refers to it -- never its value", response_model=SecretOut)
def get_secret(secret_id: str, context: AuthContext = Depends(_manage)) -> SecretOut:
    with db.SessionLocal() as session:
        row = _get_scoped(session, secret_id, context)
        return _out(row, secrets.used_by(session, row.org_id).get(row.name, []))


@router.post("/{secret_id}/rotate", summary="Replace a secret's value", response_model=SecretOut)
def rotate_secret(secret_id: str, body: SecretRotate, request: Request, context: AuthContext = Depends(_manage)) -> SecretOut:
    """Whatever already names this secret needs no change -- the next call
    that resolves it gets the new value, no restart."""
    try:
        value = secrets.check_value(body.value.get_secret_value())
    except secrets.DataConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        encrypted = secret_store.encrypt(value)
    except secret_store.SecretError as exc:
        raise HTTPException(status_code=500, detail=f"The secret can't be saved: {exc}") from exc

    with db.SessionLocal() as session:
        row = _get_scoped(session, secret_id, context)
        row.value_encrypted = encrypted
        row.updated_at = _now()
        session.commit()
        used_by = secrets.used_by(session, row.org_id).get(row.name, [])
        audit.record(
            audit.Actor.of(context, request), "secret.rotate", "secret", row.id,
            label=row.name, org_id=row.org_id,
            summary=f"Rotated the credential {row.name!r}"
            + (f" (used by {len(used_by)} report{'s' if len(used_by) != 1 else ''}/connection{'s' if len(used_by) != 1 else ''})" if used_by else ""),
        )
        return _out(row, used_by)


@router.patch("/{secret_id}", summary="Rename its description, or revoke/reactivate it", response_model=SecretOut)
def update_secret(secret_id: str, body: SecretUpdate, request: Request, context: AuthContext = Depends(_manage)) -> SecretOut:
    with db.SessionLocal() as session:
        row = _get_scoped(session, secret_id, context)
        before_active = row.is_active
        if body.description is not None:
            row.description = body.description.strip() or None
        if body.is_active is not None:
            row.is_active = body.is_active
        row.updated_at = _now()
        session.commit()
        used_by = secrets.used_by(session, row.org_id).get(row.name, [])
        if body.is_active is not None and body.is_active != before_active:
            audit.record(
                audit.Actor.of(context, request), "secret.revoke" if not row.is_active else "secret.reactivate",
                "secret", row.id, label=row.name, org_id=row.org_id,
                summary=(
                    f"Revoked the credential {row.name!r}"
                    + (f" -- still used by {len(used_by)} report{'s' if len(used_by) != 1 else ''}/connection{'s' if len(used_by) != 1 else ''}, which will now fail to run" if used_by and not row.is_active else "")
                ) if not row.is_active else f"Reactivated the credential {row.name!r}",
            )
        return _out(row, used_by)


@router.delete("/{secret_id}", status_code=204, summary="Delete a secret nothing refers to")
def delete_secret(secret_id: str, request: Request, context: AuthContext = Depends(_manage)) -> None:
    """Refused while a report or connection still names it: deleting it would
    break every one of those, so they have to be pointed elsewhere first --
    same posture as routers/connections.py's delete."""
    with db.SessionLocal() as session:
        row = _get_scoped(session, secret_id, context)
        used_by = secrets.used_by(session, row.org_id).get(row.name, [])
        if used_by:
            names = ", ".join(r["name"] for r in used_by[:5]) + (f" and {len(used_by) - 5} more" if len(used_by) > 5 else "")
            raise HTTPException(
                status_code=409,
                detail=f"{row.name!r} is still used by {len(used_by)} report{'s' if len(used_by) != 1 else ''}/connection{'s' if len(used_by) != 1 else ''} ({names}) -- point them at another credential first",
            )
        name, org_id = row.name, row.org_id
        session.delete(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "secret.delete", "secret", secret_id,
            label=name, org_id=org_id, summary=f"Deleted the credential {name!r}",
        )
