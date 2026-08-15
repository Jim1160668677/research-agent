"""API routes for skills"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...agents.skills import SkillRegistry, get_executor

router = APIRouter()


class SkillExecuteRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


@router.get("/", response_model=list[dict])
async def list_skills(
    category: str | None = Query(None, description="按分类筛选"),
    search: str | None = Query(None, description="搜索关键词"),
):
    """列出所有可用技能"""
    skills = SkillRegistry.list_all()
    result = list(skills.values())

    if category:
        result = [s for s in result if s.get("category") == category]
    if search:
        query = search.lower()
        result = [
            skill for skill in result
            if query in skill.get("name", "").lower()
            or query in skill.get("description", "").lower()
        ]

    return result


@router.get("/categories")
async def list_categories():
    """列出技能分类"""
    skills = SkillRegistry.list_all()
    categories = {}
    for skill in skills.values():
        cat = skill.get("category", "general")
        categories.setdefault(cat, 0)
        categories[cat] += 1
    return {"categories": categories}


@router.get("/{skill_name}")
async def get_skill(skill_name: str):
    """获取技能详情"""
    skill = SkillRegistry.get(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    return skill.to_dict()


@router.post("/{skill_name}/execute")
async def execute_skill(
    skill_name: str,
    request: SkillExecuteRequest,
):
    """执行技能"""
    executor = get_executor()
    result = await executor.execute(skill_name, **request.parameters)
    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "execution_time": result.execution_time,
    }


__all__ = ["router"]
