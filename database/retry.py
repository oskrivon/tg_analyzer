"""Database retry utilities for handling transient failures."""

import asyncio
import logging
from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncGenerator, Callable, TypeVar

from sqlalchemy.exc import (
    DBAPIError,
    InterfaceError,
    OperationalError,
    TimeoutError as SQLAlchemyTimeoutError,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Exceptions that should trigger a retry
RETRYABLE_EXCEPTIONS = (
    OperationalError,  # Connection issues, deadlocks
    InterfaceError,  # Connection pool issues
    SQLAlchemyTimeoutError,  # Query timeout
    ConnectionRefusedError,  # PostgreSQL not available
    asyncio.TimeoutError,  # Async timeout
)


def db_retry(
    max_attempts: int = 3,
    min_wait: float = 0.5,
    max_wait: float = 10.0,
) -> Callable:
    """
    Decorator for retrying database operations on transient failures.

    Args:
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time between retries (seconds)
        max_wait: Maximum wait time between retries (seconds)

    Example:
        @db_retry(max_attempts=3)
        async def fetch_accounts(session: AsyncSession):
            return await session.execute(select(ChannelDB))
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None

            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
                retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
                reraise=True,
            ):
                with attempt:
                    try:
                        return await func(*args, **kwargs)
                    except RETRYABLE_EXCEPTIONS as e:
                        last_exception = e
                        attempt_num = attempt.retry_state.attempt_number
                        logger.warning(
                            f"DB operation {func.__name__} failed (attempt {attempt_num}/{max_attempts}): {e}"
                        )
                        raise

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


@asynccontextmanager
async def retry_session(
    session_maker,
    max_attempts: int = 3,
    min_wait: float = 0.5,
    max_wait: float = 10.0,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager that provides a session with automatic retry on connection failures.

    Retries the entire block if a transient database error occurs.

    Args:
        session_maker: SQLAlchemy async session maker
        max_attempts: Maximum retry attempts
        min_wait: Minimum wait between retries
        max_wait: Maximum wait between retries

    Example:
        async with retry_session(async_session_maker) as session:
            result = await session.execute(select(ChannelDB))
            accounts = result.scalars().all()
    """
    last_exception = None

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        reraise=True,
    ):
        with attempt:
            async with session_maker() as session:
                try:
                    yield session
                    return
                except RETRYABLE_EXCEPTIONS as e:
                    last_exception = e
                    attempt_num = attempt.retry_state.attempt_number
                    logger.warning(
                        f"DB session operation failed (attempt {attempt_num}/{max_attempts}): {e}"
                    )
                    await session.rollback()
                    raise

    if last_exception:
        raise last_exception


async def execute_with_retry(
    session: AsyncSession,
    operation: Callable,
    max_attempts: int = 3,
    min_wait: float = 0.5,
    max_wait: float = 10.0,
) -> T:
    """
    Execute a database operation with retry logic.

    Args:
        session: SQLAlchemy async session
        operation: Async callable that performs the database operation
        max_attempts: Maximum retry attempts
        min_wait: Minimum wait between retries
        max_wait: Maximum wait between retries

    Example:
        result = await execute_with_retry(
            session,
            lambda: session.execute(select(ChannelDB))
        )
    """
    last_exception = None

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        reraise=True,
    ):
        with attempt:
            try:
                return await operation()
            except RETRYABLE_EXCEPTIONS as e:
                last_exception = e
                attempt_num = attempt.retry_state.attempt_number
                logger.warning(
                    f"DB execute failed (attempt {attempt_num}/{max_attempts}): {e}"
                )
                raise

    if last_exception:
        raise last_exception


class RetryableSession:
    """
    Wrapper around AsyncSession that adds retry logic to common operations.

    Example:
        async with async_session_maker() as session:
            retry_session = RetryableSession(session)
            result = await retry_session.execute(select(ChannelDB))
    """

    def __init__(
        self,
        session: AsyncSession,
        max_attempts: int = 3,
        min_wait: float = 0.5,
        max_wait: float = 10.0,
    ):
        self._session = session
        self._max_attempts = max_attempts
        self._min_wait = min_wait
        self._max_wait = max_wait

    @property
    def session(self) -> AsyncSession:
        """Access underlying session for operations that don't need retry."""
        return self._session

    async def execute(self, statement, *args, **kwargs):
        """Execute statement with retry."""
        return await execute_with_retry(
            self._session,
            lambda: self._session.execute(statement, *args, **kwargs),
            self._max_attempts,
            self._min_wait,
            self._max_wait,
        )

    async def commit(self):
        """Commit with retry."""
        return await execute_with_retry(
            self._session,
            self._session.commit,
            self._max_attempts,
            self._min_wait,
            self._max_wait,
        )

    async def rollback(self):
        """Rollback (no retry needed)."""
        return await self._session.rollback()

    def add(self, instance):
        """Add instance to session (no retry needed)."""
        return self._session.add(instance)

    async def refresh(self, instance, *args, **kwargs):
        """Refresh with retry."""
        return await execute_with_retry(
            self._session,
            lambda: self._session.refresh(instance, *args, **kwargs),
            self._max_attempts,
            self._min_wait,
            self._max_wait,
        )

    async def delete(self, instance):
        """Delete instance with retry."""
        return await execute_with_retry(
            self._session,
            lambda: self._session.delete(instance),
            self._max_attempts,
            self._min_wait,
            self._max_wait,
        )
