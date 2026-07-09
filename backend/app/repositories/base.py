"""Generic async repository.

Encapsulates common data-access patterns so services never build raw queries
for trivial operations. Feature-specific repositories subclass this and add
domain queries (e.g. `get_by_email`). All list/get helpers are org-agnostic;
callers are responsible for tenant scoping (usually via a `where` clause or a
dedicated method).
"""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    async def list_where(self, *conditions: object) -> list[ModelT]:
        stmt = select(self.model)
        if conditions:
            stmt = stmt.where(*conditions)  # type: ignore[arg-type]
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
