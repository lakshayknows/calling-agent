"""Organization model — the tenant boundary.

Every domain row (users, agents, campaigns, calls, …) hangs off an
organization. All queries in services must be scoped by `organization_id` to
enforce multi-tenant isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.api_key import ApiKey
    from app.models.user import User


class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list["User"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
