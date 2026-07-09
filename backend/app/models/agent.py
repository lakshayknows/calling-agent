"""AI Agent model — the configurable "brain" of a call.

Holds everything the call engine needs to run a conversation: the system
prompt, greeting, LLM model + temperature, voice/language for speech, and
behavioural rules (interruptions, transfer, end-of-call, tools, memory,
custom variables). Flexible/nested settings are stored as JSONB so the shape
can evolve without a migration per field.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class Agent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "agents"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    greeting: Mapped[str | None] = mapped_column(Text, nullable=True)

    llm_model: Mapped[str] = mapped_column(
        String(120), nullable=False, default="openai/gpt-4o-mini"
    )
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)

    voice: Mapped[str] = mapped_column(String(60), nullable=False, default="meera")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en-IN")

    max_call_duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300
    )
    interruptible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    transfer_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    end_call_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    custom_variables: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    organization: Mapped["Organization"] = relationship()
