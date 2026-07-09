"""API key data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.api_key import ApiKey
from app.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    model = ApiKey

    async def get_by_hash(self, hashed_key: str) -> ApiKey | None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.hashed_key == hashed_key)
        )
        return result.scalar_one_or_none()

    async def list_by_org(self, organization_id: uuid.UUID) -> list[ApiKey]:
        result = await self.session.execute(
            select(ApiKey)
            .where(ApiKey.organization_id == organization_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())
