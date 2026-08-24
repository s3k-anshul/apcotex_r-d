"""
app/services/auth_service.py

Business logic for authentication: login and token refresh.
No routes, no ORM queries — only orchestration between repository and security utils.
"""
import uuid
import logging

from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_actions import AuditAction, AuditEntityType
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
    hash_password,
    needs_upgrade,
)
from app.repositories.user_repository import UserRepository
from app.schemas.auth import AccessTokenResponse, LoginRequest, TokenResponse
from app.services.audit_service import AuditService
from app.utils.exceptions import InvalidCredentialsError, InvalidTokenError

logger = logging.getLogger(__name__)


class AuthService:
    """Handles login and token-refresh business logic."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)
        self._audit_service = AuditService(session)

    async def login(self, credentials: LoginRequest) -> TokenResponse:
        """
        Validate credentials and return an access + refresh token pair.
        Raises InvalidCredentialsError on bad username, wrong password, or inactive account.
        """
        user = await self._repo.get_by_username(credentials.username)

        if user is None or not verify_password(credentials.password, user.hashed_password):
            logger.warning("Failed login attempt for username=%r", credentials.username)
            # Log failed login attempt
            await self._audit_service.log(
                user_id="anonymous",
                action=AuditAction.LOGIN_FAILED,
                entity_type=AuditEntityType.USER,
                entity_id=None,
                detail={"username": credentials.username, "reason": "invalid_credentials"},
            )
            raise InvalidCredentialsError()

        if not user.is_active:
            logger.warning("Login attempt on inactive account username=%r", credentials.username)
            # Log failed login attempt for inactive account
            await self._audit_service.log(
                user_id=str(user.id),
                action=AuditAction.LOGIN_FAILED,
                entity_type=AuditEntityType.USER,
                entity_id=str(user.id),
                detail={"username": credentials.username, "reason": "account_disabled"},
            )
            raise InvalidCredentialsError(message="Account is disabled. Contact an administrator.")

        if needs_upgrade(user.hashed_password):
            user.hashed_password = hash_password(credentials.password)
            await self._repo.update(user)
            logger.info("Upgraded password hash for user %r", user.username)

        access_token = create_access_token(
            subject=str(user.id),
            additional_claims={"role": user.role.value, "username": user.username},
        )
        refresh_token = create_refresh_token(subject=str(user.id))

        logger.info("User %r logged in successfully.", user.username)

        # Log successful login
        await self._audit_service.log(
            user_id=str(user.id),
            action=AuditAction.LOGIN,
            entity_type=AuditEntityType.USER,
            entity_id=str(user.id),
            detail={"username": user.username, "role": user.role.value},
        )

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def refresh(self, refresh_token_str: str) -> AccessTokenResponse:
        """
        Validate a refresh token and issue a new access token.
        Raises InvalidTokenError if the token is invalid, expired, or wrong type.
        """
        try:
            payload = decode_token(refresh_token_str)
            if payload.get("type") != "refresh":
                raise InvalidTokenError()
            user_id = uuid.UUID(payload["sub"])
        except (JWTError, ValueError, KeyError):
            raise InvalidTokenError()

        user = await self._repo.get_by_id(user_id)
        if user is None or not user.is_active:
            raise InvalidTokenError()

        access_token = create_access_token(
            subject=str(user.id),
            additional_claims={"role": user.role.value, "username": user.username},
        )
        logger.info("Token refreshed for user_id=%s", user_id)
        return AccessTokenResponse(access_token=access_token)
