"""
app/api/v1/users.py

User endpoints:
  GET /api/v1/users/me → current authenticated user profile
"""
from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.user import UserOut

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.get(
    "/me",
    response_model=SuccessResponse[UserOut],
    summary="Get current user profile",
    description="Returns the profile of the currently authenticated user. Requires Bearer token.",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[UserOut]:
    return SuccessResponse(data=UserOut.model_validate(current_user))


# ── Admin User Management ──────────────────────────────────────────────────

from typing import List
import uuid
from app.dependencies.auth import require_role
from app.models.user import UserRole
from app.schemas.user import UserCreate, UserUpdatePassword
from app.services.user_service import UserService
from app.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Body

@router.get(
    "",
    response_model=SuccessResponse[List[UserOut]],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="List users (Admin)",
)
async def list_users(
    skip: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db)
) -> SuccessResponse[List[UserOut]]:
    svc = UserService(session)
    users = await svc.get_all(skip, limit)
    return SuccessResponse(data=[UserOut.model_validate(u) for u in users])


@router.post(
    "",
    response_model=SuccessResponse[UserOut],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Create a new user (Admin)",
)
async def create_user(
    data: UserCreate,
    session: AsyncSession = Depends(get_db)
) -> SuccessResponse[UserOut]:
    svc = UserService(session)
    new_user = await svc.create_user(data)
    return SuccessResponse(data=UserOut.model_validate(new_user))


@router.patch(
    "/{user_id}/password",
    response_model=SuccessResponse[UserOut],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Change user password (Admin)",
)
async def change_password(
    user_id: uuid.UUID,
    data: UserUpdatePassword,
    session: AsyncSession = Depends(get_db)
) -> SuccessResponse[UserOut]:
    svc = UserService(session)
    updated_user = await svc.change_password(user_id, data.password)
    return SuccessResponse(data=UserOut.model_validate(updated_user))


@router.delete(
    "/{user_id}",
    response_model=SuccessResponse[UserOut],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Deactivate user (Admin)",
)
async def deactivate_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db)
) -> SuccessResponse[UserOut]:
    svc = UserService(session)
    deactivated_user = await svc.deactivate_user(user_id)
    return SuccessResponse(data=UserOut.model_validate(deactivated_user))
