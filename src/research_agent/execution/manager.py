"""Persistent state machine for external scientific pipeline execution."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from ..core.app import settings
from ..core.models.db import PipelineRun, ResearchArtifact
from ..research.artifacts import ArtifactStore
from .base import ExecutionBackend
from .nextflow import NextflowBackend

ACTIVE_STATUSES = {"queued", "running", "cancelling"}
RESUMABLE_STATUSES = {"failed", "cancelled", "interrupted"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PipelineRunManager:
    """Owns subprocess tasks while SQL remains the source of truth."""

    def __init__(self, backend: ExecutionBackend | None = None):
        self._loop = asyncio.get_running_loop()
        self._database_url = settings.database_url
        self._backend = backend or NextflowBackend()
        self._store = ArtifactStore.from_database_url(settings.database_url)
        self._tasks: dict[str, asyncio.Task] = {}
        self._shutting_down = False

    @property
    def backend(self) -> ExecutionBackend:
        return self._backend

    @asynccontextmanager
    async def _artifact_paths(self, db: Any, run: PipelineRun):
        bindings = dict(run.artifact_bindings or {})
        ids = list(dict.fromkeys(str(value) for value in bindings.values()))
        if not ids:
            yield {}
            return
        result = await db.execute(
            select(ResearchArtifact).where(
                ResearchArtifact.user_id == run.user_id,
                ResearchArtifact.id.in_(ids),
                ResearchArtifact.status == "ready",
            )
        )
        artifacts = {item.id: item for item in result.scalars().all()}
        if len(artifacts) != len(ids):
            raise ValueError("A bound artifact is missing, unavailable, or owned by another user")
        with ExitStack() as stack:
            paths: dict[str, Path] = {}
            for parameter, artifact_id in bindings.items():
                artifact = artifacts[str(artifact_id)]
                try:
                    path = stack.enter_context(self._store.materialize(artifact))
                except ValueError as exc:
                    raise ValueError(
                        f"Bound artifact file is unavailable or corrupt: {parameter}"
                    ) from exc
                paths[str(parameter)] = path
            yield paths

    async def plan_run(self, run_id: str) -> dict[str, Any]:
        from ..core import db as db_module

        async with db_module.AsyncSessionLocal() as db:
            result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            run = result.scalar_one_or_none()
            if run is None:
                raise ValueError("Pipeline run does not exist")
            async with self._artifact_paths(db, run) as artifact_paths:
                plan = await self._backend.build_plan(
                    run_id=run.id,
                    user_id=run.user_id,
                    pipeline_id=run.pipeline_id,
                    revision=run.revision,
                    profile=run.profile,
                    parameters=dict(run.parameters or {}),
                    artifact_paths=artifact_paths,
                    resume=bool(run.resume_requested),
                    network_allowed=bool(run.network_allowed),
                    timeout_seconds=int(run.timeout_seconds),
                )
                public = plan.public()
            run.plan = public
            run.provenance = {
                **dict(run.provenance or {}),
                "backend": plan.backend,
                "pipeline": run.pipeline_id,
                "revision": run.revision,
                "profile": run.profile,
                "artifact_sha256": dict(await self._artifact_hashes(db, run)),
            }
            await db.commit()
            return public

    async def _artifact_hashes(self, db: Any, run: PipelineRun) -> list[tuple[str, str]]:
        bindings = dict(run.artifact_bindings or {})
        if not bindings:
            return []
        result = await db.execute(
            select(ResearchArtifact.id, ResearchArtifact.sha256).where(
                ResearchArtifact.user_id == run.user_id,
                ResearchArtifact.id.in_(list(bindings.values())),
            )
        )
        hashes = dict(result.all())
        return [(name, hashes.get(artifact_id, "")) for name, artifact_id in bindings.items()]

    def submit(self, run_id: str) -> bool:
        current = self._tasks.get(run_id)
        if current and not current.done():
            return False
        task = asyncio.create_task(self._run(run_id), name=f"pipeline-run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
        return True

    async def _run(self, run_id: str) -> None:
        from ..core import db as db_module

        async with db_module.AsyncSessionLocal() as db:
            result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            run = result.scalar_one_or_none()
            if run is None or run.status not in {"queued", "running"}:
                return
            try:
                preflight = await self._backend.preflight(
                    pipeline_id=run.pipeline_id,
                    revision=run.revision,
                    profile=run.profile,
                    network_allowed=bool(run.network_allowed),
                )
                if not preflight.get("ready"):
                    raise RuntimeError("; ".join(preflight.get("issues") or ["Preflight failed"]))
                async with self._artifact_paths(db, run) as artifact_paths:
                    plan = await self._backend.build_plan(
                        run_id=run.id,
                        user_id=run.user_id,
                        pipeline_id=run.pipeline_id,
                        revision=run.revision,
                        profile=run.profile,
                        parameters=dict(run.parameters or {}),
                        artifact_paths=artifact_paths,
                        resume=bool(run.resume_requested),
                        network_allowed=bool(run.network_allowed),
                        timeout_seconds=int(run.timeout_seconds),
                    )
                    run.status = "running"
                    run.started_at = _utcnow()
                    run.completed_at = None
                    run.cancel_requested = False
                    run.plan = plan.public()
                    run.error = None
                    await db.commit()

                    # Keep decrypted inputs alive only for the external process lifetime.
                    from ..runtime_coordinator import get_runtime_coordinator

                    async with get_runtime_coordinator().lease("pipeline", run.id):
                        execution = await self._backend.execute(plan)
                run.status = execution.status
                run.exit_code = execution.exit_code
                run.result = execution.to_dict()
                run.provenance = {
                    **dict(run.provenance or {}),
                    **dict(execution.provenance or {}),
                }
                run.error = execution.error or None
                run.completed_at = _utcnow()
                run.resume_requested = False
                await db.commit()
            except asyncio.CancelledError:
                run.status = "interrupted" if self._shutting_down else "cancelled"
                run.cancel_requested = not self._shutting_down
                run.completed_at = _utcnow()
                run.error = (
                    "Application shutdown interrupted execution" if self._shutting_down else None
                )
                run.result = {
                    "run_id": run.id,
                    "status": run.status,
                    "exit_code": None,
                    "error": run.error or "Execution was cancelled by the user",
                }
                await db.commit()
                raise
            except Exception as exc:
                run.status = "failed"
                run.completed_at = _utcnow()
                run.error = str(exc)[:4000]
                run.result = {
                    "run_id": run.id,
                    "status": "failed",
                    "exit_code": None,
                    "error": run.error,
                }
                await db.commit()

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if not task or task.done():
            return False
        task.cancel()
        return True

    def active_ids(self) -> list[str]:
        return sorted(key for key, task in self._tasks.items() if not task.done())

    async def shutdown(self) -> None:
        self._shutting_down = True
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


_manager: PipelineRunManager | None = None


def get_pipeline_manager() -> PipelineRunManager:
    global _manager
    loop = asyncio.get_running_loop()
    if _manager is not None and (
        _manager._loop is not loop or _manager._database_url != settings.database_url
    ):
        for task in list(_manager._tasks.values()):
            if not task.done():
                task.cancel()
        _manager = None
    if _manager is None:
        _manager = PipelineRunManager()
    return _manager


async def recover_pipeline_runs() -> int:
    """Mark process-owned work as interrupted after an unclean application exit."""
    from ..core import db as db_module

    async with db_module.AsyncSessionLocal() as db:
        result = await db.execute(
            update(PipelineRun)
            .where(PipelineRun.status.in_(ACTIVE_STATUSES))
            .values(
                status="interrupted",
                completed_at=_utcnow(),
                error="The previous application process ended before this run completed",
                result={
                    "status": "interrupted",
                    "error": "The previous application process ended before this run completed",
                },
            )
        )
        await db.commit()
        return int(result.rowcount or 0)


async def shutdown_pipeline_manager() -> None:
    global _manager
    if _manager is not None:
        await _manager.shutdown()
        _manager = None


__all__ = [
    "ACTIVE_STATUSES",
    "PipelineRunManager",
    "RESUMABLE_STATUSES",
    "TERMINAL_STATUSES",
    "get_pipeline_manager",
    "recover_pipeline_runs",
    "shutdown_pipeline_manager",
]
