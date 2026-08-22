"""End-to-end test: multi-omics fusion -> RO-Crate export via API."""
import csv
import hashlib
import json
import zipfile
from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_scrna_matrix(n_genes=50, n_cells=10):
    import random
    random.seed(42)
    header = ["gene_id"] + [f"cell_{i}" for i in range(n_cells)]
    rows = [header]
    for g in range(n_genes):
        row = [f"Gene{g:03d}"] + [str(random.randint(0, 500)) for _ in range(n_cells)]
        rows.append(row)
    return rows


def _make_spatial_matrix(n_genes=50, n_spots=8):
    import random
    random.seed(43)
    header = ["gene_id"] + [f"spot_{i}" for i in range(n_spots)]
    rows = [header]
    for g in range(n_genes):
        row = [f"Gene{g:03d}"] + [str(random.randint(10, 1000)) for _ in range(n_spots)]
        rows.append(row)
    return rows


def _save_csv(store_root, name, rows):
    path = store_root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    return str(path.relative_to(store_root))


def _make_run(objective="Multi-omics fusion test", status="completed",
              steps=None, evidence=None, result=None):
    return {
        "id": "run-e2e-001",
        "objective": objective,
        "status": status,
        "progress": 100,
        "created_at": "2026-08-19T10:00:00",
        "completed_at": "2026-08-19T11:30:00",
        "plan": {"domains": ["transcriptomics", "spatial_transcriptomics"]},
        "result": result or {"confidence": 0.92, "summary": "Fusion complete"},
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
        "evidence": evidence or [],
        "user_id": 1,
    }


def _make_artifact(name, content, sha256, kind="output", media_type="text/csv"):
    return {
        "id": f"art-{name}",
        "name": name,
        "relative_path": f"user-1/run-e2e-001/generated/{name}",
        "media_type": media_type,
        "kind": kind,
        "size_bytes": len(content),
        "sha256": sha256,
        "encryption_format": None,
        "summary": {"modality": "table", "rows_scanned": 50, "columns": 18},
        "status": "ready",
        "created_at": "2026-08-19T11:00:00",
    }


