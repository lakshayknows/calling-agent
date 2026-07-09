"""User management within an organization (invite, list, update, deactivate)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def list_org_users(self, organization_id: uuid.UUID) -> list[User]:
        return await self.users.list_by_org(organization_id)

    async def get_in_org(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> User:
        user = await self.users.get(user_id)
        if not user or user.organization_id != organization_id:
            raise NotFoundError("User not found")
        return user

    async def create_in_org(self, data: UserCreate, organization_id: uuid.UUID) -> User:
        if await self.users.get_by_email(data.email.lower()):
            raise ConflictError("A user with this email already exists")
        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
            organization_id=organization_id,
        )
        return await self.users.add(user)

    async def update_in_org(
        self,
        user_id: uuid.UUID,
        data: UserUpdate,
        *,
        organization_id: uuid.UUID,
        acting_user: User,
    ) -> User:
        user = await self.get_in_org(user_id, organization_id)

        # Only an owner may change roles or touch another owner.
        if data.role is not None or user.role == UserRole.OWNER:
            if acting_user.role != UserRole.OWNER:
                raise ForbiddenError("Only the owner can change roles")

        if data.full_name is not None:
            user.full_name = data.full_name
        if data.role is not None:
            user.role = data.role
        if data.is_active is not None:
            user.is_active = data.is_active
        await self.session.flush()
        return user

    async def delete_in_org(
        self, user_id: uuid.UUID, *, organization_id: uuid.UUID, acting_user: User
    ) -> None:
        user = await self.get_in_org(user_id, organization_id)
        if user.id == acting_user.id:
            raise ForbiddenError("You cannot delete your own account")
        if user.role == UserRole.OWNER:
            raise ForbiddenError("The organization owner cannot be deleted")
        await self.users.delete(user)
