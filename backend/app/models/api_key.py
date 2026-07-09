"""API key model — programmatic org-scoped access for the public API.

We store only a SHA-256 hash of the key (keys are high-entropy, so a fast hash
is appropriate — bcrypt would needlessly slow every authenticated request). The
`prefix` is shown in the UI so users can identify a key without revealing it.
The plaintext key is returned exactly once, at creation time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class ApiKey(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "api_keys"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    hashed_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization: Mapped["Organization"] = relationship(back_populates="api_keys")
