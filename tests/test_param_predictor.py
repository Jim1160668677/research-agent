"""Tests for the active parameter prediction model."""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, "src")

from research_agent.research.param_predictor import (
    ParamRecommendation,
    PredictionContext,
    PredictionResult,
    predict_parameters,
    _normalize_param_value,
    _compute_overall_confidence,
    _build_warnings,
    _merge_with_prior,
    _failure_fix_recommendations,
    _apply_system_constraints,
    estimate_sample_sufficiency,
)


def test_normalize_param_value():
    assert _normalize_param_value(None) == "None"
    assert _normalize_param_value(True) == "true"
    assert _normalize_param_value(False) == "false"
    assert _normalize_param_value(4) == "4"
    assert _normalize_param_value(3.14) == "3.14"
    assert _normalize_param_value("hello") == "hello"


def test_predict_empty_history():
    """With no historical runs, should return system-constraint fallbacks."""
    ctx = PredictionContext(
        user_id=1,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        system_memory_gb=16.0,
        system_cpus=4,
    )
    result = predict_parameters(ctx, [])
    assert result.historical_runs_analyzed == 0
    assert len(result.recommendations) >= 2
    assert result.confidence < 0.5
    assert any("No historical" in w for w in result.warnings)


def test_predict_with_successful_runs():
    """When all runs succeeded with same params, recommend those params."""
    runs = [
        {
            "id": "a", "run_id": "r1", "status": "completed",
            "parameters": {"max_cpus": "4", "max_memory": "16.Gb"},
            "error": "", "exit_code": None, "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            "elapsed_seconds": 120.0,
        },
        {
            "id": "b", "run_id": "r2", "status": "completed",
            "parameters": {"max_cpus": "4", "max_memory": "16.Gb"},
            "error": "", "exit_code": None, "created_at": datetime(2026, 8, 5, tzinfo=timezone.utc).replace(tzinfo=None),
            "elapsed_seconds": 115.0,
        },
    ]
    ctx = PredictionContext(
        user_id=1, pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
        system_memory_gb=32.0, system_cpus=8,
    )
    result = predict_parameters(ctx, runs)
    assert result.historical_runs_analyzed == 2
    cpus_recs = [r for r in result.recommendations if r.parameter == "max_cpus"]
    mem_recs = [r for r in result.recommendations if r.parameter == "max_memory"]
    assert cpus_recs
    assert cpus_recs[0].recommended_value == "4"
    assert cpus_recs[0].source == "historical_success"
    assert mem_recs
    assert mem_recs[0].recommended_value == "16.Gb"


def test_predict_success_vs_failure():
    """Parameter value that correlates with success should be recommended."""
    runs = [
        # Failed with low memory
        {
            "id": "fail1", "run_id": "rf1", "status": "failed",
            "parameters": {"max_cpus": "2", "max_memory": "4.Gb"},
            "error": "java.lang.OutOfMemoryError", "exit_code": 1,
            "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            "elapsed_seconds": 300.0,
        },
        # Succeeded with high memory
        {
            "id": "ok1", "run_id": "ro1", "status": "completed",
            "parameters": {"max_cpus": "4", "max_memory": "16.Gb"},
            "error": "", "exit_code": None,
            "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            "elapsed_seconds": 120.0,
        },
        # Succeeded again with high memory
        {
            "id": "ok2", "run_id": "ro2", "status": "completed",
            "parameters": {"max_cpus": "4", "max_memory": "16.Gb"},
            "error": "", "exit_code": None,
            "created_at": datetime(2026, 8, 10, tzinfo=timezone.utc).replace(tzinfo=None),
            "elapsed_seconds": 130.0,
        },
    ]
    ctx = PredictionContext(
        user_id=1, pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
        system_memory_gb=64.0, system_cpus=16,
    )
    result = predict_parameters(ctx, runs)
    mem_recs = [r for r in result.recommendations if r.parameter == "max_memory"]
    assert mem_recs
    assert mem_recs[0].recommended_value == "16.Gb"
    assert mem_recs[0].confidence >= 0.7


