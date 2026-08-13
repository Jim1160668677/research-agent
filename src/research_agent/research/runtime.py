"""持久化的计划—执行—验证科研任务运行时。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.models.db import ResearchArtifact, ResearchRun, ResearchRunStep
from .artifacts import ArtifactStore
from .contracts import CAPABILITIES
from .planner import ResearchPlanner
from .scheduler import CapabilityScheduler, ToolPolicy
from .services import HANDLERS

TERMINAL_STEP_STATES = {"completed", "degraded", "failed", "blocked", "cancelled"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ResearchRuntime:
    def __init__(self, global_semaphore: asyncio.Semaphore, artifact_store: ArtifactStore):
        self.global_semaphore = global_semaphore
        self.artifact_store = artifact_store

    async def _artifacts_for_run(self, db: AsyncSession, run: ResearchRun) -> list[dict[str, Any]]:
        ids = list((run.context or {}).get("artifact_ids") or [])
        if not ids:
            return []
        result = await db.execute(
            select(ResearchArtifact).where(
                ResearchArtifact.user_id == run.user_id,
                ResearchArtifact.id.in_(ids),
            )
        )
        return [
            {
                "id": item.id,
                "name": item.name,
                "relative_path": item.relative_path,
                "media_type": item.media_type,
                "kind": item.kind,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
                "encryption_format": item.encryption_format,
                "encrypted_sha256": item.encrypted_sha256,
                "summary": item.summary or {},
            }
            for item in result.scalars().all()
        ]

    async def _persist_generated(
        self,
        db: AsyncSession,
        run: ResearchRun,
        generated: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        public = []
        for item in generated:
            artifact = ResearchArtifact(
                id=item["id"],
                user_id=run.user_id,
                run_id=run.id,
                name=item["name"],
                relative_path=item["relative_path"],
                media_type=item["media_type"],
                kind=item.get("kind", "output"),
                size_bytes=item.get("size_bytes", 0),
                sha256=item["sha256"],
                encryption_format=item.get("encryption_format"),
                encrypted_sha256=item.get("encrypted_sha256"),
                summary=item.get("summary", {}),
                status=item.get("status", "ready"),
            )
            db.add(artifact)
            public.append({
                "id": artifact.id,
                "name": artifact.name,
                "media_type": artifact.media_type,
                "kind": artifact.kind,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
                "summary": artifact.summary,
            })
        return public

    async def execute(self, db: AsyncSession, run_id: str) -> None:
        result = await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return
        if run.status not in {"pending", "queued"}:
            return

        errors = ResearchPlanner.validate_plan(run.plan or {})
        if errors:
            run.status = "failed"
            run.result = {"errors": errors, "has_gaps": True}
            run.completed_at = _utcnow()
            await db.commit()
            return

        run.status = "running"
        run.started_at = _utcnow()
        run.progress = 0
        await db.commit()

        policy = ToolPolicy(run.policy or {})
        scheduler = CapabilityScheduler(
            self.global_semaphore,
            int((run.budget or {}).get("max_concurrency", 2)),
        )
        artifacts = await self._artifacts_for_run(db, run)
        try:
            while True:
                await db.refresh(run)
                if run.cancel_requested:
                    raise asyncio.CancelledError

                step_result = await db.execute(
                    select(ResearchRunStep)
                    .where(ResearchRunStep.run_id == run.id)
                    .order_by(ResearchRunStep.order)
                )
                steps = list(step_result.scalars().all())
                pending = [step for step in steps if step.status == "pending"]
                if not pending:
                    break
                status_by_key = {step.step_key: step.status for step in steps}
                ready = [
                    step for step in pending
                    if all(status_by_key.get(key) in TERMINAL_STEP_STATES for key in (step.dependencies or []))
                ]
                if not ready:
                    raise RuntimeError("研究计划无法继续：依赖未满足或存在循环")

                max_wave = int((run.budget or {}).get("max_concurrency", 2))
                ready = ready[:max_wave]
                now = _utcnow()
                for step in ready:
                    step.status = "running"
                    step.started_at = now
                    run.current_step = step.title
                await db.commit()

                completed_outputs = {
                    step.step_key: step.output_data or {}
                    for step in steps
                    if step.status in TERMINAL_STEP_STATES
                }
                calls = []
                for step in ready:
                    spec = CAPABILITIES[step.capability]
                    payload = {
                        **(step.input_data or {}),
                        "objective": run.objective,
                        "context": run.context or {},
                        "artifacts": artifacts,
                        "dependency_outputs": {
                            key: completed_outputs.get(key, {}) for key in (step.dependencies or [])
                        },
                        "run_id": run.id,
                        "user_id": run.user_id,
                        "artifact_store": self.artifact_store,
                    }
                    calls.append(scheduler.execute(spec, HANDLERS[step.capability], payload, policy))

                scheduled = await asyncio.gather(*calls)
                for step, outcome in zip(ready, scheduled, strict=True):
                    capability_result = outcome.result
                    step.status = capability_result.status
                    step.output_data = capability_result.output
                    step.warnings = capability_result.warnings
                    step.confidence = max(0.0, min(float(capability_result.confidence), 1.0))
                    step.attempts = outcome.attempts
                    step.completed_at = _utcnow()
                    step.duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
                    if capability_result.status == "failed":
                        step.error = "; ".join(capability_result.warnings)[:2000]
                    if capability_result.evidence:
                        existing = list(run.evidence or [])
                        known = {(item.get("source_type"), item.get("id")) for item in existing}
                        for evidence in capability_result.evidence:
                            key = (evidence.get("source_type"), evidence.get("id"))
                            if key not in known:
                                existing.append(evidence)
                                known.add(key)
                        run.evidence = existing[:200]
                    if capability_result.generated_artifacts:
                        generated = await self._persist_generated(db, run, capability_result.generated_artifacts)
                        merged = dict(step.output_data or {})
                        merged["generated_artifacts"] = generated
                        step.output_data = merged

                finished = sum(1 for step in steps if step.status in TERMINAL_STEP_STATES)
                run.progress = int(finished / max(len(steps), 1) * 100)
                await db.commit()

            final_steps = list((await db.execute(
                select(ResearchRunStep)
                .where(ResearchRunStep.run_id == run.id)
                .order_by(ResearchRunStep.order)
            )).scalars().all())
            warnings = [warning for step in final_steps for warning in (step.warnings or [])]
            failures = [step.step_key for step in final_steps if step.status in {"failed", "blocked"}]
            confidences = [step.confidence for step in final_steps if step.confidence is not None]
            run.result = {
                "objective": run.objective,
                "status": "completed_with_gaps" if warnings or failures else "completed",
                "has_gaps": bool(warnings or failures),
                "confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
                "warnings": warnings[:100],
                "failed_or_blocked_steps": failures,
                "outputs": {step.step_key: step.output_data or {} for step in final_steps},
                "review_required": list((run.plan or {}).get("review_gates") or []),
                "provenance": {
                    "evidence_count": len(run.evidence or []),
                    "plan_id": (run.plan or {}).get("id"),
                    "runtime": "research-runtime-v1",
                },
            }
            run.status = "completed"
            run.progress = 100
            run.current_step = None
            run.completed_at = _utcnow()
            await db.commit()
        except asyncio.CancelledError:
            run.status = "cancelled"
            run.current_step = None
            run.completed_at = _utcnow()
            run.result = {"status": "cancelled", "has_gaps": True, "message": "任务已由用户取消。"}
            step_result = await db.execute(
                select(ResearchRunStep).where(
                    ResearchRunStep.run_id == run.id,
                    ResearchRunStep.status == "running",
                )
            )
            for step in step_result.scalars().all():
                step.status = "cancelled"
                step.completed_at = _utcnow()
            await db.commit()
        except Exception as exc:
            logger.exception(f"科研任务 {run.id} 执行失败")
            run.status = "failed"
            run.current_step = None
            run.completed_at = _utcnow()
            run.result = {"status": "failed", "has_gaps": True, "error": str(exc)[:1000]}
            await db.commit()
