import asyncio
import hashlib
import uuid

import pytest
from sqlalchemy import select

from research_agent.core import db as db_module
from research_agent.core.models.db import PipelineRun, ResearchArtifact, User
from research_agent.execution.base import ExecutionBackend, ExecutionPlan, ExecutionResult
from research_agent.execution.manager import PipelineRunManager, recover_pipeline_runs
from research_agent.research.artifacts import ArtifactStore


class FakeBackend(ExecutionBackend):
    backend_id = "fake"

    def __init__(self, root, block=False):
        self.root = root
        self.block = block
        self.started = asyncio.Event()

    async def capabilities(self, *, deep=False):
        return {"backend": self.backend_id, "available": True, "deep_probe": deep}

    async def preflight(self, **kwargs):
        return {"ready": True, "issues": [], "warnings": []}

    async def build_plan(self, **kwargs):
        root = self.root / kwargs["run_id"]
        reports = root / "reports"
        output = root / "results"
        work = root / "work"
        for path in (root, reports, output, work):
            path.mkdir(parents=True, exist_ok=True)
        return ExecutionPlan(
            backend=self.backend_id,
            run_id=kwargs["run_id"],
            argv=["fake", "run"],
            display_argv=["fake", "run"],
            cwd=root,
            environment={},
            work_dir=work,
            output_dir=output,
            report_paths={"stdout": reports / "stdout.log", "stderr": reports / "stderr.log"},
            timeout_seconds=kwargs["timeout_seconds"],
            provenance={"pipeline": kwargs["pipeline_id"]},
        )

    async def execute(self, plan):
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        return ExecutionResult(
            run_id=plan.run_id,
            status="completed",
            exit_code=0,
            task_summary={"tasks": 1, "statuses": {"COMPLETED": 1}},
            provenance={"backend": self.backend_id},
        )


async def seed_run(tmp_path, status="queued"):
    store = ArtifactStore.from_database_url(str(db_module.engine.url))
    artifact_id = str(uuid.uuid4())
    folder = store.root / "user-1" / "inbox"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{artifact_id}.csv"
    content = b"sample,fastq_1,fastq_2,strandedness\nS1,x.fastq.gz,,auto\n"
    path.write_bytes(content)
    run_id = str(uuid.uuid4())
    async with db_module.AsyncSessionLocal() as db:
        db.add(User(id=1, username="runner", email="runner@example.org", hashed_password="x", role="admin"))
        db.add(ResearchArtifact(
            id=artifact_id, user_id=1, name="samples.csv",
            relative_path=path.relative_to(store.root).as_posix(), media_type="text/csv",
            kind="input", size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
            summary={}, status="ready",
        ))
        db.add(PipelineRun(
            id=run_id, user_id=1, backend="fake", pipeline_id="nf-core/rnaseq",
            revision="3.26.0", profile="docker", status=status,
            parameters={"genome": "GRCh38"},
            artifact_bindings={"input": artifact_id}, network_allowed=True,
            timeout_seconds=3600, provenance={},
        ))
        await db.commit()
    return run_id


@pytest.mark.asyncio
async def test_manager_persists_completed_result_and_artifact_provenance(tmp_path):
    await db_module.init_db()
    run_id = await seed_run(tmp_path)
    backend = FakeBackend(tmp_path / "backend")
    manager = PipelineRunManager(backend)
    plan = await manager.plan_run(run_id)
    assert plan["argv"] == ["fake", "run"]
    await manager._run(run_id)

    async with db_module.AsyncSessionLocal() as db:
        run = (await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))).scalar_one()
        assert run.status == "completed"
        assert run.exit_code == 0
        assert run.result["task_summary"]["tasks"] == 1
        assert len(run.provenance["artifact_sha256"]["input"]) == 64


@pytest.mark.asyncio
async def test_manager_cancellation_is_persisted(tmp_path):
    await db_module.init_db()
    run_id = await seed_run(tmp_path)
    backend = FakeBackend(tmp_path / "backend", block=True)
    manager = PipelineRunManager(backend)
    assert manager.submit(run_id)
    await asyncio.wait_for(backend.started.wait(), timeout=3)
    assert manager.cancel(run_id)
    for _ in range(100):
        if run_id not in manager.active_ids():
            break
        await asyncio.sleep(0.01)
    async with db_module.AsyncSessionLocal() as db:
        run = (await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))).scalar_one()
        assert run.status == "cancelled"
        assert run.result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_startup_recovery_marks_orphaned_runs_interrupted(tmp_path):
    await db_module.init_db()
    run_id = await seed_run(tmp_path, status="running")
    assert await recover_pipeline_runs() == 1
    async with db_module.AsyncSessionLocal() as db:
        run = (await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))).scalar_one()
        assert run.status == "interrupted"
        assert "previous application process" in run.error
