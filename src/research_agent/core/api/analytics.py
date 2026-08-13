"""Analytics API - 使用统计与需求洞察"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import get_current_user
from ...analytics import get_tracker, get_simulator

router = APIRouter(tags=["analytics"])


class UsageSummaryResponse(BaseModel):
    total_events: int
    event_types: int
    session_duration_minutes: float
    top_features: list
    error_count: int


class InsightsResponse(BaseModel):
    insights: list
    scenarios: list


@router.get("/usage", response_model=UsageSummaryResponse)
async def get_usage_summary(
    current_user: dict = Depends(get_current_user),
):
    """获取使用统计摘要"""
    tracker = get_tracker()
    if not tracker:
        return UsageSummaryResponse(
            total_events=0, event_types=0,
            session_duration_minutes=0.0, top_features=[], error_count=0,
        )
    summary = tracker.get_usage_summary()
    return UsageSummaryResponse(
        total_events=summary["total_events"],
        event_types=summary["event_types"],
        session_duration_minutes=summary["session_duration_minutes"],
        top_features=summary["top_features"],
        error_count=summary["error_count"],
    )


@router.get("/insights", response_model=InsightsResponse)
async def get_requirement_insights(
    current_user: dict = Depends(get_current_user),
):
    """获取需求洞察"""
    tracker = get_tracker()
    simulator = get_simulator()

    insights = []
    if tracker:
        insights = tracker.get_requirement_insights()

    scenarios = []
    if simulator:
        known_features = {
            "pdb_parser", "molecule_viewer", "docking_engine", "result_analyzer",
            "ncbi_search", "pdf_reader", "citation_manager", "llm_summarizer",
            "data_importer", "statistical_tests", "plot_generator", "model_fitter",
            "hypothesis_tester", "sample_size_calculator", "randomization_tool",
            "protocol_generator",
        }
        scenarios = simulator.get_all_scenario_analyses(known_features)

    return InsightsResponse(insights=insights, scenarios=scenarios)


@router.post("/track")
async def track_event(
    event_type: str,
    data: Optional[dict] = None,
    current_user: dict = Depends(get_current_user),
):
    """追踪事件 (供前端调用)"""
    tracker = get_tracker()
    if tracker:
        tracker.track(event_type, data)
    return {"status": "ok"}