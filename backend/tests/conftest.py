"""
tests/conftest.py

Shared pytest fixtures for the backend test suite.

Provides:
- `db_session`   : a fresh, isolated SQLite (aiosqlite) in-memory DB per test,
                    with all tables created from the real ORM models.
- `app`          : a FastAPI app instance with `get_db` overridden to use the
                    test session instead of the real Postgres connection.
- `client`       : an httpx.AsyncClient wired to `app` via ASGITransport —
                    no real network, no real database, fully isolated.
- `make_user`    : helper to insert a User directly (bypassing HTTP, since
                    there is no self-registration endpoint — only admin
                    user creation) so auth tests have someone to log in as.

Run with:
    cd backend && pytest tests/ -v
"""
import os
import uuid

# Test-only settings — MUST be set before `app.core.config` is imported
# anywhere, since Settings() is instantiated at import time.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault(
    "SECRET_KEY", "test-only-secret-key-do-not-use-in-prod-please-1234567890"
)
os.environ.setdefault("DEBUG", "false")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.database import Base
from app.db.session import get_db
from app.main import create_app
from app.models.user import User, UserRole

# Import all models so Base.metadata knows about every table before create_all.
import app.models  # noqa: F401


# A few models (AppConfig, AuditLog, APIUsageLog) use Postgres-native JSONB.
# Teach SQLAlchemy to render that as plain JSON when compiling against
# SQLite, so the full real schema can be created in the test DB without
# touching the production models. Production (Postgres) is unaffected.
@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_for_sqlite(element, compiler, **kw):
    return "JSON"


@pytest_asyncio.fixture
async def db_session():
    """Fresh in-memory SQLite DB per test, all tables created, torn down after."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # keeps the same in-memory DB across connections
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def app(db_session):
    """FastAPI app with the real DB dependency swapped for the test session."""
    fastapi_app = create_app()

    async def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    """httpx client talking to the app in-process — no real network."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def make_user(db_session):
    """
    Factory fixture: make_user(username=..., password=..., role=...)
    Inserts a user directly into the test DB and returns (user, plain_password).
    """

    async def _make(
        username: str = "testscientist",
        password: str = "correct-horse-battery-staple",
        email: str | None = None,
        role: UserRole = UserRole.SCIENTIST,
        is_active: bool = True,
    ) -> tuple[User, str]:
        user = User(
            username=username,
            email=email or f"{username}@example.com",
            hashed_password=hash_password(password),
            full_name=f"{username.title()} Test",
            role=role,
            is_active=is_active,
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.commit()
        return user, password

    return _make
