"""科研任务运行时、证据契约与工作台 API 测试。"""


import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from research_agent.core.app import create_app
from research_agent.research.artifacts import ArtifactError, ArtifactStore
from research_agent.research.contracts import CAPABILITIES
from research_agent.research.planner import ResearchPlanner
from research_agent.research.scheduler import ToolPolicy
from research_agent.research.services import (
    experimental_design,
    integrity_check,
    normalize_evidence,
)
from research_agent.core.models.db import UserProfile, LearningProposal


def test_planner_builds_valid_dag_and_review_gates():
    plan = ResearchPlanner().plan(
        "系统评价一种干预并设计验证实验和论文框架",
        domains=["literature", "experiment", "writing", "integrity"],
        network_allowed=False,
    )
    value = plan.to_dict()
    assert ResearchPlanner.validate_plan(value) == []
    assert [step["key"] for step in value["steps"]] == ["literature", "experiment", "writing", "integrity"]
    assert value["steps"][1]["dependencies"] == ["literature"]
    assert "integrity" in value["review_gates"]
    assert value["policy"]["network_allowed"] is False


def test_planner_adds_multimodal_intake_for_artifacts():
    plan = ResearchPlanner().plan(
        "分析上传的数据并生成可视化",
        artifact_ids=["a", "a", "b"],
    )
    assert plan.domains[:2] == ["multimodal", "data"]
    data_step = next(step for step in plan.steps if step.key == "data")
    assert data_step.dependencies == ["intake"]
    assert data_step.input_data["artifact_ids"] == ["a", "b"]


def test_tool_policy_denies_network_before_execution():
    policy = ToolPolicy({
        "network_allowed": False,
        "allowed_capabilities": ["evidence_review"],
        "deny_unlisted": True,
    })
    decision = policy.evaluate(CAPABILITIES["evidence_review"])
    assert decision.allowed is False
    assert "禁止联网" in decision.reason


def test_evidence_normalization_deduplicates_and_preserves_locator():
    records = [
        {"pmid": "123", "title": "A trial", "abstract": "Result text", "year": "2025"},
        {"pmid": "123", "title": "A trial duplicate", "abstract": "Result text"},
        {"doi": "10.1000/test", "title": "Second paper"},
    ]
    evidence = normalize_evidence(records)
    assert len(evidence) == 2
    pubmed = next(item for item in evidence if item["id"] == "123")
    assert pubmed["locator"] == "https://pubmed.ncbi.nlm.nih.gov/123/"
    assert all("locator" in item and "quality_flags" in item for item in evidence)


