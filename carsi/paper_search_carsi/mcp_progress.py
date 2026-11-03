"""Request-local standard MCP progress for a synchronous single download."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import threading
from typing import Callable, Any

from . import progress_reporter

STAGE_PREFIX = "carsi.stage:"


async def run_with_progress(context: Any, identifier: str, operation: Callable[[], str]) -> str:
    """Stream fixed stages while the blocking operation runs off the event loop.

    The injected MCP context owns the caller's progress token (or sends nothing
    for an older client). Neither a global progress file nor GUI prose is read.
    """
    if context is None:
        return await asyncio.to_thread(operation)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=64)
    active = threading.Event()
    active.set()
    lock = threading.Lock()
    last_stage: str | None = None

    def enqueue(stage: str) -> None:
        if not active.is_set():
            return
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(stage)

    def observe(stage: str) -> None:
        nonlocal last_stage
        if stage not in progress_reporter.STAGES or not active.is_set():
            return
        with lock:
            if stage == last_stage:
                return
            last_stage = stage
            try:
                loop.call_soon_threadsafe(enqueue, stage)
            except RuntimeError:
                # The request loop has already closed; never retain/replay it.
                active.clear()

    async def send() -> None:
        revision = 0
        while (stage := await queue.get()) is not None:
            revision += 1
            try:
                await context.report_progress(progress=revision, message=STAGE_PREFIX + stage)
            except Exception:
                # Progress is optional; a disconnected observer must not alter
                # the result or expose the raw transport exception.
                active.clear()
                return

    sender = asyncio.create_task(send())
    cancelled = False
    try:
        with progress_reporter.listen_for_stages(identifier, observe):
            return await asyncio.to_thread(operation)
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        active.clear()
        if not cancelled:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(None)
            # Never let an unavailable progress consumer hold the final result.
            with suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(sender, timeout=1)
        sender.cancel()
        with suppress(asyncio.CancelledError):
            await sender
