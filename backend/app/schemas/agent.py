"""AI Agent request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    system_prompt: str = Field(default="", max_length=20000)
    greeting: str | None = Field(default=None, max_length=2000)
    llm_model: str = Field(default="openai/gpt-4o-mini", max_length=120)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    voice: str = Field(default="meera", max_length=60)
    language: str = Field(default="en-IN", max_length=16)
    max_call_duration_seconds: int = Field(default=300, ge=10, le=3600)
    interruptible: bool = True
    memory_enabled: bool = True
    tools: list[dict[str, Any]] = Field(default_factory=list)
    transfer_rules: dict[str, Any] = Field(default_factory=dict)
    end_call_rules: dict[str, Any] = Field(default_factory=dict)
    custom_variables: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    """All fields optional — partial update."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    system_prompt: str | None = Field(default=None, max_length=20000)
    greeting: str | None = Field(default=None, max_length=2000)
    llm_model: str | None = Field(default=None, max_length=120)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    voice: str | None = Field(default=None, max_length=60)
    language: str | None = Field(default=None, max_length=16)
    max_call_duration_seconds: int | None = Field(default=None, ge=10, le=3600)
    interruptible: bool | None = None
    memory_enabled: bool | None = None
    tools: list[dict[str, Any]] | None = None
    transfer_rules: dict[str, Any] | None = None
    end_call_rules: dict[str, Any] | None = None
    custom_variables: dict[str, Any] | None = None
    is_active: bool | None = None


class AgentRead(ORMModel, AgentBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AgentPreviewRequest(BaseModel):
    """Text-chat preview of how the agent would respond (no phone call)."""

    message: str = Field(min_length=1, max_length=4000)
    history: list[dict[str, str]] = Field(default_factory=list)


class AgentPreviewResponse(BaseModel):
    reply: str
    model: str
    # OpenRouter usage includes floats (cost) and nested dicts — keep it lenient.
    usage: dict[str, Any] = Field(default_factory=dict)
