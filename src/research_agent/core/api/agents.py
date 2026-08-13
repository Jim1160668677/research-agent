"""API routes for agents"""

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agents.agent import ResearchAgent
from ..auth import get_current_user
from ..db import get_db
from ..models.db import Conversation
from ..models.schemas import AgentMessage, AgentResponse

router = APIRouter()


@router.post("/chat", response_model=AgentResponse)
async def chat(
    message: AgentMessage,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """自然语言对话接口"""
    try:
        agent = ResearchAgent(
            db_session=db,
            user_id=current_user["user_id"],
            session_id=message.session_id,
        )
        response = await agent.process_message(message.content, message.context)
        tools = [
            item if isinstance(item, dict) else {"name": str(item)}
            for item in response.get("tools_used", [])
        ]
        skills = [
            item if isinstance(item, dict) else {"name": str(item)}
            for item in response.get("skills_executed", [])
        ]
        return AgentResponse(
            session_id=response.get("session_id"),
            message=response["message"],
            tools_used=tools,
            skills_executed=skills,
            suggestions=response.get("suggestions", []),
            metadata={
                "success": response.get("success", True),
                "intent": response.get("intent"),
                "execution_time": response.get("execution_time"),
                "llm": response.get("llm_info", {}),
            },
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/execute")
async def execute_task(
    task: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """执行指定任务"""
    try:
        agent = ResearchAgent(db_session=db, user_id=current_user["user_id"])
        result = await agent.execute_task(task)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Execute task error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/multi-agent")
async def multi_agent_chat(
    message: AgentMessage,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """多智能体协作接口"""
    try:
        from ...agents.multi_agent import CoordinatorAgent

        coordinator = CoordinatorAgent(db=db, user_id=current_user["user_id"])
        result = await coordinator.run(message.content)
        return {
            "session_id": message.session_id,
            "message": result.get("response", ""),
            "success": result.get("success", False),
            "agents_used": result.get("agents_used", []),
            "skills_used": result.get("skills_used", []),
            "suggestions": result.get("suggestions", []),
            "metadata": {
                "architecture": "langgraph",
                "results": result.get("results", {}),
            },
        }
    except Exception as e:
        logger.error(f"Multi-agent error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/multi-agent/status")
async def multi_agent_status(current_user: dict = Depends(get_current_user)):
    """多智能体系统状态"""
    try:
        from ...agents.multi_agent import CoordinatorAgent

        coordinator = CoordinatorAgent()
        agents = []
        for name, agent in coordinator.specialists.items():
            agents.append({"name": name, "description": agent.description})
        return {
            "architecture": "LangGraph StateGraph",
            "coordinator": "CoordinatorAgent (条件路由)",
            "specialists": agents,
            "routing_keywords": CoordinatorAgent.ROUTING_KEYWORDS,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/sessions")
async def list_sessions(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取用户会话列表"""
    safe_limit = min(max(limit, 1), 100)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user["user_id"])
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(safe_limit)
    )
    sessions = []
    for conversation in result.scalars().all():
        messages = list(conversation.messages or [])
        first_user = next(
            (item.get("content", "") for item in messages if item.get("role") == "user"),
            "新对话",
        )
        sessions.append(
            {
                "session_id": conversation.session_id,
                "title": first_user.strip().replace("\n", " ")[:56] or "新对话",
                "message_count": len(messages),
                "provider": conversation.provider,
                "model": conversation.model,
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
            }
        )
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取会话详情"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.session_id == session_id,
            Conversation.user_id == current_user["user_id"],
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {
        "session": {
            "session_id": conversation.session_id,
            "messages": conversation.messages or [],
            "provider": conversation.provider,
            "model": conversation.model,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        }
    }


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除会话"""
    result = await db.execute(
        delete(Conversation).where(
            Conversation.session_id == session_id,
            Conversation.user_id == current_user["user_id"],
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="对话不存在")
    await db.commit()
    return {"status": "ok"}


__all__ = ["router"]
