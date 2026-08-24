"""
app/core/security.py

JWT token creation/decoding and bcrypt password hashing utilities.
All auth logic belongs here — routes and services call these helpers.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────
ph = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Return Argon2id hash of a plaintext password."""
    return ph.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if plain_password matches the stored bcrypt or Argon2id hash."""
    try:
        if hashed_password.startswith("$2"):
            return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
        elif hashed_password.startswith("$argon2"):
            return ph.verify(hashed_password, plain_password)
        else:
            logger.warning("password_hash_scheme=unknown")
            return False
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
    except Exception as e:
        logger.error(f"Error verifying password: {type(e).__name__}")
        return False

def needs_upgrade(hashed_password: str) -> bool:
    """Return True if the hash should be upgraded (bcrypt or outdated Argon2 config)."""
    if hashed_password.startswith("$2"):
        return True
    if hashed_password.startswith("$argon2"):
        try:
            return ph.check_needs_rehash(hashed_password)
        except InvalidHashError:
            return False
    return False


# ── JWT helpers ───────────────────────────────────────────────────────────────
def _create_token(
    subject: str,
    token_type: str,
    expire_delta: timedelta,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expire_delta,
    }
    if additional_claims:
        payload.update(additional_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(
    subject: str,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """Create a short-lived access JWT."""
    return _create_token(
        subject=subject,
        token_type="access",
        expire_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        additional_claims=additional_claims,
    )


def create_refresh_token(subject: str) -> str:
    """Create a long-lived refresh JWT."""
    return _create_token(
        subject=subject,
        token_type="refresh",
        expire_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT.
    Raises jose.JWTError on failure (expired, invalid signature, etc.).
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
