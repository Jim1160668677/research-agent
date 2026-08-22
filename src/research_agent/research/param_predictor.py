"""Active parameter prediction model for scientific pipelines.

Predicts optimal pipeline parameters by learning from historical run data.
Supports both proactive (pre-execution) and reactive (post-failure) modes.

Design:
- Weighted scoring: successful runs contribute +score, failed runs contribute -score
- Recency weighting: recent runs count more than old ones
- Confidence bounds: low-sample predictions have lower confidence
- Failure pattern detection: OOM, timeout, argument errors produce targeted fixes
"""

from __future__ import annotations

import hashlib
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class _WeightedParam:
    """A single parameter's history of observed values with success/failure labels."""

    name: str
    values: list[tuple[Any, bool]] = field(default_factory=list)  # (value_str, was_success)


@dataclass
class PredictionContext:
    """Runtime context for parameter prediction."""

    user_id: int
    pipeline_id: str
    revision: str
    profile: str
    system_memory_gb: float = 32.0
    system_cpus: int = 8
    sample_count: int = 0
    data_type: str = ""  # e.g. "rnaseq", "scRNA", "variant"
    prior_parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParamRecommendation:
    """A single parameter recommendation."""

    parameter: str
    recommended_value: str
    reason: str
    confidence: float  # 0.0–1.0
    source: str  # "historical_success" | "failure_fix" | "system_constraint" | "fallback"


@dataclass
class PredictionResult:
    """Full parameter prediction result."""

    pipeline_id: str
    revision: str
    recommendations: list[ParamRecommendation] = field(default_factory=list)
    confidence: float = 0.0
    historical_runs_analyzed: int = 0
    model_version: str = "1.0"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "revision": self.revision,
            "recommendations": [
                {
                    "parameter": r.parameter,
                    "recommended_value": r.recommended_value,
                    "reason": r.reason,
                    "confidence": r.confidence,
                    "source": r.source,
                }
                for r in self.recommendations
            ],
            "confidence": self.confidence,
            "historical_runs_analyzed": self.historical_runs_analyzed,
            "model_version": self.model_version,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Historical data loader
# ---------------------------------------------------------------------------

async def load_historical_runs(user_id: int, pipeline_id: str, revision: str) -> list[dict[str, Any]]:
    """Load historical pipeline runs for a given pipeline/revision from the DB."""
    from sqlalchemy import select

    from ..core import db as db_module
    from ..core.models.db import PipelineRun

    async with db_module.AsyncSessionLocal() as db:
        result = await db.execute(
            select(PipelineRun)
            .where(PipelineRun.user_id == user_id)
            .where(PipelineRun.pipeline_id == pipeline_id)
            .where(PipelineRun.revision == revision)
            .order_by(PipelineRun.created_at.asc())
        )
        runs = result.scalars().all()

    records = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for r in runs:
        params = r.parameters or {}
        # Normalize parameter values to strings for consistent hashing
        norm_params = {k: _normalize_param_value(v) for k, v in params.items()}
        records.append({
            "id": r.id,
            "run_id": r.run_id,
            "status": r.status,
            "parameters": norm_params,
            "error": r.error or "",
            "exit_code": r.exit_code,
            "created_at": r.created_at or now,
            "elapsed_seconds": _compute_elapsed(r.started_at, r.completed_at),
        })
    return records


def _normalize_param_value(v: Any) -> str:
    """Normalize a parameter value to a stable string representation."""
    if v is None:
        return "None"
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int | float):
        return str(v)
    return str(v)


def _compute_elapsed(started: datetime | None, completed: datetime | None) -> float | None:
    if started and completed:
        delta = (completed - started).total_seconds()
        return max(delta, 0.0)
    return None


# ---------------------------------------------------------------------------
# Core predictor
# ---------------------------------------------------------------------------