@pytest.mark.asyncio
async def test_e2e_multi_omics_fusion_to_rocrate(tmp_path):
    from research_agent.reporting.rocrate import generate_rocrate
    from research_agent.research.artifacts import ArtifactStore
    from research_agent.research.services import multi_omics_fusion

    store_root = tmp_path / "artifacts"
    store = ArtifactStore(store_root)

    scrna_rows = _make_scrna_matrix(n_genes=30, n_cells=6)
    spatial_rows = _make_spatial_matrix(n_genes=30, n_spots=4)
    scrna_rel = _save_csv(store_root, "scrna_counts.csv", scrna_rows)
    spatial_rel = _save_csv(store_root, "spatial_expr.csv", spatial_rows)

    result = await multi_omics_fusion({
        "artifact_store": store,
        "user_id": 1,
        "run_id": "run-e2e-001",
        "fusion_spec": {
            "scrna_artifact": {"relative_path": scrna_rel},
            "spatial_artifact": {"relative_path": spatial_rel},
        },
    })
    assert result.status in ("completed", "degraded")
    assert result.output["fusion_status"] == "completed"
    assert result.output["common_genes"] == 30
    assert result.output["fused_matrix_shape"] == [30, 10]

    fused_name = result.generated_artifacts[0]["name"]
    fused_content = result.generated_artifacts[0]["content"]
    art_dir = store_root / "user-1" / "run-run-e2e-001" / "generated"
    art_dir.mkdir(parents=True, exist_ok=True)
    (art_dir / fused_name).write_text(fused_content, encoding="utf-8")
    fused_path = art_dir / fused_name
    fused_bytes = fused_path.read_bytes()
    sha = hashlib.sha256(fused_bytes).hexdigest()
    artifact = _make_artifact(fused_name, fused_bytes, sha)
    artifact['relative_path'] = f'user-1/run-run-e2e-001/generated/{fused_name}'

    run = _make_run(
        objective="scRNA-seq + Spatial transcriptomics fusion",
        steps=[{
            "key": "multi_omics_fusion",
            "title": "Multi-omics Fusion",
            "capability": "multi_omics_fusion",
            "dependencies": [],
            "status": "completed",
            "confidence": result.confidence,
            "duration_ms": 12000,
            "warnings": result.warnings,
            "input_data": {"scrna": scrna_rel, "spatial": spatial_rel},
            "output_data": {"fused_matrix": result.generated_artifacts[0]["name"]},
        }],
    )

    crate_bytes, filename = await generate_rocrate(run, [artifact], [], store_root)
    assert filename.endswith(".zip")
    assert len(crate_bytes) > 0

    with zipfile.ZipFile(BytesIO(crate_bytes)) as zf:
        names = zf.namelist()
        assert "ro-crate-metadata.json" in names
        assert "provenance.json" in names
        assert "brief.md" in names

        metadata = json.loads(zf.read("ro-crate-metadata.json"))
        graph = metadata["@graph"]

        main = next(e for e in graph if e.get("@id") == "#")
        assert "ScholarlyArticle" in main["@type"]
        assert "scRNA-seq" in main["name"]

        fusion_step = next((e for e in graph if e.get("@id") == "#step/multi_omics_fusion"), None)
        assert fusion_step is not None
        assert fusion_step["capability"] == "multi_omics_fusion"
        assert fusion_step["status"] == "completed"

        art_entities = [e for e in graph if e.get("@id", "").startswith("artifacts/")]
        assert len(art_entities) >= 1
        assert "fused_matrix" in art_entities[0]["name"]

        sw = next((e for e in graph if e.get("@id") == "#software"), None)
        assert sw is not None
        assert sw["name"] == "Research Agent"

        prov = json.loads(zf.read("provenance.json"))
        assert "sha256Crate" in prov
        assert prov["runId"] == "run-e2e-001"

        data_files = [n for n in names if n.startswith("data/")]
        assert len(data_files) >= 1


@pytest.mark.asyncio
async def test_e2e_rocrate_api_via_fusion_run(tmp_path, monkeypatch):
    import uuid

    from research_agent.core.api.research import router as research_router
    from research_agent.core.auth import create_access_token
    from research_agent.core.db import AsyncSessionLocal, init_db
    from research_agent.core.models.db import ResearchRun, ResearchRunStep

    await init_db()

    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        run = ResearchRun(
            id=run_id, user_id=1,
            objective="E2E multi-omics to RO-Crate",
            status="completed", progress=100,
            plan={"domains": ["transcriptomics"]},
            result={"confidence": 0.92},
            evidence=[], policy={}, budget={},
        )
        db.add(run)
        step = ResearchRunStep(
            run_id=run_id, step_key="multi_omics_fusion", order=0,
            title="Multi-omics Fusion", capability="multi_omics_fusion",
            dependencies=[], status="completed", input_data={},
            output_data={"fused_matrix": "fused_matrix.csv"}, confidence=0.95,
        )
        db.add(step)
        await db.commit()

    store_root = tmp_path / "artifacts"
    store_root.mkdir(parents=True, exist_ok=True)
    csv_content = b"gene_id,c1,c2,spot1,spot2\nGeneA,10,20,100,200\nGeneB,5,15,50,150"
    (store_root / "fused_matrix.csv").write_bytes(csv_content)

    token = create_access_token(user_id=1, username="test", role="researcher")
    headers = {"Authorization": f"Bearer {token}"}

    with patch("research_agent.core.api.research.get_run_manager") as mock_mgr:
        mock_store = type("MockStore", (), {"root": store_root})()
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

    with zipfile.ZipFile(BytesIO(resp.content)) as zf:
        names = zf.namelist()
        assert "ro-crate-metadata.json" in names
        assert "provenance.json" in names
        metadata = json.loads(zf.read("ro-crate-metadata.json"))
        main = next(e for e in metadata["@graph"] if e.get("@id") == "#")
        assert main["runId"] == run_id
