"""进程内科研后台任务管理器。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import update

from ..core.app import settings
from .artifacts import ArtifactStore
from .runtime import ResearchRuntime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ResearchRunManager:
    """为桌面单进程提供有界后台执行和取消传播。"""

    def __init__(self, max_concurrent_capabilities: int = 4):
        self._loop = asyncio.get_running_loop()
        self._database_url = settings.database_url
        self._global_semaphore = asyncio.Semaphore(max(1, max_concurrent_capabilities))
        self._tasks: dict[str, asyncio.Task] = {}
        self._store = ArtifactStore.from_database_url(settings.database_url)
        self._runtime = ResearchRuntime(self._global_semaphore, self._store)

    @property
    def artifact_store(self) -> ArtifactStore:
        return self._store

    def submit(self, run_id: str) -> bool:
        existing = self._tasks.get(run_id)
        if existing and not existing.done():
            return False
        task = asyncio.create_task(self._run(run_id), name=f"research-run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
        return True

    async def _run(self, run_id: str) -> None:
        # Import dynamically: the test/profile switching hook can reload the
        # database module and replace its session factory at runtime.
        from ..core import db as db_module

        async with db_module.AsyncSessionLocal() as db:
            await self._runtime.execute(db, run_id)

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if not task or task.done():
            return False
        task.cancel()
        return True

    def active_ids(self) -> list[str]:
        return sorted(run_id for run_id, task in self._tasks.items() if not task.done())

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


_manager: ResearchRunManager | None = None


def get_run_manager() -> ResearchRunManager:
    global _manager
    loop = asyncio.get_running_loop()
    if _manager is not None and (
        _manager._loop is not loop or _manager._database_url != settings.database_url
    ):
        # Test clients, profile switches and desktop restarts may replace the
        # event loop or database binding. Never reuse loop-bound semaphores or
        # an artifact root from the previous runtime.
        for task in list(_manager._tasks.values()):
            if not task.done():
                task.cancel()
        _manager = None
    if _manager is None:
        _manager = ResearchRunManager()
    return _manager


async def shutdown_run_manager() -> None:
    global _manager
    if _manager is not None:
        await _manager.shutdown()
        _manager = None


async def recover_research_runs() -> int:
    """Mark orphaned in-process research work interrupted after a restart."""
    from ..core import db as db_module
    from ..core.models.db import ResearchRun, ResearchRunStep

    async with db_module.AsyncSessionLocal() as db:
        run_result = await db.execute(
            update(ResearchRun)
            .where(ResearchRun.status.in_({"queued", "running"}))
            .values(
                status="interrupted",
                current_step=None,
                completed_at=_utcnow(),
                result={
                    "status": "interrupted",
                    "has_gaps": True,
                    "error": "The previous application process ended before this run completed",
                },
            )
        )
        await db.execute(
            update(ResearchRunStep)
            .where(ResearchRunStep.status == "running")
            .values(
                status="interrupted",
                error="Application restart interrupted this step",
                completed_at=_utcnow(),
            )
        )
        await db.commit()
        return int(run_result.rowcount or 0)