def predict_parameters(
    context: PredictionContext,
    historical_runs: list[dict[str, Any]] | None = None,
) -> PredictionResult:
    """Predict optimal parameters based on historical run data.

    Algorithm:
    1. Collect all parameters observed across historical runs
    2. For each parameter, compute success-weighted score per value
    3. Apply recency weighting (exponential decay)
    4. Apply system constraint overrides (e.g. memory < system RAM)
    5. Generate recommendations sorted by confidence
    """
    if historical_runs is None:
        historical_runs = []

    recommendations: list[ParamRecommendation] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if not historical_runs:
        # No historical data — return fallback recommendations based on system constraints
        recommendations.extend(_system_constraint_fallback(context))
        return PredictionResult(
            pipeline_id=context.pipeline_id,
            revision=context.revision,
            recommendations=recommendations,
            confidence=0.30,
            historical_runs_analyzed=0,
            warnings=["No historical runs available; using system-constraint defaults"],
        )

    # --- Build per-parameter statistics ---
    param_stats: dict[str, _WeightedParam] = {}
    for run in historical_runs:
        params = run.get("parameters") or {}
        success = run["status"] == "completed"
        for key, val in params.items():
            if key in ("test_profile", "offline", "profile"):
                continue  # Skip boolean flags and common non-predictive params
            if key not in param_stats:
                param_stats[key] = _WeightedParam(name=key)
            param_stats[key].values.append((val, success))

    # --- Score each parameter value ---
    for param_name, stats in param_stats.items():
        if not stats.values:
            continue

        # Group by value
        value_scores: dict[str, list[bool]] = {}
        for val_str, was_success in stats.values:
            value_scores.setdefault(val_str, []).append(was_success)

        # Compute weighted score per value (recency decay)
        sorted_runs = sorted(historical_runs, key=lambda r: r["created_at"], reverse=True)
        best_value = None
        best_score = -float("inf")
        best_confidence = 0.0

        for val_str, outcomes in value_scores.items():
            success_count = sum(1 for o in outcomes if o)
            fail_count = len(outcomes) - success_count
            total = len(outcomes)

            # Base score: (successes - failures) * recency_weight
            recency_weight = _recency_weight(sorted_runs, outcomes, now)
            score = (success_count - fail_count) * recency_weight

            # Confidence: higher with more samples and clearer signal
            signal_strength = abs(success_count - fail_count)
            sample_bonus = min(total / 5.0, 1.0)  # Cap at 5 samples
            confidence = min(0.5 + 0.1 * signal_strength + 0.05 * sample_bonus, 0.95)

            if score > best_score:
                best_score = score
                best_value = val_str
                best_confidence = round(confidence, 2)

        if best_value is not None and best_score > 0:
            # Check if this value would violate system constraints
            constrained_val = _apply_system_constraints(
                param_name, best_value, context, historical_runs
            )
            if constrained_val != best_value:
                recommendations.append(ParamRecommendation(
                    parameter=param_name,
                    recommended_value=constrained_val,
                    reason=f"Historical best: {best_value}, constrained by system resources",
                    confidence=best_confidence * 0.8,
                    source="system_constraint",
                ))
            else:
                recommendations.append(ParamRecommendation(
                    parameter=param_name,
                    recommended_value=best_value,
                    reason=f"Most effective value in {len(stats.values)} historical runs (success: {sum(1 for _,s in stats.values if s)}x)",
                    confidence=best_confidence,
                    source="historical_success",
                ))

    # --- Failure-driven recommendations ---
    failed_runs = [r for r in historical_runs if r["status"] == "failed"]
    for run in failed_runs[-5:]:  # Last 5 failures
        recommendations.extend(_failure_fix_recommendations(run, context))

    # --- Merge with prior parameters (don't override explicit user choices) ---
    final_recommendations = _merge_with_prior(recommendations, context.prior_parameters)

    # --- Compute overall confidence ---
    overall_confidence = _compute_overall_confidence(final_recommendations, len(historical_runs))

    return PredictionResult(
        pipeline_id=context.pipeline_id,
        revision=context.revision,
        recommendations=final_recommendations,
        confidence=overall_confidence,
        historical_runs_analyzed=len(historical_runs),
        warnings=_build_warnings(final_recommendations, len(historical_runs)),
    )


def _recency_weight(sorted_runs: list[dict], outcomes: list[bool], now: datetime) -> float:
    """Compute a recency weight for a set of outcomes based on their run timestamps."""
    if not outcomes:
        return 1.0
    # Simplified: if most outcomes are from recent runs (last 30 days), boost weight
    recent_threshold = now - timedelta(days=30)
    recent_count = sum(
        1 for r, o in zip(sorted_runs, outcomes, strict=False)
        if r.get("created_at", now) >= recent_threshold and o
    )
    total_recent = sum(1 for r in sorted_runs if r.get("created_at", now) >= recent_threshold)
    if total_recent > 0 and recent_count / total_recent > 0.5:
        return 1.3
    return 1.0


