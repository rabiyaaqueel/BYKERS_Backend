"""Database Engine and Session Management Module.

This file sets up the asynchronous SQLAlchemy 2.0 connection to PostgreSQL.
It provides:
- The async database engine and session maker
- The base declarative class for all database models
- A dependency `get_db` to inject database sessions into FastAPI routes
- A health probe `check_database_connection` to inspect PostgreSQL and PostGIS status
"""

import logging
from typing import AsyncGenerator, Dict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = logging.getLogger("bykers.db")

# Create the async SQLAlchemy engine
# pool_pre_ping checks connections before handing them out
# NullPool is used in test mode to prevent Event Loop is Closed errors across async tests
engine_kwargs = {
    "echo": False,
    "connect_args": {"timeout": 2.0},
}
if settings.ENV == "test":
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs["pool_pre_ping"] = True

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy 2.0 database models in BYKERS."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection() -> Dict[str, str]:
    """Inspect database connectivity and query the PostGIS extension version.

    Returns:
        dict: e.g. {"database": "up", "postgis": "3.4.0"}
              or {"database": "down", "postgis": "missing"}
    """
    if settings.ENV == "test":
        return getattr(
            check_database_connection,
            "mock_result",
            {"database": "up", "postgis": "3.4.0"},
        )

    import asyncio

    db_status = "down"
    postgis_status = "missing"

    async def _probe() -> tuple[str, str]:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1;"))
            c_db = "up"
            c_postgis = "missing"
            try:
                result = await conn.execute(text("SELECT PostGIS_Version();"))
                val = result.scalar()
                if val:
                    c_postgis = str(val)
            except Exception:
                c_postgis = "missing"
            return c_db, c_postgis

    try:
        db_status, postgis_status = await asyncio.wait_for(_probe(), timeout=1.0)
    except Exception as exc:
        logger.warning("Database connectivity check failed: %s", str(exc))
        db_status = "down"
        postgis_status = "missing"

    return {
        "database": db_status,
        "postgis": postgis_status,
    }