def test_system_constraint_override():
    """Recommended memory > 80% of system RAM should be capped."""
    runs = [
        {
            "id": "r1", "run_id": "r1", "status": "completed",
            "parameters": {"max_memory": "30.Gb"},
            "error": "", "exit_code": None,
            "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            "elapsed_seconds": 60.0,
        },
    ]
    # System has 32GB — 30.Gb is > 80%
    ctx = PredictionContext(
        user_id=1, pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
        system_memory_gb=32.0, system_cpus=8,
    )
    result = predict_parameters(ctx, runs)
    mem_recs = [r for r in result.recommendations if r.parameter == "max_memory"]
    assert mem_recs
    # Should be constrained to 75% of 32GB = 24GB
    assert "24" in mem_recs[0].recommended_value
    assert mem_recs[0].source == "system_constraint"


def test_cpu_constraint_override():
    """Recommended CPUs > system CPUs should be capped."""
    runs = [
        {
            "id": "r1", "run_id": "r1", "status": "completed",
            "parameters": {"max_cpus": "32"},
            "error": "", "exit_code": None,
            "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            "elapsed_seconds": 60.0,
        },
    ]
    ctx = PredictionContext(
        user_id=1, pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
        system_memory_gb=64.0, system_cpus=8,
    )
    result = predict_parameters(ctx, runs)
    cpu_recs = [r for r in result.recommendations if r.parameter == "max_cpus"]
    assert cpu_recs
    assert cpu_recs[0].recommended_value == "8"
    assert cpu_recs[0].source == "system_constraint"