def _apply_system_constraints(
    param_name: str, value: str, context: PredictionContext, runs: list[dict]
) -> str:
    """Apply system resource constraints to a recommended value."""
    # Memory parameters
    mem_match = re.match(r"^([\d.]+)\s*([A-Za-z]*)$", value, re.IGNORECASE)
    if mem_match and param_name in ("max_memory", "memory", "memory_gb"):
        num = float(mem_match.group(1))
        unit = (mem_match.group(2) or "Gb").lower()
        if unit in ("kb", "mb"):
            num /= 1024 if unit == "mb" else 1048576
        # Ensure recommended memory <= 80% of system RAM
        if num > context.system_memory_gb * 0.8:
            safe_mem = int(context.system_memory_gb * 0.75)
            return f"{safe_mem}.Gb"

    # CPU parameters
    cpu_match = re.match(r"^(\d+)$", value)
    if cpu_match and param_name in ("max_cpus", "cpu", "threads"):
        cpus = int(cpu_match.group(1))
        if cpus > context.system_cpus:
            return str(context.system_cpus)

    return value


def _failure_fix_recommendations(run: dict, context: PredictionContext) -> list[ParamRecommendation]:
    """Generate fix recommendations from a failed run."""
    recs: list[ParamRecommendation] = []
    error = run.get("error") or ""
    params = run.get("parameters") or {}

    # OOM detection
    if any(kw in error.lower() for kw in ("out of memory", "oom", "killed", "heap space")):
        current_mem = params.get("max_memory") or params.get("memory")
        suggested = _double_memory(str(current_mem) if current_mem else "8.Gb")
        recs.append(ParamRecommendation(
            parameter="max_memory",
            recommended_value=suggested,
            reason=f"OOM in run {run['id'][:8]}; doubling memory from {current_mem}",
            confidence=0.85,
            source="failure_fix",
        ))

    # Timeout detection
    if any(kw in error.lower() for kw in ("timeout", "timed out", "exceeded")):
        current_timeout = run.get("elapsed_seconds")
        if current_timeout:
            recs.append(ParamRecommendation(
                parameter="timeout_seconds",
                recommended_value=str(int(current_timeout * 1.5)),
                reason=f"Timeout in run {run['id'][:8]} ({int(current_timeout)}s elapsed)",
                confidence=0.75,
                source="failure_fix",
            ))

    # Exit code detection
    exit_code = run.get("exit_code")
    if exit_code and exit_code != 0:
        recs.append(ParamRecommendation(
            parameter="retry",
            recommended_value="true",
            reason=f"Non-zero exit code {exit_code} in run {run['id'][:8]}; consider retry",
            confidence=0.60,
            source="failure_fix",
        ))

    return recs


def _double_memory(current: str) -> str:
    """Double a memory specification like '8.Gb' -> '16.Gb'."""
    m = re.match(r"^([\d.]+)\.?([A-Za-z]*)$", current)
    if m:
        num = float(m.group(1)) * 2
        unit = m.group(2) or "Gb"
        return f"{int(num)}.{unit}"
    return f"{int(float(current) * 2)}.Gb"


