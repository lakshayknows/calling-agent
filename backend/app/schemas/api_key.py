"""API key schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ApiKeyRead(ORMModel):
    id: uuid.UUID
    name: str
    prefix: str
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """Returned once on creation — includes the plaintext key."""

    key: str
