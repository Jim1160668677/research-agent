"""User-scoped recommendation API."""


from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...recommendations.engine import RecommendationEngine
from ..auth import get_current_user
from ..db import get_db
from ..models.schemas import RecommendationRequest, RecommendationResponse

router = APIRouter()


class RecommendationFeedbackRequest(BaseModel):
    item_type: str = Field(pattern="^(skill|plugin|workflow)$")
    item_name: str = Field(min_length=1, max_length=200)
    accepted: bool


@router.get("/", response_model=list[RecommendationResponse])
async def get_recommendations(
    context_type: str = "general",
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取推荐列表"""
    engine = RecommendationEngine(db)
    recommendations = await engine.get_recommendations(
        user_id=current_user["user_id"],
        context_type=context_type,
        limit=limit
    )
    return recommendations


@router.post("/for-context", response_model=RecommendationResponse)
async def recommend_for_context(
    request: RecommendationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """基于上下文获取推荐"""
    engine = RecommendationEngine(db)
    return await engine.recommend_for_context(
        user_id=current_user["user_id"],
        context_type=request.context_type,
        context_data=request.context_data,
        limit=request.limit,
    )


@router.get("/history")
async def get_recommendation_history(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取推荐历史"""
    engine = RecommendationEngine(db)
    history = await engine.get_history(user_id=current_user["user_id"], limit=limit)
    return history


@router.post("/feedback")
async def submit_recommendation_feedback(
    request: RecommendationFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    engine = RecommendationEngine(db)
    try:
        return await engine.record_feedback(
            current_user["user_id"],
            item_type=request.item_type,
            item_name=request.item_name,
            accepted=request.accepted,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["router"]
