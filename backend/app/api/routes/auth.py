"""Authentication endpoints: register, login, refresh, logout, me."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DBSession, RedisDep, SettingsDep
from app.schemas.auth import (
    AuthResult,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.organization import OrganizationRead
from app.schemas.user import UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResult, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, db: DBSession, redis: RedisDep, settings: SettingsDep
) -> AuthResult:
    service = AuthService(db, redis, settings)
    user, org, tokens = await service.register(
        organization_name=body.organization_name,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
    )
    return AuthResult(
        tokens=tokens,
        user=UserRead.model_validate(user),
        organization=OrganizationRead.model_validate(org),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, db: DBSession, redis: RedisDep, settings: SettingsDep
) -> TokenResponse:
    service = AuthService(db, redis, settings)
    _, tokens = await service.login(email=body.email, password=body.password)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, db: DBSession, redis: RedisDep, settings: SettingsDep
) -> TokenResponse:
    service = AuthService(db, redis, settings)
    return await service.refresh(body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest, db: DBSession, redis: RedisDep, settings: SettingsDep
) -> None:
    service = AuthService(db, redis, settings)
    await service.logout(body.refresh_token)


@router.get("/me", response_model=UserRead)
async def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)
