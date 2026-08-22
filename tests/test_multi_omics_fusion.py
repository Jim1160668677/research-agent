"""Tests for multi_omics_fusion handler."""
import csv

import pytest

from research_agent.research.artifacts import ArtifactStore
from research_agent.research.contracts import CAPABILITIES
from research_agent.research.services import multi_omics_fusion


@pytest.fixture
def artifact_store(tmp_path):
    return ArtifactStore(tmp_path / "artifacts")


def _make_scrna_matrix(n_genes=50, n_cells=10):
    """Generate a synthetic scRNA-seq count matrix (genes x cells)."""
    import random
    random.seed(42)
    header = ["gene_id"] + [f"cell_{i}" for i in range(n_cells)]
    rows = [header]
    for g in range(n_genes):
        row = [f"Gene{g:03d}"]
        for _ in range(n_cells):
            row.append(str(random.randint(0, 500)))
        rows.append(row)
    return rows


def _make_spatial_matrix(n_genes=50, n_spots=8):
    """Generate a synthetic spatial expression matrix (genes x spots)."""
    import random
    random.seed(43)
    header = ["gene_id"] + [f"spot_{i}" for i in range(n_spots)]
    rows = [header]
    for g in range(n_genes):
        row = [f"Gene{g:03d}"]
        for _ in range(n_spots):
            row.append(str(random.randint(10, 1000)))
        rows.append(row)
    return rows


def _save_csv(store: ArtifactStore, name: str, rows: list[list[str]]):
    path = store.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return str(path.relative_to(store.root))


@pytest.mark.asyncio
async def test_multi_omics_fusion_missing_inputs(artifact_store):
    result = await multi_omics_fusion({
        "artifact_store": artifact_store,
        "user_id": 1,
        "run_id": "run-001",
        "fusion_spec": {},
    })
    assert result.status == "degraded"
    assert "scrna_artifact" in result.output.get("required_inputs", [])
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_multi_omics_fusion_no_common_genes(artifact_store):
    scrna_rows = [["gene_id", "c1", "c2"], ["A", "10", "20"], ["B", "30", "40"]]
    spatial_rows = [["gene_id", "s1", "s2"], ["X", "100", "200"], ["Y", "300", "400"]]

    scrna_rel = _save_csv(artifact_store, "scrna.csv", scrna_rows)
    spatial_rel = _save_csv(artifact_store, "spatial.csv", spatial_rows)

    result = await multi_omics_fusion({
        "artifact_store": artifact_store,
        "user_id": 1,
        "run_id": "run-002",
        "fusion_spec": {
            "scrna_artifact": {"relative_path": scrna_rel},
            "spatial_artifact": {"relative_path": spatial_rel},
        },
    })
    assert result.status == "failed"
    assert "共同的基因" in result.output.get("message", "") or "共同" in result.output.get("message", "")


@pytest.mark.asyncio
async def test_multi_omics_fusion_success(artifact_store):
    n_genes, n_cells, n_spots = 30, 6, 4
    scrna_rows = _make_scrna_matrix(n_genes, n_cells)
    spatial_rows = _make_spatial_matrix(n_genes, n_spots)

    scrna_rel = _save_csv(artifact_store, "scrna_counts.csv", scrna_rows)
    spatial_rel = _save_csv(artifact_store, "spatial_expr.csv", spatial_rows)

    result = await multi_omics_fusion({
        "artifact_store": artifact_store,
        "user_id": 1,
        "run_id": "run-003",
        "fusion_spec": {
            "scrna_artifact": {"relative_path": scrna_rel},
            "spatial_artifact": {"relative_path": spatial_rel},
        },
    })

    assert result.status in ("completed", "degraded")
    assert result.output["fusion_status"] == "completed"
    assert result.output["common_genes"] == n_genes
    assert result.output["scrna_cells"] == n_cells
    assert result.output["spatial_spots"] == n_spots
    assert result.output["fused_matrix_shape"] == [n_genes, n_cells + n_spots]
    assert len(result.generated_artifacts) == 1
    assert "fused_matrix" in result.generated_artifacts[0]["name"]
    assert result.confidence > 0.5


@pytest.mark.asyncio
async def test_multi_omics_fusion_low_quality_warnings(artifact_store):
    rows = [["gene_id", "c1", "c2"], ["Gene000", "0", "0"], ["Gene001", "0", "0"]]
    scrna_rel = _save_csv(artifact_store, "low_quality_scrna.csv", rows)

    spatial_rows = [["gene_id", "s1"], ["Gene000", "500"], ["Gene001", "600"]]
    spatial_rel = _save_csv(artifact_store, "normal_spatial.csv", spatial_rows)

    result = await multi_omics_fusion({
        "artifact_store": artifact_store,
        "user_id": 1,
        "run_id": "run-004",
        "fusion_spec": {
            "scrna_artifact": {"relative_path": scrna_rel},
            "spatial_artifact": {"relative_path": spatial_rel},
        },
    })

    assert result.status in ("completed", "degraded")
    assert len(result.warnings) > 0
    assert any("UMI" in w or "质量" in w for w in result.warnings)


def test_capability_spec_exists():
    spec = CAPABILITIES.get("multi_omics_fusion")
    assert spec is not None
    assert spec.title == "多组学智能融合分析"
    assert spec.category == "analysis"
    assert spec.risk.value == "high"
    assert spec.writes_artifacts is True
    assert spec.requires_human_review is True
    assert spec.timeout_seconds == 300
