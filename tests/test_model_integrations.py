"""DeepSeek/Agnes contracts, synchronization and scientific loop acceptance."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from research_agent.llm.provider import (
    AgnesCLIProvider,
    DeepSeekProvider,
    LLMMessage,
    LLMProviderError,
    get_provider,
)
from research_agent.research.planner import ResearchPlanner
from research_agent.runtime_coordinator import RuntimeCoordinator


def test_registry_uses_current_deepseek_and_agnes_models():
    assert DeepSeekProvider.models == ["deepseek-v4-pro", "deepseek-v4-flash"]
    assert AgnesCLIProvider.models == ["agnes-2.0-flash"]
    assert get_provider("deepseek").default_base_url == "https://api.deepseek.com"
    with pytest.raises(ValueError, match="不支持模型"):
        get_provider("deepseek", model="deepseek-chat")


@pytest.mark.asyncio
async def test_deepseek_payload_and_response_normalization(monkeypatch):
    create = AsyncMock(
        return_value=SimpleNamespace(
            model="deepseek-v4-pro",
            choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create = create
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **_: fake_client)

    provider = DeepSeekProvider(api_key="deepseek-test-key", config={"max_retries": 0})
    result = await provider.chat([LLMMessage("user", "question")])

    assert result.content == "answer"
    assert result.usage["total_tokens"] == 5
    request = create.await_args.kwargs
    assert request["reasoning_effort"] == "high"
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}


@pytest.mark.asyncio
async def test_deepseek_retries_only_retriable_failures(monkeypatch):
    create = AsyncMock(
        side_effect=[
            LLMProviderError(
                "busy", provider="deepseek", code="upstream_unavailable", retriable=True
            ),
            SimpleNamespace(
                model="deepseek-v4-flash",
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=None,
            ),
        ]
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create = create
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **_: fake_client)
    provider = DeepSeekProvider(
        api_key="deepseek-test-key",
        model="deepseek-v4-flash",
        config={"max_retries": 1, "retry_min_seconds": 0, "retry_max_seconds": 0},
    )
    response = await provider.chat([LLMMessage("user", "q")])
    assert response.attempts == 2
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_agnes_cli_uses_argument_vector_and_normalizes_json(monkeypatch):
    provider = AgnesCLIProvider(
        api_key="agnes-test-key",
        config={"cli_command": ["agnes-test"], "max_retries": 0},
    )
    calls = []

    async def fake_process(arguments, *, timeout):
        calls.append((arguments, timeout))
        if arguments == ["--version"]:
            return 0, "0.1.5\n", ""
        return (
            0,
            json.dumps(
                {
                    "ok": True,
                    "model": "agnes-2.0-flash",
                    "text": " pong ",
                    "raw": {
                        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
                    },
                }
            ),
            "",
        )

    monkeypatch.setattr(provider, "_process", fake_process)
    result = await provider.chat([LLMMessage("system", "safe"), LLMMessage("user", "ping")])
    assert result.content == "pong"
    assert result.usage["total_tokens"] == 3
    assert calls[1][0][:2] == ["text", "chat"]
    assert "--json" in calls[1][0]
    prompt = calls[1][0][calls[1][0].index("--prompt") + 1]
    assert "\n" not in prompt
    assert "[User]" in prompt


@pytest.mark.asyncio
async def test_agnes_rejects_incompatible_cli(monkeypatch):
    provider = AgnesCLIProvider(api_key="agnes-test-key", config={"cli_command": ["agnes-test"]})

    async def fake_process(arguments, *, timeout):
        return 0, "0.2.0\n", ""

    monkeypatch.setattr(provider, "_process", fake_process)
    with pytest.raises(LLMProviderError) as error:
        await provider.chat([LLMMessage("user", "ping")])
    assert error.value.code == "incompatible_runtime"


@pytest.mark.asyncio
async def test_runtime_coordinator_enforces_process_wide_limit():
    coordinator = RuntimeCoordinator(max_concurrency=2)
    active = 0
    peak = 0

    async def work(index):
        nonlocal active, peak
        async with coordinator.lease("test", str(index)):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(work(index) for index in range(8)))
    snapshot = await coordinator.snapshot()
    assert peak == 2
    assert snapshot["active"] == 0
    assert snapshot["completed_operations"] == 8


def test_discovery_plan_is_valid_persistent_quality_loop():
    plan = (
        ResearchPlanner()
        .plan(
            "基于已有文献生成可检验的新机制假设并设计验证实验",
            domains=["literature", "discovery", "experiment", "writing", "integrity"],
        )
        .to_dict()
    )
    assert ResearchPlanner.validate_plan(plan) == []
    keys = [step["key"] for step in plan["steps"]]
    assert keys == [
        "literature",
        "generation",
        "reflection",
        "ranking",
        "evolution",
        "meta_review",
        "experiment",
        "writing",
        "integrity",
    ]
    ranking = next(step for step in plan["steps"] if step["key"] == "ranking")
    assert ranking["dependencies"] == ["generation", "reflection"]


def test_provider_status_preference_and_runtime_routes(api_client):
    status = api_client.get("/api/v1/llm/status")
    assert status.status_code == 200
    data = status.json()
    assert {"deepseek", "agnes"} <= set(data["available_providers"])
    descriptors = {item["name"]: item for item in data["provider_descriptors"]}
    assert descriptors["agnes"]["execution_mode"] == "cli"

    health = api_client.post("/api/v1/llm/providers/deepseek/health?live=false")
    assert health.status_code == 200
    assert health.json()["code"] == "missing_api_key"

    unconfigured_preference = api_client.put(
        "/api/v1/llm/preference",
        json={
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
        },
    )
    assert unconfigured_preference.status_code == 409

    saved = api_client.post(
        "/api/v1/llm/keys",
        json={"provider": "deepseek", "api_key": "test-deepseek-key-123456"},
    )
    assert saved.status_code == 200
    preference = api_client.put(
        "/api/v1/llm/preference",
        json={"provider": "deepseek", "model": "deepseek-v4-pro"},
    )
    assert preference.status_code == 200
    assert api_client.get("/api/v1/llm/status").json()["preferred"]["provider"] == "deepseek"

    health = api_client.post("/api/v1/llm/providers/deepseek/health?live=false")
    assert health.status_code == 200
    assert health.json()["code"] == "configured"

    runtime = api_client.get("/api/v1/system/runtime")
    assert runtime.status_code == 200
    assert {"active", "waiting", "research_run_ids", "workflow_run_ids", "pipeline_run_ids"} <= set(
        runtime.json()
    )


def test_complete_co_scientist_business_flow(api_client):
    """Run the complete persistent quality loop without external network variance."""
    created = api_client.post(
        "/api/v1/research/runs",
        json={
            "objective": "基于已知炎症通路生成可检验的新机制假设，设计验证实验并形成规范研究简报",
            "domains": ["literature", "discovery", "experiment", "writing", "integrity"],
            "context": {
                "literature_records": [
                    {
                        "pmid": "10001",
                        "title": "Inflammatory pathway and target response",
                        "abstract": "The pathway is associated with a measurable target response.",
                        "year": "2025",
                    },
                    {
                        "pmid": "10002",
                        "title": "Rescue experiments for inflammatory mechanisms",
                        "abstract": "Perturbation and rescue distinguish alternative mechanisms.",
                        "year": "2024",
                    },
                ],
            },
            "network_allowed": True,
            "max_concurrency": 3,
            "execute": True,
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    detail = None
    for _ in range(120):
        detail = api_client.get(f"/api/v1/research/runs/{run_id}").json()
        if detail["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            break
        time.sleep(0.05)

    assert detail["status"] == "completed"
    assert detail["progress"] == 100
    steps = {item["key"]: item for item in detail["steps"]}
    assert all(
        steps[key]["status"] in {"completed", "degraded"}
        for key in (
            "literature",
            "generation",
            "reflection",
            "ranking",
            "evolution",
            "meta_review",
            "experiment",
            "writing",
            "integrity",
        )
    )
    assert steps["ranking"]["output"]["rubric_version"] == "scientific-quality-v1"
    assert steps["evolution"]["output"]["lineage_preserved"] is True
    assert steps["meta_review"]["output"]["human_review_required"] is True
    assert detail["result"]["provenance"]["runtime"] == "research-runtime-v1"


@pytest.mark.asyncio
async def test_research_and_workflow_startup_recovery():
    from research_agent.core import db as db_module
    from research_agent.core.models.db import (
        ResearchRun,
        ResearchRunStep,
        User,
        Workflow,
        WorkflowRun,
        WorkflowStep,
    )
    from research_agent.research.manager import recover_research_runs
    from research_agent.workflows.engine import WorkflowEngine

    await db_module.init_db()
    async with db_module.AsyncSessionLocal() as db:
        db.add(User(id=1, username="recover", email="recover@example.org", hashed_password="x"))
        db.add(
            Workflow(
                id=7001,
                name="recover workflow",
                definition={"nodes": [{"name": "one"}], "edges": []},
                author=1,
                status="active",
            )
        )
        db.add(
            ResearchRun(
                id="00000000-0000-0000-0000-000000000001",
                user_id=1,
                objective="recover research",
                status="running",
                plan={},
                context={},
                result={},
                evidence=[],
                policy={},
                budget={},
                progress=20,
            )
        )
        db.add(
            ResearchRunStep(
                run_id="00000000-0000-0000-0000-000000000001",
                step_key="one",
                order=0,
                title="one",
                capability="integrity_check",
                status="running",
            )
        )
        db.add(WorkflowRun(id=9001, workflow_id=7001, user_id=1, status="running", inputs={}))
        db.add(WorkflowStep(run_id=9001, node_name="one", order=0, status="running"))
        await db.commit()

    assert await recover_research_runs() == 1
    assert await WorkflowEngine.recover_interrupted_runs() == 1
    async with db_module.AsyncSessionLocal() as db:
        research = (await db.execute(select(ResearchRun))).scalar_one()
        workflow = (await db.execute(select(WorkflowRun))).scalar_one()
        assert research.status == "interrupted"
        assert research.result["has_gaps"] is True
        assert workflow.status == "interrupted"


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient

    from research_agent.core.app import create_app

    with TestClient(create_app()) as client:
        yield client
