from __future__ import annotations

from collections.abc import Awaitable, Callable

ProgressCallback = Callable[[str], Awaitable[None]]


async def report_progress(callback: ProgressCallback | None, stage: str) -> None:
    if callback is not None:
        await callback(stage)
