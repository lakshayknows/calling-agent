"""Shared enums used across models and schemas."""

from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    """Role of a user within their organization (RBAC).

    Ordering (owner > admin > member) is used by `require_role` to allow a
    higher role to satisfy a lower requirement.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"

    @property
    def rank(self) -> int:
        return {"owner": 3, "admin": 2, "member": 1}[self.value]
