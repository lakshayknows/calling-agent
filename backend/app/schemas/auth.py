"""Authentication schemas: register, login, tokens, refresh."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.organization import OrganizationRead
from app.schemas.user import UserRead


class RegisterRequest(BaseModel):
    """Sign up: creates an organization and its first (owner) user."""

    organization_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access token lifetime in seconds


class AuthResult(BaseModel):
    """Returned by register — tokens plus the created principal/org."""

    tokens: TokenResponse
    user: UserRead
    organization: OrganizationRead
