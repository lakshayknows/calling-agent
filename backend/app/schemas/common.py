"""Shared schema base and helpers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Base for response models read from SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True)
