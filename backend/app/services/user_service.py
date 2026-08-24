"""
app/services/user_service.py

Business logic for user-related operations.
Phase 2 will add create_user(), list_users(), update_role(), etc.
"""
import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.exceptions import NotFoundError

logger = logging.getLogger(__name__)


class UserService:
    """Handles user retrieval and management business logic."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)

    async def get_by_id(self, user_id: uuid.UUID) -> User:
        """
        Return a User by UUID.
        Raises NotFoundError if the user does not exist.
        """
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError(resource="User")
        return user

    async def get_by_email(self, email: str) -> User:
        """
        Return a User by email address.
        Raises NotFoundError if the user does not exist.
        """
        user = await self._repo.get_by_email(email)
        if user is None:
            raise NotFoundError(resource="User")
        return user

    async def get_all(self, skip: int = 0, limit: int = 100) -> list[User]:
        return await self._repo.get_all(skip=skip, limit=limit)

    async def create_user(self, data: "UserCreate") -> User:
        """Create a new user. Expects caller to handle RBAC."""
        from app.core.security import hash_password
        from app.utils.exceptions import ConflictError
        
        # Check duplicates
        existing_username = await self._repo.get_by_username(data.username)
        if existing_username:
            raise ConflictError(message="Username already exists")
            
        existing_email = await self._repo.get_by_email(data.email)
        if existing_email:
            raise ConflictError(message="Email already exists")

        new_user = User(
            username=data.username,
            email=data.email,
            full_name=data.full_name,
            hashed_password=hash_password(data.password),
            role=data.role,
            is_active=True
        )
        return await self._repo.create(new_user)

    async def change_password(self, user_id: uuid.UUID, new_password: str) -> User:
        """Change a user's password. Expects caller to handle RBAC."""
        from app.core.security import hash_password
        user = await self.get_by_id(user_id)
        user.hashed_password = hash_password(new_password)
        return await self._repo.update(user)

    async def deactivate_user(self, user_id: uuid.UUID) -> User:
        """Deactivate a user with last-admin protection."""
        from app.models.user import UserRole
        from app.utils.exceptions import ConflictError
        
        user = await self.get_by_id(user_id)
        
        # Self-protection / Last admin protection
        if user.role == UserRole.ADMIN and user.is_active:
            active_admins = await self._repo.count_active_admins()
            if active_admins <= 1:
                raise ConflictError(message="At least one active administrator is required.")
                
        return await self._repo.deactivate(user)
