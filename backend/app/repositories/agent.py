"""AI Agent data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.agent import Agent
from app.repositories.base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    model = Agent

    async def get_in_org(self, agent_id: uuid.UUID, organization_id: uuid.UUID) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(
                Agent.id == agent_id, Agent.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_org(self, organization_id: uuid.UUID) -> list[Agent]:
        result = await self.session.execute(
            select(Agent)
            .where(Agent.organization_id == organization_id)
            .order_by(Agent.created_at.desc())
        )
        return list(result.scalars().all())