def test_failure_fix_oom():
    """OOM failure should generate memory fix recommendation."""
    run = {
        "id": "fail1", "run_id": "r1", "status": "failed",
        "parameters": {"max_memory": "8.Gb", "max_cpus": "4"},
        "error": "java.lang.OutOfMemoryError: Java heap space",
        "exit_code": 1, "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc).replace(tzinfo=None),
        "elapsed_seconds": 600.0,
    }
    ctx = PredictionContext(user_id=1, pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker")
    recs = _failure_fix_recommendations(run, ctx)
    assert any(r.parameter == "max_memory" and r.source == "failure_fix" for r in recs)
    mem_rec = next(r for r in recs if r.parameter == "max_memory")
    assert "16" in mem_rec.recommended_value


def test_failure_fix_timeout():
    """Timeout failure should generate timeout fix recommendation."""
    run = {
        "id": "fail1", "run_id": "r1", "status": "failed",
        "parameters": {"max_cpus": "4"},
        "error": "Workflow timed out after 3600 seconds",
        "exit_code": 1, "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc).replace(tzinfo=None),
        "elapsed_seconds": 3600.0,
    }
    ctx = PredictionContext(user_id=1, pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker")
    recs = _failure_fix_recommendations(run, ctx)
    timeout_recs = [r for r in recs if r.parameter == "timeout_seconds"]
    assert timeout_recs
    assert int(timeout_recs[0].recommended_value) == 5400  # 3600 * 1.5


def test_merge_with_prior():
    """User-specified parameters should override predictions."""
    recs = [
        ParamRecommendation("max_cpus", "16", "Historical best", 0.85, "historical_success"),
        ParamRecommendation("max_memory", "32.Gb", "Historical best", 0.80, "historical_success"),
    ]
    merged = _merge_with_prior(recs, {"max_cpus": "8"})
    cpus_recs = [r for r in merged if r.parameter == "max_cpus"]
    assert cpus_recs
    assert cpus_recs[0].recommended_value == "8"
    assert cpus_recs[0].source == "user_override"
    # Memory should still have the prediction
    mem_recs = [r for r in merged if r.parameter == "max_memory"]
    assert mem_recs
    assert mem_recs[0].recommended_value == "32.Gb"


def test_merge_adds_user_only_params():
    """User params not in predictions should be added."""
    recs = [ParamRecommendation("max_cpus", "4", "Test", 0.7, "historical_success")]
    merged = _merge_with_prior(recs, {"custom_param": "hello"})
    custom = [r for r in merged if r.parameter == "custom_param"]
    assert custom
    assert custom[0].recommended_value == "hello"
    assert custom[0].source == "user_override"


def test_overall_confidence():
    """Overall confidence should be mean of individual confidences + data bonus."""
    recs = [
        ParamRecommendation("a", "1", "r", 0.8, "h"),
        ParamRecommendation("b", "2", "r", 0.6, "h"),
    ]
    conf = _compute_overall_confidence(recs, 10)
    assert conf >= 0.7  # mean 0.7 + 0.2 bonus
    assert conf <= 0.95


def test_warnings():
    """Warnings should be generated for low data and low-confidence recommendations."""
    recs = [ParamRecommendation("x", "1", "r", 0.3, "h")]
    warnings = _build_warnings(recs, 0)
    assert any("No historical" in w for w in warnings)
    assert any("low confidence" in w for w in warnings)


def test_estimate_sample_sufficiency():
    ok, msg = estimate_sample_sufficiency(15)
    assert ok
    assert "reliable" in msg.lower()

    ok, msg = estimate_sample_sufficiency(7)
    assert not ok
    assert "moderate" in msg.lower()

    ok, msg = estimate_sample_sufficiency(3)
    assert not ok
    assert "limited" in msg.lower()

    ok, msg = estimate_sample_sufficiency(1)
    assert not ok
    assert "insufficient" in msg.lower()


@pytest.mark.asyncio
async def test_predict_for_new_run_integration(tmp_path):
    """End-to-end: predict for a new run with historical data in DB."""
    from research_agent.core.db import init_db
    from research_agent.core import db as db_module
    from research_agent.core.models.db import PipelineRun
    from research_agent.research.param_predictor import predict_for_new_run
    from datetime import datetime, timezone

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        runs = [
            PipelineRun(
                id="hist-1", user_id=1, run_id="hr-1",
                pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
                status="completed",
                parameters={"max_cpus": 4, "max_memory": "16.Gb"},
                created_at=datetime(2026, 8, 1, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
            PipelineRun(
                id="hist-2", user_id=1, run_id="hr-2",
                pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
                status="completed",
                parameters={"max_cpus": 4, "max_memory": "16.Gb"},
                created_at=datetime(2026, 8, 5, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
            PipelineRun(
                id="hist-3", user_id=1, run_id="hr-3",
                pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
                status="failed",
                parameters={"max_cpus": 2, "max_memory": "4.Gb"},
                error="java.lang.OutOfMemoryError",
                exit_code=1,
                created_at=datetime(2026, 8, 10, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
            ),
        ]
        for r in runs:
            db.add(r)
        await db.commit()

    result = await predict_for_new_run(
        user_id=1,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        system_memory_gb=32.0,
        system_cpus=8,
    )
    assert result.historical_runs_analyzed == 3
    assert result.confidence >= 0.5
    # Should recommend max_cpus=4 (the successful value)
    cpus_recs = [r for r in result.recommendations if r.parameter == "max_cpus"]
    assert cpus_recs
    assert cpus_recs[0].recommended_value == "4"


@pytest.mark.asyncio
async def test_predict_for_new_run_no_historical(tmp_path):
    """Predict with no historical runs returns system-constraint fallbacks."""
    from research_agent.core.db import init_db
    from research_agent.research.param_predictor import predict_for_new_run

    await init_db()

    result = await predict_for_new_run(
        user_id=999,  # non-existent user
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        system_memory_gb=16.0,
        system_cpus=4,
    )
    assert result.historical_runs_analyzed == 0
    assert result.confidence < 0.5
    assert any("No historical" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_predict_respects_prior_parameters(tmp_path):
    """Prior parameters should not be overridden."""
    from research_agent.core.db import init_db
    from research_agent.core import db as db_module
    from research_agent.core.models.db import PipelineRun
    from research_agent.research.param_predictor import predict_for_new_run
    from datetime import datetime, timezone

    await init_db()

    async with db_module.AsyncSessionLocal() as db:
        run = PipelineRun(
            id="hist-1", user_id=1, run_id="hr-1",
            pipeline_id="nf-core/rnaseq", revision="3.26.0", profile="docker",
            status="completed",
            parameters={"max_cpus": 8, "max_memory": "32.Gb"},
            created_at=datetime(2026, 8, 1, 10, 0, 0).replace(tzinfo=timezone.utc).replace(tzinfo=None),
        )
        db.add(run)
        await db.commit()

    result = await predict_for_new_run(
        user_id=1,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        system_memory_gb=64.0,
        system_cpus=16,
        prior_parameters={"max_cpus": "2"},  # User explicitly chose 2
    )
    cpus_recs = [r for r in result.recommendations if r.parameter == "max_cpus"]
    assert cpus_recs
    assert cpus_recs[0].recommended_value == "2"
    assert cpus_recs[0].source == "user_override"
