"""Organization request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OrganizationRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