def _system_constraint_fallback(context: PredictionContext) -> list[ParamRecommendation]:
    """Generate fallback recommendations based on system resources."""
    recs: list[ParamRecommendation] = []
    safe_memory = int(context.system_memory_gb * 0.75)
    safe_cpus = max(1, context.system_cpus // 2)

    recs.append(ParamRecommendation(
        parameter="max_memory",
        recommended_value=f"{safe_memory}.Gb",
        reason=f"System has {context.system_memory_gb}GB RAM; recommending 75% safety margin",
        confidence=0.50,
        source="system_constraint",
    ))
    recs.append(ParamRecommendation(
        parameter="max_cpus",
        recommended_value=str(safe_cpus),
        reason=f"System has {context.system_cpus} CPUs; recommending 50% for stability",
        confidence=0.45,
        source="system_constraint",
    ))
    return recs


def _merge_with_prior(
    recommendations: list[ParamRecommendation],
    prior: dict[str, Any],
) -> list[ParamRecommendation]:
    """Merge recommendations with user's prior/explicit parameters.

    User-specified parameters are never overridden by predictions.
    """
    prior_set = set(prior.keys())
    merged = []
    for rec in recommendations:
        if rec.parameter in prior_set:
            # User explicitly set this — keep their value, add as note
            merged.append(ParamRecommendation(
                parameter=rec.parameter,
                recommended_value=str(prior[rec.parameter]),
                reason=f"User-specified (prediction was: {rec.recommended_value})",
                confidence=1.0,
                source="user_override",
            ))
        else:
            merged.append(rec)
    # Add any user-specified params that weren't in recommendations
    for key, val in prior.items():
        if not any(r.parameter == key for r in merged):
            merged.append(ParamRecommendation(
                parameter=key,
                recommended_value=str(val),
                reason="User-specified parameter",
                confidence=1.0,
                source="user_override",
            ))
    return merged


def _compute_overall_confidence(
    recommendations: list[ParamRecommendation], historical_count: int
) -> float:
    """Compute an overall confidence score for the prediction batch."""
    if not recommendations:
        return 0.30
    confidences = [r.confidence for r in recommendations]
    base = statistics.mean(confidences)
    # Boost for more historical data
    data_bonus = min(historical_count / 10.0, 0.2)
    return round(min(base + data_bonus, 0.95), 2)


def _build_warnings(recommendations: list[ParamRecommendation], hist_count: int) -> list[str]:
    warnings: list[str] = []
    if hist_count == 0:
        warnings.append("No historical data; recommendations based on system constraints only")
    low_conf = [r for r in recommendations if r.confidence < 0.5]
    if low_conf:
        warnings.append(f"{len(low_conf)} recommendation(s) have low confidence (<0.5); review before applying")
    return warnings


# ---------------------------------------------------------------------------
# Proactive prediction (for use during run planning)
# ---------------------------------------------------------------------------

async def predict_for_new_run(
    user_id: int,
    pipeline_id: str,
    revision: str,
    profile: str,
    system_memory_gb: float = 32.0,
    system_cpus: int = 8,
    prior_parameters: dict[str, Any] | None = None,
) -> PredictionResult:
    """Proactively predict parameters before a run is created.

    Loads historical data and generates recommendations suitable for
    pre-execution parameter selection.
    """
    runs = await load_historical_runs(user_id, pipeline_id, revision)
    context = PredictionContext(
        user_id=user_id,
        pipeline_id=pipeline_id,
        revision=revision,
        profile=profile,
        system_memory_gb=system_memory_gb,
        system_cpus=system_cpus,
        prior_parameters=prior_parameters or {},
    )
    return predict_parameters(context, runs)


# ---------------------------------------------------------------------------
# Reactive prediction (for post-failure analysis)
# ---------------------------------------------------------------------------

async def diagnose_and_recommend(
    run_id: str,
    user_id: int,
) -> PredictionResult:
    """After a run fails, diagnose the issue and recommend parameter fixes.

    Loads all historical runs (including the failed one) and generates
    targeted fix recommendations.
    """
    from sqlalchemy import select

    from ..core import db as db_module
    from ..core.models.db import PipelineRun

    async with db_module.AsyncSessionLocal() as db:
        result = await db.execute(
            select(PipelineRun)
            .where(PipelineRun.user_id == user_id)
            .where(PipelineRun.pipeline_id == (
                await _get_pipeline_id_for_run(db, run_id)
            ))
            .order_by(PipelineRun.created_at.asc())
        )
        runs = result.scalars().all()

    runs_dict = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for r in runs:
        params = r.parameters or {}
        runs_dict.append({
            "id": r.id,
            "run_id": r.run_id,
            "status": r.status,
            "parameters": {k: _normalize_param_value(v) for k, v in params.items()},
            "error": r.error or "",
            "exit_code": r.exit_code,
            "created_at": r.created_at or now,
            "elapsed_seconds": _compute_elapsed(r.started_at, r.completed_at),
        })

    # Load the failed run's details for context
    failed_run = None
    for rd in runs_dict:
        if rd["run_id"] == run_id:
            failed_run = rd
            break

    context = PredictionContext(
        user_id=user_id,
        pipeline_id=failed_run["parameters"].get("_pipeline_id", "unknown") if failed_run else "unknown",
        revision="",
        profile="",
    )
    if failed_run:
        context.pipeline_id = str(failed_run.get("_pipeline_id", "unknown"))

    return predict_parameters(context, runs_dict)


async def _get_pipeline_id_for_run(db, run_id: str) -> str | None:
    """Helper to look up pipeline_id for a given research run_id."""
    from sqlalchemy import select

    from ..core.models.db import PipelineRun
    result = await db.execute(
        select(PipelineRun.pipeline_id).where(PipelineRun.run_id == run_id).limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Model persistence (simple JSON-based cache)
# ---------------------------------------------------------------------------

_MODEL_CACHE_KEY = "param_predictor_model_v1"


def compute_model_digest(runs: list[dict[str, Any]]) -> str:
    """Compute a content-hash of the training data to detect when model needs rebuild."""
    raw = "|".join(
        f"{r['id']}:{r['status']}:{hashlib.sha256(str(r.get('parameters', '')).encode()).hexdigest()[:16]}"
        for r in runs
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def estimate_sample_sufficiency(run_count: int) -> tuple[bool, str]:
    """Check if we have enough historical data for reliable predictions."""
    if run_count >= 10:
        return True, "Sufficient data for reliable predictions"
    elif run_count >= 5:
        return False, "Moderate data; predictions may be unreliable"
    elif run_count >= 2:
        return False, "Limited data; treat recommendations as suggestions only"
    return False, "Insufficient data; using system defaults"
