"""科研任务运行时、证据契约与工作台 API 测试。"""


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
