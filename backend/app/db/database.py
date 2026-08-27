"""
app/db/database.py

Async SQLAlchemy engine and declarative Base.
All ORM models inherit from Base defined here.
"""
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# ── Async engine ──────────────────────────────────────────────────────────────
# NOTE: pool_size / max_overflow are QueuePool-only options and are invalid
# for SQLite's default pool (used by the test suite via an in-memory
# sqlite+aiosqlite:// URL). Only pass them for non-SQLite (i.e. real
# Postgres) URLs so production behavior is unchanged.
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {
    "echo": settings.DEBUG,       # log SQL only in DEBUG mode
    "pool_pre_ping": not _is_sqlite,   # recycle stale connections
    "pool_recycle": 3600,          # recycle connections every 1 h
}
if not _is_sqlite:
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20

engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)


# ── Declarative Base ──────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """
    All ORM models must inherit from this class.
    Import this Base in Alembic's env.py so migrations detect model changes.
    """
    pass
