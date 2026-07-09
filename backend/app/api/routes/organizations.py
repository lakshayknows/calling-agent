"""Organization endpoints (current org only in v1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import AuthContextDep, DBSession, require_role
from app.core.exceptions import NotFoundError
from app.models.enums import UserRole
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import OrganizationRead, OrganizationUpdate

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/me", response_model=OrganizationRead)
async def get_my_org(ctx: AuthContextDep, db: DBSession) -> OrganizationRead:
    org = await OrganizationRepository(db).get(ctx.organization_id)
    if not org:
        raise NotFoundError("Organization not found")
    return OrganizationRead.model_validate(org)


@router.patch(
    "/me",
    response_model=OrganizationRead,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def update_my_org(
    body: OrganizationUpdate, ctx: AuthContextDep, db: DBSession
) -> OrganizationRead:
    org = await OrganizationRepository(db).get(ctx.organization_id)
    if not org:
        raise NotFoundError("Organization not found")
    if body.name is not None:
        org.name = body.name
    await db.flush()
    return OrganizationRead.model_validate(org)
