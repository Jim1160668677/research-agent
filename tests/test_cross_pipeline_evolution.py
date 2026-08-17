"""Test for cross-pipeline evolution in pipeline_evolution handler"""
import pytest
import pytest_asyncio
from pathlib import Path


@pytest_asyncio.fixture
async def _setup_db(tmp_path):
    from research_agent.core.db import init_db
    await init_db()
    return tmp_path


@pytest.mark.asyncio
async def test_pipeline_evolution_cross_pipeline_aggregation(_setup_db, tmp_path, monkeypatch):
    """When a user has runs across multiple pipelines, cross-pipeline signals are aggregated."""
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_evolution
    from research_agent.research.artifacts import ArtifactStore
    from research_agent.core.models.db import PipelineRun
    from research_agent.core import db as db_module
    from datetime import datetime, timezone

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        # Same-pipeline runs (existing behavior)
        runs = [
            PipelineRun(
                id="hist-run-a", user_id=1, run_id="hist-research-a",
                pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
                status="completed",
                parameters={"max_cpus": 4, "test_profile": True},
                created_at=datetime(2026, 8, 10, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
            PipelineRun(
                id="hist-run-b", user_id=1, run_id="hist-research-b",
                pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
                status="completed",
                parameters={"max_cpus": 4, "test_profile": True},
                created_at=datetime(2026, 8, 11, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
            PipelineRun(
                id="hist-run-c", user_id=1, run_id="hist-research-c",
                pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
                status="failed",
                parameters={"max_cpus": 1, "test_profile": True},
                error="Executor: java.lang.OutOfMemoryError: Java heap space (killed)",
                created_at=datetime(2026, 8, 12, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
            # Cross-pipeline runs from a DIFFERENT pipeline
            PipelineRun(
                id="hist-run-d", user_id=1, run_id="hist-research-d",
                pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
                status="completed",
                parameters={"max_cpus": 4},
                created_at=datetime(2026, 8, 13, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
            PipelineRun(
                id="hist-run-e", user_id=1, run_id="hist-research-e",
                pipeline_id="nf-core/sarek", revision="3.9.0", profile="docker",
                status="completed",
                parameters={"max_cpus": 4, "assembly": "de_novo"},
                created_at=datetime(2026, 8, 13, 11, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
        ]
        for r in runs:
            db.add(r)
        await db.commit()

    result = await pipeline_evolution({
        "run_id": "hist-research-c",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "completed"
    # Should have cross-pipeline signal
    assert any("跨流水线" in s for s in result.output["signals"])
    assert result.output.get("cross_pipeline_summary") is not None
    summary = result.output["cross_pipeline_summary"]
    assert summary["unique_pipelines"] >= 2
    assert summary["total_cross_runs"] >= 2
    # Should also have same-pipeline adaptive analysis
    assert result.output.get("adaptive_summary") is not None
    assert any("历史分析" in s for s in result.output["signals"])
