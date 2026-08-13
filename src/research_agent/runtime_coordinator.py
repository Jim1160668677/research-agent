"""Process-wide resource coordination and observable runtime snapshots."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RuntimeLease:
    subsystem: str
    operation_id: str
    acquired_at: str


class RuntimeCoordinator:
    """Bound aggregate desktop work while preserving subsystem schedulers.

    Research capabilities, workflow nodes and external pipelines previously had
    independent limits.  This coordinator adds the missing process-wide limit
    and exposes a lock-protected snapshot for diagnostics and the desktop UI.
    """

    def __init__(self, max_concurrency: int = 6):
        self._loop = asyncio.get_running_loop()
        self._max_concurrency = max(1, min(int(max_concurrency), 32))
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._lock = asyncio.Lock()
        self._active: dict[str, RuntimeLease] = {}
        self._waiting = 0
        self._completed = 0
        self._failed = 0

    @asynccontextmanager
    async def lease(self, subsystem: str, operation_id: str) -> AsyncIterator[RuntimeLease]:
        key = f"{subsystem}:{operation_id}:{id(asyncio.current_task())}"
        async with self._lock:
            self._waiting += 1
        await self._semaphore.acquire()
        lease = RuntimeLease(
            subsystem=subsystem,
            operation_id=operation_id,
            acquired_at=datetime.now(timezone.utc).isoformat(),
        )
        async with self._lock:
            self._waiting -= 1
            self._active[key] = lease
        failed = False
        try:
            yield lease
        except BaseException:
            failed = True
            raise
        finally:
            async with self._lock:
                self._active.pop(key, None)
                self._completed += 1
                if failed:
                    self._failed += 1
            self._semaphore.release()

    async def snapshot(self) -> dict:
        async with self._lock:
            counts: dict[str, int] = {}
            for lease in self._active.values():
                counts[lease.subsystem] = counts.get(lease.subsystem, 0) + 1
            return {
                "max_concurrency": self._max_concurrency,
                "active": len(self._active),
                "waiting": self._waiting,
                "active_by_subsystem": counts,
                "completed_operations": self._completed,
                "failed_operations": self._failed,
                "operations": [
                    {
                        "subsystem": lease.subsystem,
                        "operation_id": lease.operation_id,
                        "acquired_at": lease.acquired_at,
                    }
                    for lease in self._active.values()
                ],
            }


_coordinator: RuntimeCoordinator | None = None


def get_runtime_coordinator(max_concurrency: int = 6) -> RuntimeCoordinator:
    global _coordinator
    loop = asyncio.get_running_loop()
    if _coordinator is None or _coordinator._loop is not loop:
        _coordinator = RuntimeCoordinator(max_concurrency=max_concurrency)
    return _coordinator


def reset_runtime_coordinator() -> None:
    global _coordinator
    _coordinator = None


__all__ = [
    "RuntimeCoordinator",
    "RuntimeLease",
    "get_runtime_coordinator",
    "reset_runtime_coordinator",
]
