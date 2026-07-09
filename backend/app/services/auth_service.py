"""Authentication service: registration, login, token refresh, logout.

Refresh tokens are tracked in Redis as an allowlist (`refresh:{jti}` -> user_id
with TTL = refresh lifetime). This gives us server-side revocation (logout) and
rotation (each refresh invalidates the previous jti) that stateless JWTs can't
provide alone.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User
from app.repositories.organization import OrganizationRepository
from app.repositories.user import UserRepository
from app.schemas.auth import TokenResponse

_REFRESH_KEY = "refresh:{jti}"


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return base or "org"


class AuthService:
    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.users = UserRepository(session)
        self.orgs = OrganizationRepository(session)

    # ---- registration ---------------------------------------------------
    async def register(
        self,
        *,
        organization_name: str,
        email: str,
        password: str,
        full_name: str | None,
    ) -> tuple[User, Organization, TokenResponse]:
        email = email.lower()
        if await self.users.get_by_email(email):
            raise ConflictError("A user with this email already exists")

        org = Organization(name=organization_name, slug=await self._unique_slug(organization_name))
        await self.orgs.add(org)

        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            organization_id=org.id,
            role=UserRole.OWNER,
        )
        await self.users.add(user)

        tokens = await self._issue_tokens(user)
        return user, org, tokens

    async def _unique_slug(self, name: str) -> str:
        base = _slugify(name)
        slug = base
        i = 1
        while await self.orgs.get_by_slug(slug):
            i += 1
            slug = f"{base}-{i}"
        return slug

    # ---- login ----------------------------------------------------------
    async def login(self, *, email: str, password: str) -> tuple[User, TokenResponse]:
        user = await self.users.get_by_email(email.lower())
        if not user or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password", code="invalid_credentials")
        if not user.is_active:
            raise UnauthorizedError("Account is disabled", code="account_disabled")

        user.last_login_at = datetime.now(UTC)
        await self.session.flush()
        tokens = await self._issue_tokens(user)
        return user, tokens

    # ---- refresh / logout ----------------------------------------------
    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(self.settings, refresh_token, expected_type=REFRESH_TOKEN_TYPE)
        jti = payload["jti"]
        user_id = payload["sub"]

        stored = await self.redis.get(_REFRESH_KEY.format(jti=jti))
        if stored != user_id:
            raise UnauthorizedError("Refresh token is no longer valid", code="invalid_token")

        # Rotate: invalidate the presented token before issuing a new pair.
        await self.redis.delete(_REFRESH_KEY.format(jti=jti))

        user = await self.users.get(uuid.UUID(user_id))
        if not user or not user.is_active:
            raise UnauthorizedError("Account is disabled", code="account_disabled")
        return await self._issue_tokens(user)

    async def logout(self, refresh_token: str) -> None:
        try:
            payload = decode_token(
                self.settings, refresh_token, expected_type=REFRESH_TOKEN_TYPE
            )
        except UnauthorizedError:
            return  # already invalid — nothing to revoke
        await self.redis.delete(_REFRESH_KEY.format(jti=payload["jti"]))

    # ---- helpers --------------------------------------------------------
    async def _issue_tokens(self, user: User) -> TokenResponse:
        access = create_access_token(
            self.settings,
            user_id=user.id,
            organization_id=user.organization_id,
            role=user.role.value,
        )
        refresh, jti = create_refresh_token(self.settings, user_id=user.id)
        await self.redis.set(
            _REFRESH_KEY.format(jti=jti),
            str(user.id),
            ex=self.settings.refresh_token_expire_days * 86400,
        )
        return TokenResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=self.settings.access_token_expire_minutes * 60,
        )
