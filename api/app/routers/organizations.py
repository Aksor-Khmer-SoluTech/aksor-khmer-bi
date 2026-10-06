"""Organization (tenant) management. Creating an org also seeds its
standard role catalog (app/rbac.py's seed_org_roles) in the same
transaction, so a newly-created org can immediately have users assigned
to real roles rather than existing in a role-less, unusable state.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit, db, rbac
from ..auth import get_current_user, require_permission
from ..models import OrganizationCreate, OrganizationOut
from ..rbac import AuthContext

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


def _row_to_out(row: db.Organization) -> OrganizationOut:
    return OrganizationOut(
        id=row.id, name=row.name, parent_org_id=row.parent_org_id, is_active=row.is_active, created_at=row.created_at
    )


@router.post(
    "",
    summary="Create a new organization (tenant)",
    response_model=OrganizationOut,
)
def create_organization(
    body: OrganizationCreate, request: Request, context: AuthContext = Depends(require_permission("org:manage"))
) -> OrganizationOut:
    with db.SessionLocal() as session:
        if session.get(db.Organization, body.id) is not None:
            raise HTTPException(status_code=409, detail=f"Organization '{body.id}' already exists")
        try:
            org = rbac.create_organization(session, body.id, body.name, body.parent_org_id)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail="Invalid organization (bad parent_org_id?)") from exc
        audit.record(
            audit.Actor.of(context, request), "organization.create", "organization", org.id,
            label=org.name, org_id=org.id, summary=f'Created organization "{org.name}" ({org.id})',
            details={"parent_org_id": org.parent_org_id},
        )
        return _row_to_out(org)


@router.get("", summary="List organizations", response_model=list[OrganizationOut])
def list_organizations(_: AuthContext = Depends(get_current_user)) -> list[OrganizationOut]:
    with db.SessionLocal() as session:
        rows = session.execute(select(db.Organization).order_by(db.Organization.id)).scalars().all()
        return [_row_to_out(row) for row in rows]


@router.get("/{org_id}", summary="Get one organization", response_model=OrganizationOut)
def get_organization(org_id: str, _: AuthContext = Depends(get_current_user)) -> OrganizationOut:
    with db.SessionLocal() as session:
        row = session.get(db.Organization, org_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return _row_to_out(row)
