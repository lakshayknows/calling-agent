"""AI Agent CRUD, scoped to an organization."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.agent import Agent
from app.repositories.agent import AgentRepository
from app.schemas.agent import AgentCreate, AgentUpdate


class AgentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AgentRepository(session)

    async def list_(self, organization_id: uuid.UUID) -> list[Agent]:
        return await self.repo.list_by_org(organization_id)

    async def get(self, agent_id: uuid.UUID, organization_id: uuid.UUID) -> Agent:
        agent = await self.repo.get_in_org(agent_id, organization_id)
        if not agent:
            raise NotFoundError("Agent not found")
        return agent

    async def create(self, data: AgentCreate, organization_id: uuid.UUID) -> Agent:
        agent = Agent(organization_id=organization_id, **data.model_dump())
        return await self.repo.add(agent)

    async def update(
        self, agent_id: uuid.UUID, data: AgentUpdate, organization_id: uuid.UUID
    ) -> Agent:
        agent = await self.get(agent_id, organization_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(agent, field, value)
        await self.session.flush()
        return agent

    async def delete(self, agent_id: uuid.UUID, organization_id: uuid.UUID) -> None:
        agent = await self.get(agent_id, organization_id)
        await self.repo.delete(agent)
