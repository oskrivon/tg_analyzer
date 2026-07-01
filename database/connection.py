"""Database connection and session management."""

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from .retry import RetryableSession, db_retry, execute_with_retry, retry_session

logger = logging.getLogger(__name__)

async_engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=30,
    max_overflow=50,
    pool_timeout=60,
)

async_session_maker = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database session."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables."""
    from .models import Base

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connection."""
    await async_engine.dispose()


async def get_retryable_session() -> AsyncGenerator[RetryableSession, None]:
    """Dependency for getting async database session with retry support."""
    async with async_session_maker() as session:
        try:
            yield RetryableSession(session)
        finally:
            await session.close()


async def check_db_health() -> dict:
    """
    Check database health.

    Returns:
        Dict with health status and details
    """
    from sqlalchemy import text

    try:
        async with async_session_maker() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar()

            # Get pool status
            pool = async_engine.pool

            return {
                "status": "healthy",
                "pool_size": pool.size() if hasattr(pool, 'size') else None,
                "checked_out": pool.checkedout() if hasattr(pool, 'checkedout') else None,
                "overflow": pool.overflow() if hasattr(pool, 'overflow') else None,
            }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }
