"""CRUD for named, reusable, org-scoped Khmer protected term sets (see
app/db/protected_terms.py's module docstring and
specs/protected_terms_design.md). A report selects sets into its own
protected-terms-config by id (see routers/reports.py's
/{report_id}/protected-terms-config) -- this router is only the
library/CRUD side, same split routers/images.py has from
context_media.py.

Auth: creating/editing/deleting a set needs `protected_terms:manage` --
deliberately narrower than `report:manage`, since a set can affect every
report in the org that selects it (higher blast radius than one report's
own config). Listing/reading needs either that or `report:manage`: a
report author has to be able to see what sets exist to select one,
without needing edit rights over them.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import audit, db, protected_term_sets_store
from ..auth import ensure_org_scope, get_current_user, require_permission
from ..models import DeploymentProtectedTermsOut, ProtectedTermSetCreate, ProtectedTermSetOut, ProtectedTermSetUpdate
from ..protected_terms_config import ProtectedTermsConfigError, validate_term_set_fields
from ..rbac import AuthContext

router = APIRouter(prefix="/api/v1/protected-term-sets", tags=["protected-term-sets"])


def _require_view(context: AuthContext = Depends(get_current_user)) -> AuthContext:
    if context.has_permission("protected_terms:manage") or context.has_permission("report:manage"):
        return context
    raise HTTPException(status_code=403, detail="Missing required permission: protected_terms:manage or report:manage")


@router.post("", summary="Create a protected term set", response_model=ProtectedTermSetOut)
def create_term_set(
    body: ProtectedTermSetCreate, request: Request, context: AuthContext = Depends(require_permission("protected_terms:manage"))
) -> ProtectedTermSetOut:
    ensure_org_scope(context, body.org_id)
    try:
        cleaned = validate_term_set_fields(body.name, body.description, body.terms, body.exclude_terms)
    except ProtectedTermsConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    created = protected_term_sets_store.create_set(
        org_id=body.org_id,
        created_by=context.user.id if context.user else None,
        **cleaned,
    )
    audit.record(
        audit.Actor.of(context, request), "protected_term_set.create", "protected_term_set", created["id"],
        label=created["name"], org_id=created["org_id"],
        summary=f'Created protected term set "{created["name"]}" ({len(created["terms"])} terms, {len(created["exclude_terms"])} exclusions)',
        details={"term_count": len(created["terms"]), "exclude_count": len(created["exclude_terms"])},
    )
    return ProtectedTermSetOut(**created)


@router.get("", summary="List protected term sets visible to the caller", response_model=list[ProtectedTermSetOut])
def list_term_sets(
    org_id: str | None = Query(None, description="Superusers may omit this to list every org's sets"),
    context: AuthContext = Depends(_require_view),
) -> list[ProtectedTermSetOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id
    return [ProtectedTermSetOut(**row) for row in protected_term_sets_store.list_sets(org_id=org_id)]


@router.get(
    "/deployment-floor",
    summary="The deployment-wide protected-terms floor, as last synced from mounted config files",
    response_model=DeploymentProtectedTermsOut,
)
def get_deployment_floor(context: AuthContext = Depends(_require_view)) -> DeploymentProtectedTermsOut:
    """Registered ABOVE /{set_id} on purpose -- FastAPI/Starlette match
    routes in registration order, so a literal path after a `/{set_id}`
    route would be swallowed as if "deployment-floor" were a set id."""
    with db.SessionLocal() as session:
        row = session.get(db.DeploymentProtectedTerms, "default")
        if row is None:
            raise HTTPException(status_code=404, detail="Not synced yet — this shouldn't happen after a normal boot")
        return DeploymentProtectedTermsOut(
            id=row.id,
            version=row.version,
            terms=row.terms,
            exclude_terms=row.exclude_terms,
            source_paths=row.source_paths,
            synced_at=row.synced_at,
        )


@router.get("/{set_id}", summary="Get one protected term set", response_model=ProtectedTermSetOut)
def get_term_set(set_id: str, context: AuthContext = Depends(_require_view)) -> ProtectedTermSetOut:
    try:
        row = protected_term_sets_store.get_set(set_id)
    except protected_term_sets_store.ProtectedTermSetNotFoundError:
        raise HTTPException(status_code=404, detail="Protected term set not found")
    ensure_org_scope(context, row["org_id"])
    return ProtectedTermSetOut(**row)


@router.put("/{set_id}", summary="Replace a protected term set's fields", response_model=ProtectedTermSetOut)
def update_term_set(
    set_id: str, body: ProtectedTermSetUpdate, request: Request, context: AuthContext = Depends(require_permission("protected_terms:manage"))
) -> ProtectedTermSetOut:
    try:
        existing = protected_term_sets_store.get_set(set_id)
    except protected_term_sets_store.ProtectedTermSetNotFoundError:
        raise HTTPException(status_code=404, detail="Protected term set not found")
    ensure_org_scope(context, existing["org_id"])
    try:
        cleaned = validate_term_set_fields(body.name, body.description, body.terms, body.exclude_terms)
    except ProtectedTermsConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = protected_term_sets_store.update_set(set_id, **cleaned)
    # A set can change how every report that selects it breaks Khmer lines,
    # so the added/removed terms themselves are what's kept, not just "edited".
    changes = audit.diff(existing, updated, ["name", "description", "terms", "exclude_terms"])
    if changes:
        audit.record(
            audit.Actor.of(context, request), "protected_term_set.update", "protected_term_set", set_id,
            label=updated["name"], org_id=updated["org_id"],
            summary=f'Updated protected term set "{updated["name"]}" (' + ", ".join(c["field"].replace("_", " ") for c in changes) + ")",
            changes=changes,
        )
    return ProtectedTermSetOut(**updated)


@router.delete("/{set_id}", status_code=204, summary="Delete a protected term set")
def delete_term_set(
    set_id: str, request: Request, context: AuthContext = Depends(require_permission("protected_terms:manage"))
) -> None:
    """Any report still selecting this set just stops getting its terms
    on the next render (fail-soft -- see
    protected_terms_config.resolve_protected_terms), not blocked here."""
    try:
        existing = protected_term_sets_store.get_set(set_id)
    except protected_term_sets_store.ProtectedTermSetNotFoundError:
        raise HTTPException(status_code=404, detail="Protected term set not found")
    ensure_org_scope(context, existing["org_id"])
    protected_term_sets_store.delete_set(set_id)
    audit.record(
        audit.Actor.of(context, request), "protected_term_set.delete", "protected_term_set", set_id,
        label=existing["name"], org_id=existing["org_id"], summary=f'Deleted protected term set "{existing["name"]}"',
        details={"terms": existing["terms"][:100], "term_count": len(existing["terms"]), "exclude_terms": existing["exclude_terms"][:100]},
    )
