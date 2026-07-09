"""User data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def list_by_org(self, organization_id: uuid.UUID) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(User.organization_id == organization_id)
            .order_by(User.created_at.desc())
        )
        return list(result.scalars().all())
