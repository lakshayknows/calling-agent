"""API key lifecycle: create (returns plaintext once), list, revoke."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import generate_api_key
from app.models.api_key import ApiKey
from app.repositories.api_key import ApiKeyRepository


class ApiKeyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ApiKeyRepository(session)

    async def list_for_org(self, organization_id: uuid.UUID) -> list[ApiKey]:
        return await self.repo.list_by_org(organization_id)

    async def create(
        self, *, name: str, organization_id: uuid.UUID, created_by_user_id: uuid.UUID
    ) -> tuple[ApiKey, str]:
        plaintext, prefix, hashed = generate_api_key()
        api_key = ApiKey(
            name=name,
            prefix=prefix,
            hashed_key=hashed,
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
        )
        await self.repo.add(api_key)
        return api_key, plaintext

    async def revoke(self, key_id: uuid.UUID, *, organization_id: uuid.UUID) -> None:
        api_key = await self.repo.get(key_id)
        if not api_key or api_key.organization_id != organization_id:
            raise NotFoundError("API key not found")
        api_key.is_active = False
        await self.session.flush()
