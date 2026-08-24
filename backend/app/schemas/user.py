"""
app/schemas/user.py

Pydantic models for user serialisation and creation.
UserOut is the safe public representation (no hashed_password).
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class UserOut(BaseModel):
    """
    Public user representation returned by GET /api/v1/users/me.
    Never exposes hashed_password.
    """

    id: uuid.UUID
    username: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    """
    Payload for creating a new user (admin-only, Phase 2).
    Included here as a foundation for the admin user management API.
    """

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1, max_length=255)
    role: UserRole = UserRole.SCIENTIST


class UserUpdatePassword(BaseModel):
    password: str = Field(..., min_length=8)
