"""Model registry.

Import every model here so `Base.metadata` is fully populated for Alembic
autogenerate and runtime relationships.
"""

from app.models.agent import Agent
from app.models.api_key import ApiKey
from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User

__all__ = [
    "Agent",
    "ApiKey",
    "Base",
    "Organization",
    "TimestampMixin",
    "UUIDMixin",
    "User",
    "UserRole",
]
