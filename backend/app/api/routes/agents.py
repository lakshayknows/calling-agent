"""AI Agent endpoints: CRUD + text-chat preview."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import AuthContextDep, DBSession, SettingsDep
from app.providers.base import LLMMessage
from app.providers.llm.cerebras import CerebrasProvider
from app.schemas.agent import (
    AgentCreate,
    AgentPreviewRequest,
    AgentPreviewResponse,
    AgentRead,
    AgentUpdate,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentRead])
async def list_agents(ctx: AuthContextDep, db: DBSession) -> list[AgentRead]:
    agents = await AgentService(db).list_(ctx.organization_id)
    return [AgentRead.model_validate(a) for a in agents]


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate, ctx: AuthContextDep, db: DBSession
) -> AgentRead:
    agent = await AgentService(db).create(body, ctx.organization_id)
    return AgentRead.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: uuid.UUID, ctx: AuthContextDep, db: DBSession) -> AgentRead:
    agent = await AgentService(db).get(agent_id, ctx.organization_id)
    return AgentRead.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: uuid.UUID, body: AgentUpdate, ctx: AuthContextDep, db: DBSession
) -> AgentRead:
    agent = await AgentService(db).update(agent_id, body, ctx.organization_id)
    return AgentRead.model_validate(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, ctx: AuthContextDep, db: DBSession) -> None:
    await AgentService(db).delete(agent_id, ctx.organization_id)


@router.post("/{agent_id}/preview", response_model=AgentPreviewResponse)
async def preview_agent(
    agent_id: uuid.UUID,
    body: AgentPreviewRequest,
    ctx: AuthContextDep,
    db: DBSession,
    settings: SettingsDep,
) -> AgentPreviewResponse:
    """Run the agent's brain as a text chat — same LLM path a call uses, no phone."""
    agent = await AgentService(db).get(agent_id, ctx.organization_id)

    messages: list[LLMMessage] = []
    if agent.system_prompt:
        messages.append(LLMMessage(role="system", content=agent.system_prompt))
    for turn in body.history:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if content:
            messages.append(LLMMessage(role=role, content=content))
    messages.append(LLMMessage(role="user", content=body.message))

    provider = CerebrasProvider(settings)
    result = await provider.complete(
        messages, model=agent.llm_model, temperature=agent.temperature
    )
    return AgentPreviewResponse(reply=result.content, model=agent.llm_model, usage=result.usage)
