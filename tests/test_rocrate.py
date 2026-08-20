"""Tests for RO-Crate export functionality."""
import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest


def _make_run(objective="Test scRNA-seq analysis", status="completed", steps=None,
              evidence=None, result=None):
    return {
        "id": "run-test-001",
        "objective": objective,
        "status": status,
        "progress": 100,
        "created_at": "2026-08-19T10:00:00",
        "completed_at": "2026-08-19T11:30:00",
        "plan": {"domains": ["transcriptomics"]},
        "result": result or {"confidence": 0.92, "summary": "Analysis complete"},
        "steps": steps or [
            {
                "key": "multi_omics_fusion",
                "title": "Multi-omics Fusion",
                "capability": "multi_omics_fusion",
                "dependencies": [],
                "status": "completed",
                "confidence": 0.95,
                "duration_ms": 12000,
                "warnings": [],
                "input_data": {},
                "output_data": {"fused_matrix": "fused_matrix.csv"},
            }
        ],
        "evidence": evidence or [
            {"source_type": "pubmed", "id": "PMID-12345", "locator": "https://pubmed.ncbi.nlm.nih.gov/12345/", "summary": "Relevant study"}
        ],
        "user_id": 1,
    }


def _make_artifact(name: str, content: bytes, sha256: str, kind: str = "output", media_type: str = "text/csv") -> dict:
    return {
        "id": f"art-{name}",
        "name": name,
        "relative_path": f"user-1/run-test-001/generated/{name}",
        "media_type": media_type,
        "kind": kind,
        "size_bytes": len(content),
        "sha256": sha256,
        "encryption_format": None,
        "summary": {"modality": "table", "rows_scanned": 10, "columns": 3},
        "status": "ready",
        "created_at": "2026-08-19T11:00:00",
    }


def _make_pipeline_run(pipeline_id: str, revision: str, profile: str, status: str, error: str = "") -> dict:
    return {
        "pipeline_id": pipeline_id,
        "revision": revision,
        "profile": profile,
        "status": status,
        "task_summary": {"completed": 42, "failed": 0},
        "error": error,
        "result": {"task_summary": {"completed": 42, "failed": 0}},
    }


@pytest.mark.asyncio
async def test_rocrate_basic_structure(tmp_path):
    """RO-Crate must be a valid zip with ro-crate-metadata.json at root."""
    from research_agent.reporting.rocrate import generate_rocrate

    run = _make_run()
    artifacts = []
    pipeline_runs = [_make_pipeline_run("nf-core/rnaseq", "3.26.0", "docker", "completed")]

    crate_bytes, filename = await generate_rocrate(run, artifacts, pipeline_runs, tmp_path)

    assert filename.endswith(".zip")
    assert isinstance(crate_bytes, bytes)
    assert len(crate_bytes) > 0

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        names = zf.namelist()
        assert "ro-crate-metadata.json" in names
        metadata = json.loads(zf.read("ro-crate-metadata.json"))
        assert "@context" in metadata
        assert "https://w3id.org/ro/crate/1.1/context" == metadata["@context"]
        assert len(metadata["@graph"]) > 0

        # Main entity should be present
        main_entities = [e for e in metadata["@graph"] if e.get("@id") == "#"]
        assert len(main_entities) == 1
        main = main_entities[0]
        assert main["name"] == run["objective"]
        assert "ScholarlyArticle" in main["@type"]


@pytest.mark.asyncio
async def test_rocrate_includes_artifacts(tmp_path):
    """RO-Crate should include artifact entities and data files."""
    from research_agent.reporting.rocrate import generate_rocrate

    run = _make_run()
    csv_content = b"gene_id,c1,c2\nGeneA,10,20\nGeneB,5,15"
    sha = "f41fad8c68ce3e99b1c73ab6de41ae0a1e194a7e686392558224802e89e47255"
    artifact = _make_artifact("fused_matrix.csv", csv_content, sha)
    artifacts = [artifact]
    pipeline_runs = []

    # Write the actual CSV file to tmp_path so the store can read it back
    user_dir = tmp_path / "user-1" / "run-test-001" / "generated"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "fused_matrix.csv").write_bytes(csv_content)

    crate_bytes, _ = await generate_rocrate(run, artifacts, pipeline_runs, tmp_path)

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        names = zf.namelist()
        # Check data file is included
        data_files = [n for n in names if n.startswith("data/")]
        assert len(data_files) >= 1
        # Check artifact entity in metadata
        metadata = json.loads(zf.read("ro-crate-metadata.json"))
        artifact_entities = [e for e in metadata["@graph"] if e.get("@id", "").startswith("artifacts/")]
        assert len(artifact_entities) >= 1
        assert "fused_matrix.csv" in artifact_entities[0]["name"]


