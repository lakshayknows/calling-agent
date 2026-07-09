"""User management endpoints (scoped to the caller's organization)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import AuthContextDep, CurrentUser, DBSession, require_role
from app.models.enums import UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
async def list_users(ctx: AuthContextDep, db: DBSession) -> list[UserRead]:
    users = await UserService(db).list_org_users(ctx.organization_id)
    return [UserRead.model_validate(u) for u in users]


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def invite_user(
    body: UserCreate, ctx: AuthContextDep, db: DBSession
) -> UserRead:
    user = await UserService(db).create_in_org(body, ctx.organization_id)
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, ctx: AuthContextDep, db: DBSession) -> UserRead:
    user = await UserService(db).get_in_org(user_id, ctx.organization_id)
    return UserRead.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    ctx: AuthContextDep,
    current_user: CurrentUser,
    db: DBSession,
) -> UserRead:
    user = await UserService(db).update_in_org(
        user_id, body, organization_id=ctx.organization_id, acting_user=current_user
    )
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def delete_user(
    user_id: uuid.UUID,
    ctx: AuthContextDep,
    current_user: CurrentUser,
    db: DBSession,
) -> None:
    await UserService(db).delete_in_org(
        user_id, organization_id=ctx.organization_id, acting_user=current_user
    )
