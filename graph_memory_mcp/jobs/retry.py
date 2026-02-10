"""Retry utilities for background jobs."""

import asyncio
import logging
from functools import wraps
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_async(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    backoff_max: float = 30.0,
):
    """Decorator for async functions with exponential backoff retry.

    Args:
        max_attempts: Maximum number of attempts before giving up.
        backoff_base: Base for exponential backoff calculation.
        backoff_max: Maximum wait time between retries in seconds.

    Returns:
        Decorated function that will retry on exceptions.
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__name__,
                            max_attempts,
                            exc,
                        )
                        raise
                    wait = min(backoff_base**attempt, backoff_max)
                    logger.warning(
                        "%s attempt %d/%d failed, retry in %.1fs: %s",
                        func.__name__,
                        attempt,
                        max_attempts,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
