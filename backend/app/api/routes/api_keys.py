"""API key management endpoints (admin+)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import AuthContextDep, CurrentUser, DBSession, require_role
from app.models.enums import UserRole
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from app.services.api_key_service import ApiKeyService

router = APIRouter(
    prefix="/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(ctx: AuthContextDep, db: DBSession) -> list[ApiKeyRead]:
    keys = await ApiKeyService(db).list_for_org(ctx.organization_id)
    return [ApiKeyRead.model_validate(k) for k in keys]


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate, ctx: AuthContextDep, current_user: CurrentUser, db: DBSession
) -> ApiKeyCreated:
    api_key, plaintext = await ApiKeyService(db).create(
        name=body.name,
        organization_id=ctx.organization_id,
        created_by_user_id=current_user.id,
    )
    return ApiKeyCreated(
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at,
        created_at=api_key.created_at,
        key=plaintext,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: uuid.UUID, ctx: AuthContextDep, db: DBSession) -> None:
    await ApiKeyService(db).revoke(key_id, organization_id=ctx.organization_id)
