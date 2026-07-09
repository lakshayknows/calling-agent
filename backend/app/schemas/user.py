"""User request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole
from app.schemas.common import ORMModel


class UserRead(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool
    organization_id: uuid.UUID
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    """Invite a user into the caller's organization."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = UserRole.MEMBER


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None