@pytest.mark.asyncio
async def test_rocrate_includes_pipeline_info(tmp_path):
    """RO-Crate should include pipeline execution entities."""
    from research_agent.reporting.rocrate import generate_rocrate

    run = _make_run()
    artifacts = []
    pipeline_runs = [
        _make_pipeline_run("nf-core/rnaseq", "3.26.0", "docker", "completed"),
        _make_pipeline_run("nf-core/sarek", "3.9.0", "docker", "failed", "Executor: java.lang.OutOfMemoryError"),
    ]

    crate_bytes, _ = await generate_rocrate(run, artifacts, pipeline_runs, tmp_path)

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        metadata = json.loads(zf.read("ro-crate-metadata.json"))
        pipeline_entities = [e for e in metadata["@graph"] if "Workflow" in (e.get("@type") or [])]
        assert len(pipeline_entities) == 2

        failed_pipeline = next(e for e in pipeline_entities if "OutOfMemory" in e.get("error", ""))
        assert failed_pipeline["status"] == "failed"


@pytest.mark.asyncio
async def test_rocrate_includes_evidence(tmp_path):
    """RO-Crate should include evidence entities."""
    from research_agent.reporting.rocrate import generate_rocrate

    evidence = [
        {"source_type": "pubmed", "id": "PMID-11111", "locator": "https://pubmed.ncbi.nlm.nih.gov/11111/", "summary": "Study A"},
        {"source_type": "genbank", "id": "GSM12345", "locator": "https://www.ncbi.nlm.nih.gov/gds/12345", "summary": "Dataset B"},
    ]
    run = _make_run(evidence=evidence)
    artifacts = []
    pipeline_runs = []

    crate_bytes, _ = await generate_rocrate(run, artifacts, pipeline_runs, tmp_path)

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        metadata = json.loads(zf.read("ro-crate-metadata.json"))
        evidence_entities = [e for e in metadata["@graph"] if e.get("@id", "").startswith("#evidence/")]
        assert len(evidence_entities) == 2
        assert evidence_entities[0]["sourceType"] == "pubmed"
        assert evidence_entities[1]["sourceType"] == "genbank"


@pytest.mark.asyncio
async def test_rocrate_includes_brief(tmp_path):
    """RO-Crate should include a brief.md file."""
    from research_agent.reporting.rocrate import generate_rocrate

    run = _make_run()
    artifacts = []
    pipeline_runs = [_make_pipeline_run("nf-core/rnaseq", "3.26.0", "docker", "completed")]

    crate_bytes, _ = await generate_rocrate(run, artifacts, pipeline_runs, tmp_path)

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        names = zf.namelist()
        assert "brief.md" in names
        brief_content = zf.read("brief.md").decode("utf-8")
        assert "研究简报" in brief_content or "Research" in brief_content


@pytest.mark.asyncio
async def test_rocrate_includes_provenance(tmp_path):
    """RO-Crate should include a provenance.json with SHA-256 of the crate itself."""
    from research_agent.reporting.rocrate import generate_rocrate

    run = _make_run()
    artifacts = []
    pipeline_runs = []

    crate_bytes, _ = await generate_rocrate(run, artifacts, pipeline_runs, tmp_path)

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        assert "provenance.json" in zf.namelist()
        prov = json.loads(zf.read("provenance.json"))
        assert "sha256Crate" in prov
        assert len(prov["sha256Crate"]) == 64
        assert prov["runId"] == run["id"]
        assert prov["generator"] == "Research Agent RO-Crate Exporter v1.0"


@pytest.mark.asyncio
async def test_rocrate_empty_run(tmp_path):
    """RO-Crate should handle empty runs gracefully."""
    from research_agent.reporting.rocrate import generate_rocrate

    run = _make_run(status="pending", steps=[], evidence=[])
    artifacts = []
    pipeline_runs = []

    crate_bytes, filename = await generate_rocrate(run, artifacts, pipeline_runs, tmp_path)

    assert isinstance(crate_bytes, bytes)
    assert filename.endswith(".zip")

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        metadata = json.loads(zf.read("ro-crate-metadata.json"))
        main = next(e for e in metadata["@graph"] if e.get("@id") == "#")
        assert main["status"] == "pending"


