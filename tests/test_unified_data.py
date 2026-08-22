"""Tests for unified_data module."""
import csv

import pytest

from research_agent.research.artifacts import ArtifactStore
from research_agent.research.unified_data import (
    convert_to_unified,
    log1p_zscore,
    read_matrix_from_store,
    validate_matrix,
)

# ---------------------------------------------------------------------------
# validate_matrix
# ---------------------------------------------------------------------------


def test_validate_matrix_with_feature_header():
    rows = [
        ["gene_id", "cell1", "cell2", "cell3"],
        ["GeneA", "10", "20", "30"],
        ["GeneB", "5", "15", "25"],
    ]
    features, samples, values, warnings = validate_matrix(rows, "scRNA-seq")
    assert features == ["GeneA", "GeneB"]
    assert samples == ["cell1", "cell2", "cell3"]
    assert len(values) == 2
    assert len(values[0]) == 3
    assert values[0][0] == 10.0
    assert not warnings


def test_validate_matrix_no_feature_header():
    # All-numeric header → gene_col=None → auto-generated feature IDs, all cols are values.
    rows = [
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
    ]
    features, samples, values, warnings = validate_matrix(rows, "proteomics")
    # When no feature col, all rows with valid floats are included.
    assert len(features) == 2
    assert all(f.startswith("feature_") for f in features)
    assert samples == ["1", "2", "3"]
    assert len(values) == 2
    assert len(values[0]) == 3
    assert len(warnings) > 0  # auto-generated feature IDs


def test_validate_matrix_empty():
    features, samples, values, warnings = validate_matrix([["a", "b"]], "test")
    assert features == []
    assert len(warnings) > 0


# ---------------------------------------------------------------------------
# log1p_zscore
# ---------------------------------------------------------------------------


def test_log1p_zscore_shape():
    matrix = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    result = log1p_zscore(matrix, n_samples=3)
    assert len(result) == 3
    assert all(len(row) == 3 for row in result)


def test_log1p_zscore_zero_variance():
    """All identical values → std=0, should use fallback std=1.0."""
    matrix = [[5.0, 5.0], [5.0, 5.0]]
    result = log1p_zscore(matrix, n_samples=2)
    assert len(result) == 2
    assert all(abs(v) < 100 for row in result for v in row)  # no inf/nan


def test_log1p_zscore_empty():
    assert log1p_zscore([], n_samples=0) == []


# ---------------------------------------------------------------------------
# convert_to_unified
# ---------------------------------------------------------------------------


def test_convert_to_unified_basic(tmp_path):
    rows = [
        ["gene_id", "c1", "c2"],
        ["G1", "10", "20"],
        ["G2", "30", "40"],
    ]
    unified, warnings = convert_to_unified(rows, "scRNA-seq")
    assert unified.features == ["G1", "G2"]
    assert unified.samples == ["c1", "c2"]
    assert len(unified.values) == 2
    assert unified.meta.omic_type == "scRNA-seq"


def test_convert_to_unified_persists_canonical(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    rows = [
        ["gene_id", "c1"],
        ["G1", "100"],
    ]
    # import_bytes encrypts the file; verify the UnifiedMatrix is correct instead.
    unified, warnings = convert_to_unified(
        rows, "spatial", store=store,
        artifact_relative_path="test_matrix.csv",
        user_id=1, run_id="run-1",
    )
    assert unified.features == ["G1"]
    assert unified.samples == ["c1"]
    assert unified.values == [[100.0]]
    assert unified.meta.omic_type == "spatial"
    # No warnings since the matrix is valid
    assert len(warnings) == 0


# ---------------------------------------------------------------------------
# read_matrix_from_store
# ---------------------------------------------------------------------------


def _save_csv_rows(store: ArtifactStore, name: str, rows: list[list[str]]):
    path = store.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return str(path.relative_to(store.root))


def test_read_matrix_from_store(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    rows = [
        ["gene_id", "s1", "s2"],
        ["A", "10", "20"],
        ["B", "30", "40"],
    ]
    rel = _save_csv_rows(store, "test.csv", rows)
    unified, warnings = read_matrix_from_store(
        store, {"relative_path": rel}, user_id=1, run_id="r1", omic_type="scRNA-seq",
    )
    assert unified.features == ["A", "B"]
    assert unified.samples == ["s1", "s2"]
    assert unified.values[0][0] == 10.0


def test_read_matrix_from_store_missing_file(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="矩阵读取失败"):
        read_matrix_from_store(
            store, {"relative_path": "nonexistent.csv"},
            user_id=1, run_id="r1", omic_type="scRNA-seq",
        )
