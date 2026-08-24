"""
app/repositories/user_repository.py

Data-access layer for the users table.
All DB queries are isolated here — services never touch SQLAlchemy directly.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """Async CRUD repository for the User model."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        """Persist a new User. Flush so the DB assigns defaults (id, timestamps)."""
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def update(self, user: User) -> User:
        """Flush pending changes to a User and return the refreshed instance."""
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def deactivate(self, user: User) -> User:
        """Soft-delete: mark user as inactive instead of hard-deleting."""
        user.is_active = False
        return await self.update(user)

    async def get_all(self, skip: int = 0, limit: int = 100) -> list[User]:
        result = await self._session.execute(
            select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count_active_admins(self) -> int:
        from app.models.user import UserRole
        from sqlalchemy import func
        result = await self._session.execute(
            select(func.count(User.id)).where(
                User.role == UserRole.ADMIN,
                User.is_active == True
            )
        )
        return result.scalar_one_or_none() or 0