@pytest.mark.asyncio
async def test_rocrate_step_entities(tmp_path):
    """RO-Crate should include step entities with capability and dependencies."""
    from research_agent.reporting.rocrate import generate_rocrate

    steps = [
        {
            "key": "pipeline_execution",
            "title": "Execute nf-core/rnaseq",
            "capability": "pipeline_execution",
            "dependencies": [],
            "status": "completed",
            "confidence": 0.88,
            "duration_ms": 300000,
            "warnings": [],
            "input_data": {"pipeline_id": "nf-core/rnaseq"},
            "output_data": {"artifacts": ["counts.csv"]},
        },
        {
            "key": "reporting",
            "title": "Generate Report",
            "capability": "reporting",
            "dependencies": ["pipeline_execution"],
            "status": "completed",
            "confidence": 0.95,
            "duration_ms": 5000,
            "warnings": [],
            "input_data": {},
            "output_data": {"report": "brief.pdf"},
        },
    ]
    run = _make_run(steps=steps)
    artifacts = []
    pipeline_runs = []

    crate_bytes, _ = await generate_rocrate(run, artifacts, pipeline_runs, tmp_path)

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        metadata = json.loads(zf.read("ro-crate-metadata.json"))
        step_entities = [e for e in metadata["@graph"] if e.get("@id", "").startswith("#step/")]
        assert len(step_entities) == 2
        pipeline_step = next(e for e in step_entities if e["@id"] == "#step/pipeline_execution")
        assert pipeline_step["capability"] == "pipeline_execution"
        assert pipeline_step["dependencies"] == []
        reporting_step = next(e for e in step_entities if e["@id"] == "#step/reporting")
        assert "pipeline_execution" in reporting_step["dependencies"]


@pytest.mark.asyncio
async def test_rocrate_software_entity(tmp_path):
    """RO-Crate should include a SoftwareApplication entity for the generator."""
    from research_agent.reporting.rocrate import generate_rocrate

    run = _make_run()
    crate_bytes, _ = await generate_rocrate(run, [], [], tmp_path)

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        metadata = json.loads(zf.read("ro-crate-metadata.json"))
        software = next((e for e in metadata["@graph"] if e.get("@id") == "#software"), None)
        assert software is not None
        assert software["name"] == "Research Agent"
        assert "SoftwareApplication" in software["@type"]


@pytest.mark.asyncio
async def test_rocrate_api_endpoint_integration(tmp_path, monkeypatch):
    """Integration test: POST /research/runs/{run_id}/rocrate returns valid zip."""
    from research_agent.research.manager import get_run_manager

    # Create a minimal run in the test DB
    from research_agent.core.db import init_db, AsyncSessionLocal
    from research_agent.core.models.db import ResearchRun, ResearchRunStep, ResearchArtifact
    import uuid

    await init_db()

    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        run = ResearchRun(
            id=run_id,
            user_id=1,
            objective="Test RO-Crate export",
            status="completed",
            progress=100,
            plan={"domains": ["transcriptomics"]},
            result={"confidence": 0.9},
            evidence=[],
            policy={},
            budget={},
        )
        db.add(run)
        step = ResearchRunStep(
            run_id=run_id,
            step_key="pipeline_execution",
            order=0,
            title="Execute pipeline",
            capability="pipeline_execution",
            dependencies=[],
            status="completed",
            input_data={},
            output_data={},
            confidence=0.9,
        )
        db.add(step)
        await db.commit()

    from fastapi.testclient import TestClient
    from research_agent.core.api.research import router as research_router
    from research_agent.core.auth import create_access_token
    from unittest.mock import patch
    from fastapi import FastAPI

    token = create_access_token(user_id=1, username="test", role="researcher")
    headers = {"Authorization": f"Bearer {token}"}

    with patch("research_agent.core.api.research.get_run_manager") as mock_mgr:
        mock_store = type("MockStore", (), {"root": tmp_path})()
        mock_mgr.return_value.artifact_store = mock_store
        mock_mgr.return_value.submit = lambda x: True
        mock_mgr.return_value.cancel = lambda x: None

        app = FastAPI()
        app.include_router(research_router, prefix="/research")
        client = TestClient(app)
        resp = client.post(f"/research/runs/{run_id}/rocrate", headers=headers)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["content-disposition"].startswith("attachment")

    # Verify it's a valid zip
    with zipfile.ZipFile(BytesIO(resp.content)) as zf:
        assert "ro-crate-metadata.json" in zf.namelist()
        assert "provenance.json" in zf.namelist()
