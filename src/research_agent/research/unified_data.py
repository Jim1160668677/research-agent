"""Unified cross-omics data layer.

Provides a common schema and shared normalization utilities so that any omics
matrix (scRNA-seq, spatial transcriptomics, proteomics, metabolomics, etc.) can
be validated, normalised and merged without coupling each handler to its own
ad-hoc logic.

Schema (wide form, gene-rows)
----------------------------
Each row = one feature (gene / protein / metabolite).
Columns 0..N-1 = samples (cells, spots, patients …).
The first column is reserved for the feature identifier; remaining columns
are numeric expression values.

Schema (long form)
------------------
Columns: feature_id | sample_id | value | omic_type | batch

Shared normaliser
-----------------
log1p + per-column z-score, identical across all omics types.
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class OmicsMatrixMeta:
    """Metadata describing an omics matrix in the unified schema."""

    feature_id_col: str = "feature_id"
    sample_ids: list[str] = field(default_factory=list)
    n_features: int = 0
    n_samples: int = 0
    omic_type: str = "unknown"
    batch: str | None = None
    platform: str | None = None


@dataclass
class UnifiedMatrix:
    """A matrix that conforms to the cross-omics unified schema."""

    features: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    values: list[list[float]] = field(default_factory=list)
    meta: OmicsMatrixMeta = field(default_factory=OmicsMatrixMeta)

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": self.features,
            "samples": self.samples,
            "values": self.values,
            "meta": asdict(self.meta),
            "shape": [len(self.features), len(self.samples)],
        }


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def log1p_zscore(matrix: list[list[Any]], n_samples: int) -> list[list[float]]:
    """Column-wise log1p + z-score normalisation.

    *matrix* is a list of rows (features); each row has ``n_samples`` numeric
    values.  The output has the same shape.
    """
    n = len(matrix)
    if n == 0 or n_samples == 0:
        return []
    col_sums = [0.0] * n_samples
    col_sq_sums = [0.0] * n_samples
    for row in matrix:
        for j, v in enumerate(row[:n_samples]):
            try:
                x = float(v)
            except (TypeError, ValueError):
                x = 0.0
            lx = math.log1p(max(x, 0.0))
            col_sums[j] += lx
            col_sq_sums[j] += lx * lx
    col_means = [s / n for s in col_sums]
    col_vars = [sq / n - m * m for sq, m in zip(col_sq_sums, col_means)]
    col_stds = [math.sqrt(max(v, 0.0)) if v > 0 else 1.0 for v in col_vars]
    result: list[list[float]] = []
    for row in matrix:
        normed = [
            round((math.log1p(max(float(row[j]), 0.0)) - col_means[j]) / col_stds[j], 6)
            for j in range(n_samples)
        ]
        result.append(normed)
    return result


# ---------------------------------------------------------------------------
# Parsing & validation
# ---------------------------------------------------------------------------


def _parse_floats(row: list[str], start: int = 0) -> list[float]:
    out: list[float] = []
    for v in row[start:]:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def validate_matrix(
    rows: list[list[str]],
    omic_type: str,
    expected_feature_col: str | None = None,
) -> tuple[list[str], list[str], list[list[float]], list[str]]:
    """Parse a CSV-like matrix and return (features, samples, values, warnings).

    Features are row labels; samples are column headers.
    Returns a 2-D list of floats with shape (n_features, n_samples).
    """
    warnings: list[str] = []
    if len(rows) < 2:
        return [], [], [], ["矩阵数据不足（少于2行）"]

    header = rows[0]
    if not header:
        return [], [], [], ["矩阵行为空"]

    # Detect whether first column is a feature label or a numeric value.
    first_cell = header[0] if header else ""
    if first_cell and not first_cell.replace(".", "").replace("-", "").replace("_", "").isdigit():
        feature_col = 0
        sample_ids = header[1:]
        value_start = 1
    else:
        feature_col = None
        sample_ids = header
        value_start = 0
        warnings.append("首列为数值，自动生成 feature_id")

    features: list[str] = []
    values: list[list[float]] = []
    valid_rows = 0
    for row in rows[1:]:
        if feature_col is not None and feature_col < len(row):
            fid = row[feature_col]
        else:
            fid = f"feature_{len(features)}"
        vals = _parse_floats(row, value_start)
        if not vals:
            continue
        features.append(fid)
        values.append(vals)
        valid_rows += 1

    n_samples = len(sample_ids) if sample_ids else (len(values[0]) if values else 0)
    if n_samples == 0:
        warnings.append("未检测到样本列")
    if valid_rows == 0:
        warnings.append("无可解析的特征行")
    if expected_feature_col and feature_col != expected_feature_col:
        warnings.append(f"特征列位置与预期不符（expected={expected_feature_col}, got={feature_col}）")

    return features, sample_ids, values, warnings


# ---------------------------------------------------------------------------
# Conversion: raw CSV -> UnifiedMatrix
# ---------------------------------------------------------------------------


def convert_to_unified(
    rows: list[list[str]],
    omic_type: str,
    store: ArtifactStore | None = None,
    artifact_relative_path: str | None = None,
    user_id: int = 0,
    run_id: str = "",
) -> tuple[UnifiedMatrix, list[str]]:
    """Read a matrix (already loaded into memory) and return a UnifiedMatrix.

    If *store* and *artifact_relative_path* are given the CSV is re-saved in
    the canonical wide-form layout so downstream handlers can read it directly.
    """
    features, samples, values, warnings = validate_matrix(rows, omic_type)
    n_samples = len(samples) or (len(values[0]) if values else 0)

    meta = OmicsMatrixMeta(
        feature_id_col="feature_id",
        sample_ids=samples or [f"sample_{i}" for i in range(n_samples)],
        n_features=len(features),
        n_samples=n_samples,
        omic_type=omic_type,
    )
    unified = UnifiedMatrix(features=features, samples=meta.sample_ids, values=values, meta=meta)

    # Persist canonical form when a store is available.
    if store is not None and artifact_relative_path and run_id:
        canonical_rows: list[list[str]] = [["feature_id"] + list(meta.sample_ids)]
        for fid, row in zip(features, values):
            canonical_rows.append([fid] + [str(v) for v in row])
        content = "\n".join(",".join(r) for r in canonical_rows) + "\n"
        store.import_bytes(
            name=artifact_relative_path,
            raw=content.encode("utf-8"),
            user_id=user_id,
            run_id=run_id,
        )

    return unified, warnings


# ---------------------------------------------------------------------------
# Read from artifact store (CSV)
# ---------------------------------------------------------------------------


def read_matrix_from_store(
    store: ArtifactStore,
    artifact_spec: dict[str, Any],
    user_id: int,
    run_id: str,
    omic_type: str,
) -> tuple[UnifiedMatrix, list[str]]:
    """Materialize a CSV artifact and convert it to a UnifiedMatrix."""
    try:
        with store.materialize({**artifact_spec, "user_id": user_id}) as path:
            rows: list[list[str]] = []
            with open(path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    rows.append(row)
    except Exception as exc:
        raise ValueError(f"{omic_type} 矩阵读取失败: {str(exc)[:200]}")

    if len(rows) < 2:
        raise ValueError(f"{omic_type} 矩阵数据不足（少于2行）")

    rel = str(artifact_spec.get("relative_path", f"{omic_type}_matrix.csv"))
    return convert_to_unified(rows, omic_type, store=store, artifact_relative_path=rel, user_id=user_id, run_id=run_id)