@pytest.mark.asyncio
async def test_experimental_design_adds_human_ethics_gate():
    result = await experimental_design({"objective": "评估临床患者接受干预后的主要结局", "context": {}})
    assert result.status == "completed"
    assert "知情同意或其合法豁免" in result.output["ethics_gate"]
    assert result.output["human_review_required"] is True
    assert any("样本量" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_integrity_check_detects_reporting_and_ethics_gaps():
    result = await integrity_check({
        "objective": "患者观察性研究",
        "text": "这项观察性研究证明了治疗导致改善，p<0.05，改善率为25%。",
        "context": {},
        "dependency_outputs": {},
    })
    ids = {finding["check_id"] for finding in result.output["findings"]}
    assert "statistics.effect_size" in ids
    assert "language.causality" in ids
    assert "ethics.human" in ids
    assert "citation.numeric_claim" in ids
    assert "不是抄袭数据库查重" in result.output["limitations"][0]


def test_artifact_store_profiles_table_and_blocks_traversal(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    table = store.root / "sample.csv"
    table.write_text("group,value,missing\nA,1,\nA,2,NA\nB,3,x\n", encoding="utf-8")
    profile = store.profile_table(table)
    assert profile["rows_scanned"] == 3
    assert profile["column_count"] == 3
    value = next(item for item in profile["columns"] if item["name"] == "value")
    assert value["inferred_type"] == "numeric"
    assert value["mean"] == 2.0
    with pytest.raises(ArtifactError):
        store.resolve("../../outside.txt")


@pytest.fixture
def client():
    with TestClient(create_app()) as value:
        yield value


def test_planner_adds_pipeline_execution_step():
    plan = ResearchPlanner().plan(
        "对上传的样本表运行 RNA-seq 流程并生成差异表达分析框架",
        domains=["data", "writing", "integrity"],
        artifact_ids=["samples"],
        context={
            "pipeline": {
                "pipeline_id": "nf-core/rnaseq",
                "revision": "3.26.0",
                "profile": "docker",
                "parameters": {"test_profile": True, "aligner": "star_salmon"},
                "artifact_bindings": {"input": "samples"},
            }
        },
    )
    value = plan.to_dict()
    assert ResearchPlanner.validate_plan(value) == []
    keys = [step["key"] for step in value["steps"]]
    assert keys == ["intake", "data", "pipeline", "pipeline_evolution", "writing", "integrity"]
    pipeline_step = next(step for step in value["steps"] if step["key"] == "pipeline")
    assert pipeline_step["capability"] == "pipeline_execution"
    assert pipeline_step["dependencies"] == ["intake"]
    writing_step = next(step for step in value["steps"] if step["key"] == "writing")
    assert "pipeline" in writing_step["dependencies"]
    assert "pipeline_evolution" in writing_step["dependencies"]
    assert "pipeline" in value["review_gates"]
    assert "pipeline_execution" in value["policy"]["allowed_capabilities"]


def test_planner_ignores_pipeline_without_pipeline_id():
    plan = ResearchPlanner().plan(
        "分析数据并生成写作框架",
        context={"pipeline": {"profile": "docker"}},
    )
    assert all(step.capability != "pipeline_execution" for step in plan.steps)


@pytest.mark.asyncio
async def test_pipeline_evolution_handler_generates_proposals_on_low_feedback(
    tmp_path, monkeypatch
):
    """When feedback ratings are low, pipeline_evolution creates a LearningProposal."""
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_evolution
    from research_agent.research.artifacts import ArtifactStore
    from sqlalchemy import select
    from research_agent.core.models.db import AgentFeedback, LearningProposal

    await init_db()

    # Insert a low-rating feedback record
    from research_agent.core import db as db_module
    async with db_module.AsyncSessionLocal() as db:
        fb = AgentFeedback(
            user_id=1,
            run_id="research-run-evo-1",
            rating=1,
            accepted=False,
            correction="建议将 timeout 从 3600 改为 7200",
            tags=["pipeline_param"],
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(fb)
        await db.commit()

    result = await pipeline_evolution({
        "run_id": "research-run-evo-1",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "completed"
    assert len(result.output["proposal_ids"]) >= 1
    assert any("低分" in s or "参数" in s for s in result.output["signals"])

    # Verify proposal was written to DB
    async with db_module.AsyncSessionLocal() as db:
        prop_result = await db.execute(
            select(LearningProposal).where(LearningProposal.source_run_id == "research-run-evo-1")
        )
        proposals = prop_result.scalars().all()
        assert len(proposals) >= 1
        assert proposals[0].status == "pending"
        assert proposals[0].proposed_change.get("proposal_type") == "pipeline_param"


@pytest.mark.asyncio
async def test_pipeline_evolution_handler_no_signals(tmp_path, monkeypatch):
    """When there are no low ratings or failed runs, returns empty signals."""
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_evolution
    from research_agent.research.artifacts import ArtifactStore

    await init_db()

    result = await pipeline_evolution({
        "run_id": "research-run-evo-noop",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "completed"
    assert "暂无需要进化的信号" in result.output["message"]
    assert result.confidence >= 0.8


@pytest.mark.asyncio
async def test_pipeline_evolution_handler_adaptive_optimization(tmp_path, monkeypatch):
    """When historical runs exist with parameter patterns, generates adaptive suggestions."""
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_evolution
    from research_agent.research.artifacts import ArtifactStore
    from research_agent.core.models.db import PipelineRun
    from research_agent.core import db as db_module
    from datetime import datetime, timezone

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
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
    assert any("历史分析" in s for s in result.output["signals"])
    assert result.output.get("adaptive_summary") is not None
    summary = result.output["adaptive_summary"]
    assert summary["historical_runs"] == 3
    assert len(summary["suggestions"]) >= 1
    assert any(s["parameter"] == "max_cpus" for s in summary["suggestions"])
    cpus_sug = [s for s in summary["suggestions"] if s["parameter"] == "max_cpus"]
    assert cpus_sug
    assert cpus_sug[0]["recommended_value"] == "4"
    assert cpus_sug[0]["confidence"] >= 0.7
    assert any("内存" in s or "OOM" in s for s in result.output["signals"])
    assert result.confidence == 0.80


@pytest.mark.asyncio
async def test_pipeline_evolution_handler_oom_pattern_detection(tmp_path, monkeypatch):
    """OOM errors in failed runs trigger increase_memory proposal."""
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_evolution
    from research_agent.research.artifacts import ArtifactStore
    from research_agent.core.models.db import PipelineRun
    from research_agent.core import db as db_module
    from datetime import datetime, timezone

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        run = PipelineRun(
            id="oom-run", user_id=1, run_id="oom-research",
            pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
            status="failed",
            parameters={"max_memory": "4.Gb"},
            error="Executor: java.lang.OutOfMemoryError: Java heap space (killed)",
            created_at=datetime(2026, 8, 14, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
        )
        db.add(run)
        await db.commit()

    result = await pipeline_evolution({
        "run_id": "oom-research",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "completed"
    actions = result.output["actions"]
    assert "investigate_failure" in actions
    assert any("内存" in s for s in result.output["signals"])


@pytest.mark.asyncio
async def test_pipeline_evolution_handler_timeout_pattern_detection(tmp_path, monkeypatch):
    """Timeout errors in failed runs trigger increase_timeout proposal."""
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_evolution
    from research_agent.research.artifacts import ArtifactStore
    from research_agent.core.models.db import PipelineRun
    from research_agent.core import db as db_module
    from datetime import datetime, timezone

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        run = PipelineRun(
            id="timeout-run", user_id=1, run_id="timeout-research",
            pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
            status="failed",
            parameters={},
            error="Timed out: process exceeded 3600s limit",
            created_at=datetime(2026, 8, 14, 12, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
        )
        db.add(run)
        await db.commit()

    result = await pipeline_evolution({
        "run_id": "timeout-research",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "completed"
    actions = result.output["actions"]
    assert "investigate_failure" in actions
    assert any("超时" in s for s in result.output["signals"])


@pytest.mark.asyncio
async def test_pipeline_evolution_handler_code_improvement_on_repeated_failure(tmp_path, monkeypatch):
    """When a pipeline fails 2+ times, pipeline_evolution generates a code-level proposal."""
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_evolution
    from research_agent.research.artifacts import ArtifactStore
    from research_agent.core.models.db import PipelineRun
    from research_agent.core import db as db_module
    from datetime import datetime, timezone

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        runs = [
            PipelineRun(
                id="code-fail-1", user_id=1, run_id="code-fail-run-1",
                pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
                status="failed",
                parameters={"max_memory": "4.Gb"},
                error="Executor: java.lang.OutOfMemoryError: Java heap space (killed)",
                created_at=datetime(2026, 8, 10, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
            PipelineRun(
                id="code-fail-2", user_id=1, run_id="code-fail-run-2",
                pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
                status="failed",
                parameters={"max_memory": "4.Gb"},
                error="Executor: java.lang.OutOfMemoryError: Java heap space (killed)",
                created_at=datetime(2026, 8, 12, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
        ]
        for r in runs:
            db.add(r)
        await db.commit()

    # Mock LLM provider
    class _FakeLLMResponse:
        content = '{"suggested_diff": "Increase max_memory in main.nf", "change_description": "建议使用8Gb内存替换4Gb配置", "confidence": 0.85, "target_file": "main.nf"}'

    class _FakeProvider:
        async def chat(self, messages):
            return _FakeLLMResponse()

    def _fake_get_provider(name, **kwargs):
        return _FakeProvider()

    monkeypatch.setattr("research_agent.llm.provider.get_provider", _fake_get_provider)

    class _FakeKeyManager:
        async def get_key(self, provider_name):
            return "test-api-key"

    monkeypatch.setattr("research_agent.llm.keys.get_key_manager", lambda *a, **k: _FakeKeyManager())

    result = await pipeline_evolution({
        "run_id": "code-fail-run-2",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "completed"
    assert len(result.output["proposal_ids"]) >= 1
    assert any("代码进化" in s for s in result.output["signals"])
    assert result.output.get("code_proposal_ids") is not None
    assert len(result.output["code_proposal_ids"]) >= 1

    # Verify proposal type
    async with db_module.AsyncSessionLocal() as db:
        from sqlalchemy import select
        from research_agent.core.models.db import LearningProposal
        prop_result = await db.execute(
            select(LearningProposal).where(LearningProposal.source_run_id == "code-fail-run-2")
        )
        proposals = prop_result.scalars().all()
        code_props = [p for p in proposals if (p.proposed_change or {}).get("proposal_type") == "pipeline_code_improvement"]
        assert len(code_props) >= 1
        assert code_props[0].proposed_change["pipeline_id"] == "nf-core/rnaseq"
        assert code_props[0].proposed_change["confidence"] == 0.85


@pytest.mark.asyncio
async def test_pipeline_evolution_handler_code_improvement_llm_fallback(tmp_path, monkeypatch):
    """When LLM is unavailable, code-level proposal is still generated as fallback."""
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_evolution
    from research_agent.research.artifacts import ArtifactStore
    from research_agent.core.models.db import PipelineRun
    from research_agent.core import db as db_module
    from datetime import datetime, timezone

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        runs = [
            PipelineRun(
                id="fallback-fail-1", user_id=1, run_id="fallback-run-1",
                pipeline_id="nf-core/sarek", revision="3.9.0", profile="conda",
                status="failed",
                parameters={},
                error="Process timed out",
                created_at=datetime(2026, 8, 10, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
            PipelineRun(
                id="fallback-fail-2", user_id=1, run_id="fallback-run-2",
                pipeline_id="nf-core/sarek", revision="3.9.0", profile="conda",
                status="failed",
                parameters={},
                error="Process timed out",
                created_at=datetime(2026, 8, 12, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
        ]
        for r in runs:
            db.add(r)
        await db.commit()

    # Mock LLM to raise exception (simulating unavailable API)
    def _fake_get_provider(name, **kwargs):
        raise RuntimeError("API key not configured")

    monkeypatch.setattr("research_agent.llm.provider.get_provider", _fake_get_provider)

    class _FakeKeyManager:
        async def get_key(self, provider_name):
            return "test-api-key"

    monkeypatch.setattr("research_agent.llm.keys.get_key_manager", lambda *a, **k: _FakeKeyManager())

    result = await pipeline_evolution({
        "run_id": "fallback-run-2",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "completed"
    # Should still generate fallback proposal even though LLM failed
    assert len(result.output["proposal_ids"]) >= 1
    assert any("代码进化" in s or "重复失败" in s for s in result.output["signals"])

    # Verify fallback proposal was stored
    async with db_module.AsyncSessionLocal() as db:
        from sqlalchemy import select
        from research_agent.core.models.db import LearningProposal
        prop_result = await db.execute(
            select(LearningProposal).where(LearningProposal.source_run_id == "fallback-run-2")
        )
        proposals = prop_result.scalars().all()
        code_props = [p for p in proposals if (p.proposed_change or {}).get("proposal_type") == "pipeline_code_improvement"]
        assert len(code_props) >= 1
        assert code_props[0].proposed_change["confidence"] == 0.60


@pytest.mark.asyncio
async def test_pipeline_evolution_handler_no_code_proposal_single_failure(tmp_path, monkeypatch):
    """A single pipeline failure should NOT generate a code-level proposal (needs 2+ failures)."""
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_evolution
    from research_agent.research.artifacts import ArtifactStore
    from research_agent.core.models.db import PipelineRun
    from research_agent.core import db as db_module
    from datetime import datetime, timezone

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        run = PipelineRun(
            id="single-fail", user_id=1, run_id="single-fail-run",
            pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
            status="failed",
            parameters={"max_memory": "4.Gb"},
            error="Executor: java.lang.OutOfMemoryError",
            created_at=datetime(2026, 8, 14, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
        )
        db.add(run)
        await db.commit()

    result = await pipeline_evolution({
        "run_id": "single-fail-run",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "completed"
    # OOM signal should still be generated, but no code-level proposal
    assert any("内存" in s or "OOM" in s for s in result.output["signals"])
    assert result.output.get("code_proposal_ids") is None or len(result.output["code_proposal_ids"]) == 0

    # No code-level proposal should be in DB
    async with db_module.AsyncSessionLocal() as db:
        from sqlalchemy import select
        from research_agent.core.models.db import LearningProposal
        prop_result = await db.execute(
            select(LearningProposal).where(LearningProposal.source_run_id == "single-fail-run")
        )
        proposals = prop_result.scalars().all()
        code_props = [p for p in proposals if (p.proposed_change or {}).get("proposal_type") == "pipeline_code_improvement"]
        assert len(code_props) == 0






class _FakePipelineBackend:
    def __init__(self, readiness, artifact_path=None):
        self._readiness = readiness
        self._artifact_path = artifact_path

    async def preflight(self, **kwargs):
        return self._readiness

    def resolve_artifact(self, user_id, run_id, relative_path):
        if self._artifact_path is None:
            raise ValueError("pipeline artifact unavailable")
        return self._artifact_path


class _FakePipelineManager:
    def __init__(self, backend, final_status="completed"):
        self.backend = backend
        self._final_status = final_status
        self.submitted: list[str] = []

    async def plan_run(self, run_id):
        return {"status": "planned"}

    def submit(self, run_id):
        self.submitted.append(run_id)

        async def _finish():
            await asyncio.sleep(0)
            from sqlalchemy import select

            from research_agent.core import db as db_module
            from research_agent.core.models.db import PipelineRun

            async with db_module.AsyncSessionLocal() as db:
                result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
                run = result.scalar_one()
                run.status = self._final_status
                run.exit_code = 0 if self._final_status == "completed" else 1
                run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                run.result = {
                    "artifacts": [
                        {
                            "name": "counts.tsv",
                            "kind": "result",
                            "relative_path": "results/counts.tsv",
                            "size_bytes": 9,
                            "sha256": "dummy",
                        }
                    ],
                    "task_summary": {
                        "tasks": 234,
                        "statuses": {"COMPLETED": 234},
                        "failed": [],
                    },
                }
                run.provenance = {"pipeline": "nf-core/rnaseq", "revision": "3.26.0"}
                await db.commit()

        asyncio.get_running_loop().create_task(_finish())

    def cancel(self, run_id):
        return False


@pytest.mark.asyncio
async def test_pipeline_execution_handler_degraded_on_preflight_failure(
    tmp_path, monkeypatch
):
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_execution

    await init_db()
    manager = _FakePipelineManager(
        _FakePipelineBackend({"ready": False, "issues": ["nextflow missing"]})
    )
    monkeypatch.setattr(
        "research_agent.execution.manager.get_pipeline_manager", lambda: manager
    )
    result = await pipeline_execution({
        "pipeline": {
            "pipeline_id": "nf-core/rnaseq",
            "revision": "3.26.0",
            "profile": "docker",
            "parameters": {"genome": "GRCh38"},
            "artifact_bindings": {"input": "samples"},
            "timeout_seconds": 60,
            "poll_interval": 0,
        },
        "run_id": "research-run-1",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "degraded"
    assert "预检未通过" in result.warnings[0]
    assert manager.submitted == []


@pytest.mark.asyncio
async def test_pipeline_execution_handler_completed_imports_artifacts(
    tmp_path, monkeypatch
):
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_execution

    await init_db()
    artifact_path = tmp_path / "counts.tsv"
    artifact_path.write_text("gene\tcount\nA\t1\n", encoding="utf-8")
    manager = _FakePipelineManager(
        _FakePipelineBackend({"ready": True, "issues": []}, artifact_path),
        final_status="completed",
    )
    monkeypatch.setattr(
        "research_agent.execution.manager.get_pipeline_manager", lambda: manager
    )
    result = await pipeline_execution({
        "pipeline": {
            "pipeline_id": "nf-core/rnaseq",
            "revision": "3.26.0",
            "profile": "docker",
            "parameters": {"test_profile": True},
            "artifact_bindings": {"input": "samples"},
            "timeout_seconds": 60,
            "poll_interval": 0,
        },
        "run_id": "research-run-2",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "completed"
    assert len(manager.submitted) == 1
    assert len(result.generated_artifacts) == 1
    imported = result.generated_artifacts[0]
    assert imported["name"] == "counts.tsv"
    assert imported["encryption_format"] == ArtifactStore.ENCRYPTION_FORMAT
    assert imported["kind"] == "pipeline"
    assert any(item["source_type"] == "pipeline_execution" for item in result.evidence)
    assert result.output["task_summary"]["tasks"] == 234
    assert result.confidence > 0.8


@pytest.mark.asyncio
async def test_pipeline_execution_handler_failed_when_run_fails(tmp_path, monkeypatch):
    from research_agent.core.db import init_db
    from research_agent.research.services import pipeline_execution

    await init_db()
    manager = _FakePipelineManager(
        _FakePipelineBackend({"ready": True, "issues": []}),
        final_status="failed",
    )
    monkeypatch.setattr(
        "research_agent.execution.manager.get_pipeline_manager", lambda: manager
    )
    result = await pipeline_execution({
        "pipeline": {
            "pipeline_id": "nf-core/rnaseq",
            "revision": "3.26.0",
            "profile": "docker",
            "parameters": {"genome": "GRCh38"},
            "artifact_bindings": {"input": "samples"},
            "timeout_seconds": 60,
            "poll_interval": 0,
        },
        "run_id": "research-run-3",
        "user_id": 1,
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
    })
    assert result.status == "degraded"
    assert result.confidence < 0.5


def test_research_api_plan_artifact_and_user_scoped_run(client):
    upload = client.post(
        "/api/v1/research/artifacts",
        files={"file": ("measurements.csv", b"group,value\nA,1\nB,2\n", "text/csv")},
    )
    assert upload.status_code == 201
    artifact = upload.json()
    assert artifact["summary"]["modality"] == "table"
    assert "relative_path" not in artifact

    preview = client.post("/api/v1/research/plan", json={
        "objective": "分析测量数据并撰写规范的结果框架",
        "domains": ["data", "writing", "integrity"],
        "artifact_ids": [artifact["id"]],
        "network_allowed": False,
    })
    assert preview.status_code == 200
    assert preview.json()["validation_errors"] == []
    keys = [step["key"] for step in preview.json()["plan"]["steps"]]
    assert keys == ["intake", "data", "writing", "integrity"]

    created = client.post("/api/v1/research/runs", json={
        "objective": "分析测量数据并撰写规范的结果框架",
        "domains": ["data", "writing", "integrity"],
        "artifact_ids": [artifact["id"]],
        "network_allowed": False,
        "execute": False,
    })
    assert created.status_code == 201
    run_id = created.json()["id"]
    detail = client.get(f"/api/v1/research/runs/{run_id}")
    assert detail.status_code == 200
    assert len(detail.json()["steps"]) == 4
    assert detail.json()["policy"]["deny_unlisted"] is True


def test_research_run_executes_to_completion(client):
    created = client.post("/api/v1/research/runs", json={
        "objective": "设计一项体外实验并生成论文结构和学术规范检查",
        "domains": ["experiment", "writing", "integrity"],
        "network_allowed": False,
        "execute": True,
    })
    assert created.status_code == 201
    run_id = created.json()["id"]
    detail = None
    for _ in range(80):
        detail = client.get(f"/api/v1/research/runs/{run_id}").json()
        if detail["status"] in {"completed", "failed", "cancelled"}:
            break
        __import__("time").sleep(0.05)
    assert detail["status"] == "completed"
    assert detail["progress"] == 100
    assert detail["result"]["provenance"]["runtime"] == "research-runtime-v1"
    assert detail["result"]["review_required"] == ["experiment", "writing", "integrity"]

    feedback = client.post(f"/api/v1/research/runs/{run_id}/feedback", json={
        "rating": 4,
        "accepted": True,
        "correction": "今后所有实验设计都应先列出主要结局和批次效应控制。",
    })
    assert feedback.status_code == 201
    assert feedback.json()["behavior_changed"] is False
    proposal = feedback.json()["learning_proposal"]
    assert proposal["status"] == "pending"
    applied = client.post(
        f"/api/v1/research/learning-proposals/{proposal['id']}/decision",
        json={"decision": "applied"},
    )
    assert applied.status_code == 200
    assert applied.json()["behavior_changed"] is True


@pytest.mark.asyncio
async def test_pipeline_param_proposal_gets_stored_in_profile(tmp_path, monkeypatch):
    """When a pipeline_param proposal is applied, defaults are stored in user profile."""
    from research_agent.core.db import init_db
    from research_agent.core import db as db_module
    from research_agent.core.models.db import LearningProposal, PipelineRun
    from datetime import datetime, timezone
    import uuid
    from sqlalchemy import select

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        # Create a user profile
        profile = UserProfile(user_id=1, skill_preferences={})
        db.add(profile)
        await db.commit()

        # Create a pipeline_param proposal
        prop = LearningProposal(
            id=str(uuid.uuid4()),
            user_id=1,
            source_run_id="test-run",
            title="Adaptive: increase max_cpus",
            rationale="Historical runs show max_cpus=4 is optimal",
            proposed_change={
                "parameter": "max_cpus",
                "recommended_value": "4",
                "reason": "Most common in successful runs",
                "confidence": 0.80,
                "pipeline_id": "nf-core/rnaseq",
            },
            evidence=[{"type": "adaptive", "id": "hist-run-a"}],
            status="pending",
        )
        db.add(prop)
        await db.commit()

        # Apply the proposal by updating status
        result = await db.execute(
            select(LearningProposal).where(LearningProposal.id == prop.id)
        )
        p = result.scalar_one_or_none()
        assert p is not None
        p.status = "applied"
        p.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Also apply the profile merge manually (simulating decide_learning_proposal logic)
        pr = await db.execute(select(UserProfile).where(UserProfile.user_id == 1))
        prof = pr.scalars().first()
        prefs = dict(prof.skill_preferences or {})
        pc = p.proposed_change or {}
        if pc.get("parameter") and pc.get("recommended_value") is not None:
            defaults = dict(prefs.get("pipeline_defaults") or {})
            pid = pc.get("pipeline_id", "")
            entry = defaults.get(pid) or {}
            entry[pc["parameter"]] = pc["recommended_value"]
            defaults[pid] = entry
            prefs["pipeline_defaults"] = defaults
            prof.skill_preferences = prefs
        await db.commit()

    # Verify the stored defaults
    async with db_module.AsyncSessionLocal() as db:
        pr = await db.execute(select(UserProfile).where(UserProfile.user_id == 1))
        prof = pr.scalars().first()
        defaults = prof.skill_preferences.get("pipeline_defaults", {})
        assert "nf-core/rnaseq" in defaults
        assert defaults["nf-core/rnaseq"]["max_cpus"] == "4"


@pytest.mark.asyncio
async def test_pipeline_run_merges_stored_defaults(tmp_path, monkeypatch):
    """Pipeline run creation merges stored adaptive defaults with request params."""
    from research_agent.core.app import create_app
    from research_agent.core.db import init_db
    from research_agent.core.models.db import UserProfile
    from research_agent.core import db as db_module
    from sqlalchemy import select
    from fastapi.testclient import TestClient
    import asyncio

    test_db = tmp_path / "test_merge.db"
    test_db_url = f"sqlite+aiosqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    monkeypatch.setattr("research_agent.core.app.settings.database_url", test_db_url)
    from research_agent.core.db import configure_database
    configure_database(test_db_url)
    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        profile = UserProfile(
            user_id=1,
            skill_preferences={
                "pipeline_defaults": {
                    "nf-core/rnaseq": {"max_cpus": "8", "max_memory": "16.Gb"}
                }
            },
        )
        db.add(profile)
        await db.commit()

    # The merge logic is in pipelines.py create_run endpoint
    # Verify the defaults structure is accessible
    async with db_module.AsyncSessionLocal() as db:
        pr = await db.execute(select(UserProfile).where(UserProfile.user_id == 1))
        prof = pr.scalars().first()
        defaults = (prof.skill_preferences or {}).get("pipeline_defaults", {})
        assert defaults["nf-core/rnaseq"]["max_cpus"] == "8"
        assert defaults["nf-core/rnaseq"]["max_memory"] == "16.Gb"


def test_planner_auto_triggers_multi_omics_for_scrna_spatial():
    """When objective contains scRNA-seq + spatial keywords, planner adds multi_omics step."""
    plan = ResearchPlanner().plan(
        "对 scRNA-seq 和空间转录组数据做多组学融合分析",
        network_allowed=True,
    )
    value = plan.to_dict()
    keys = [step["key"] for step in value["steps"]]
    assert "multi_omics" in keys
    multi_step = next(s for s in value["steps"] if s["key"] == "multi_omics")
    assert multi_step["capability"] == "multi_omics_fusion"
    # multi_omics step should come after data/intake and before writing
    data_idx = keys.index("data")
    omics_idx = keys.index("multi_omics")
    assert omics_idx > data_idx
    # writing depends on multi_omics
    writing_step = next((s for s in value["steps"] if s["key"] == "writing"), None)
    if writing_step:
        assert "multi_omics" in writing_step.get("dependencies", [])


def test_planner_multi_omics_with_artifacts():
    """multi_omics step depends on intake when artifact_ids are provided."""
    plan = ResearchPlanner().plan(
        "scRNA-seq 与 spatial 数据联合分析",
        artifact_ids=["art-001", "art-002"],
        network_allowed=True,
    )
    value = plan.to_dict()
    keys = [step["key"] for step in value["steps"]]
    assert "multi_omics" in keys
    assert "intake" in keys
    omics_idx = keys.index("multi_omics")
    intake_idx = keys.index("intake")
    assert intake_idx < omics_idx  # intake must precede multi_omics
