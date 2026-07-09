"""FastAPI dependency-injection helpers.

Shared singletons (Database, Redis) live on `app.state`, created during lifespan
startup. Auth resolves a request into an `AuthContext` from EITHER a JWT bearer
token (a human user) OR an `X-API-Key` header (programmatic org access), so
every protected route works with both without extra code.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import ACCESS_TOKEN_TYPE, decode_token, hash_api_key
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.api_key import ApiKeyRepository
from app.repositories.user import UserRepository


# --------------------------------------------------------------------------- #
# Datastores
# --------------------------------------------------------------------------- #
def get_db_container(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]


async def get_db(
    db: Annotated[Database, Depends(get_db_container)],
) -> AsyncGenerator[AsyncSession, None]:
    async for session in db.session():
        yield session


def get_redis(request: Request) -> Redis:
    return request.app.state.redis  # type: ignore[no-any-return]


SettingsDep = Annotated[Settings, Depends(get_settings)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class AuthContext:
    """Resolved principal for a request.

    `user` is None for API-key (service) principals. `organization_id` and
    `role` are always present and drive tenant scoping + RBAC.
    """

    organization_id: uuid.UUID
    role: UserRole
    user: User | None = None


_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_auth_context(
    db: DBSession,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    api_key: Annotated[str | None, Depends(_api_key_header)] = None,
) -> AuthContext:
    if api_key:
        return await _resolve_api_key(db, api_key)
    if credentials:
        return await _resolve_bearer(db, settings, credentials.credentials)
    raise UnauthorizedError("Not authenticated", code="not_authenticated")


async def _resolve_bearer(
    db: AsyncSession, settings: Settings, token: str
) -> AuthContext:
    payload = decode_token(settings, token, expected_type=ACCESS_TOKEN_TYPE)
    user = await UserRepository(db).get(uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise UnauthorizedError("Account is disabled", code="account_disabled")
    return AuthContext(organization_id=user.organization_id, role=user.role, user=user)


async def _resolve_api_key(db: AsyncSession, raw_key: str) -> AuthContext:
    repo = ApiKeyRepository(db)
    api_key = await repo.get_by_hash(hash_api_key(raw_key))
    if not api_key or not api_key.is_active:
        raise UnauthorizedError("Invalid API key", code="invalid_api_key")
    api_key.last_used_at = datetime.now(UTC)
    await db.flush()
    # Service principals act with ADMIN authority (cannot perform owner-only ops).
    return AuthContext(organization_id=api_key.organization_id, role=UserRole.ADMIN)


AuthContextDep = Annotated[AuthContext, Depends(get_auth_context)]


async def get_current_user(ctx: AuthContextDep) -> User:
    """Require a human user (rejects API-key principals)."""
    if ctx.user is None:
        raise ForbiddenError("This endpoint requires a user session, not an API key")
    return ctx.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(minimum: UserRole):  # noqa: ANN201 - returns a dependency
    """Dependency factory enforcing a minimum role (owner > admin > member)."""

    async def _guard(ctx: AuthContextDep) -> AuthContext:
        if ctx.role.rank < minimum.rank:
            raise ForbiddenError(f"Requires {minimum.value} role or higher")
        return ctx

    return _guard
