"""Background task utilities with error handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable


logger = logging.getLogger(__name__)


def safe_background_task(coro: Awaitable[Any], task_name: str) -> asyncio.Task[None]:
    """Wrap background task with error logging.

    Args:
        coro: The coroutine to run as a background task
        task_name: Descriptive name for logging

    Returns:
        The created asyncio Task
    """
    async def _wrapped() -> None:
        try:
            await coro
        except Exception:
            logger.exception("Background task '%s' failed", task_name)

    return asyncio.create_task(_wrapped())
