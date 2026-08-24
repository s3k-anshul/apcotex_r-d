"""
app/db/seed.py

Database bootstrapping for default development users.
Ensures admin and user accounts exist without overwriting existing credentials.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

async def ensure_default_users(session: AsyncSession) -> None:
    """
    Idempotent bootstrap for development users.
    Creates 'admin' and 'user' if they do not exist.
    """
    repo = UserRepository(session)
    
    defaults = [
        {
            "username": "admin",
            "email": "admin@apcotex.test",
            "password": "admin123",
            "full_name": "System Administrator",
            "role": UserRole.ADMIN,
        },
        {
            "username": "user",
            "email": "user@apcotex.test",
            "password": "user123",
            "full_name": "Standard User",
            "role": UserRole.SCIENTIST,  # Mapped to 'USER' in UI
        }
    ]
    
    for default in defaults:
        # We need get_by_username which might not exist in UserRepository yet. Let's assume it exists or I'll add it.
        # Actually, let me check UserRepository first. If it doesn't exist I'll add it in the next step.
        existing = await repo.get_by_username(default["username"])
        if not existing:
            new_user = User(
                username=default["username"],
                email=default["email"],
                hashed_password=hash_password(default["password"]),
                full_name=default["full_name"],
                role=default["role"],
                is_active=True
            )
            session.add(new_user)
            try:
                await session.commit()
                logger.info("Created default user: %s", default['username'])
            except IntegrityError:
                await session.rollback()
                logger.warning("Default user %s already exists or conflict occurred.", default['username'])
        else:
            # Check if the existing user has a valid password hash (bcrypt or argon2)
            has_valid_hash = False
            if existing.hashed_password:
                if existing.hashed_password.startswith("$2") or existing.hashed_password.startswith("$argon2"):
                    has_valid_hash = True
            
            if not has_valid_hash:
                logger.warning("Existing user '%s' has an invalid password hash. Existing credentials were not overwritten.", default['username'])
            else:
                logger.info("Default user %s already exists. Skipping.", default['username'])
