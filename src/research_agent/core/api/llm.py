"""API routes for LLM configuration and chat"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...llm import (
    PROVIDER_REGISTRY,
    ChatEngine,
    LLMProviderError,
    get_key_manager,
    get_provider,
    provider_descriptors,
)
from ..app import settings
from ..auth import get_current_user
from ..db import get_db
from ..models.db import UserProfile

router = APIRouter()


class KeySaveRequest(BaseModel):
    provider: str = Field(..., description="openai/deepseek/agnes/anthropic/google")
    api_key: str = Field(..., min_length=10, description="API Key")
    name: str = ""
    is_active: bool = True


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[dict[str, Any]] | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    session_id: str | None = None


class ChatResponse(BaseModel):
    success: bool
    response: str
    provider: str
    model: str
    usage: dict[str, Any] = Field(default_factory=dict)
    provider_info: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    attempts: int = 1
    latency_ms: int = 0


class ProviderPreferenceRequest(BaseModel):
    provider: str
    model: str


async def _preferred_model(db: AsyncSession, user_id: int) -> dict[str, str] | None:
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalars().first()
    if not profile or not profile.preferred_models:
        return None
    first = profile.preferred_models[0]
    if isinstance(first, dict):
        return {
            "provider": str(first.get("provider") or ""),
            "model": str(first.get("model") or ""),
        }
    provider, _, model = str(first).partition(":")
    return {"provider": provider, "model": model}


@router.get("/status")
async def llm_status(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取LLM配置状态"""
    manager = get_key_manager(db, user_id=current_user["user_id"])
    status = await manager.get_all_provider_status()
    return {
        "providers": status,
        "available_providers": list(PROVIDER_REGISTRY.keys()),
        "provider_descriptors": provider_descriptors(),
        "models": {name: list(provider.models) for name, provider in PROVIDER_REGISTRY.items()},
        "preferred": await _preferred_model(db, current_user["user_id"]),
    }


@router.get("/keys")
async def list_keys(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列出所有已配置Key (仅掩码)"""
    manager = get_key_manager(db, user_id=current_user["user_id"])
    keys = await manager.list_keys()
    return {"keys": keys}


@router.post("/keys")
async def save_key(
    request: KeySaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """安全保存API Key (加密存储, 绑定当前用户)"""
    manager = get_key_manager(db, user_id=current_user["user_id"])
    try:
        result = await manager.save_key(
            request.provider,
            request.api_key.strip(),
            name=request.name,
            is_active=request.is_active,
            created_by=current_user["user_id"],
        )
        return {"success": True, "key": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"保存Key失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {e}") from e


@router.delete("/keys/{provider}")
async def delete_key(
    provider: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除API Key"""
    manager = get_key_manager(db, user_id=current_user["user_id"])
    deleted = await manager.delete_key(provider)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"未找到 {provider} 的Key")
    return {"success": True}


@router.put("/preference")
async def save_preference(
    request: ProviderPreferenceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Persist the model choice consumed by chat and every specialist agent."""
    provider = request.provider.lower().strip()
    try:
        get_provider(provider, model=request.model)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    manager = get_key_manager(db, user_id=current_user["user_id"])
    configured_key = await manager.get_key(provider) or getattr(settings, f"{provider}_api_key", "")
    if not configured_key:
        raise HTTPException(
            status_code=409,
            detail=f"请先配置 {provider} API Key，再将其设为共享默认模型。",
        )
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user["user_id"])
    )
    profile = result.scalars().first()
    if profile is None:
        profile = UserProfile(user_id=current_user["user_id"])
        db.add(profile)
    existing = [
        item
        for item in list(profile.preferred_models or [])
        if (item.get("provider") if isinstance(item, dict) else str(item).partition(":")[0])
        != provider
    ]
    profile.preferred_models = [{"provider": provider, "model": request.model}, *existing][:10]
    await db.commit()
    return {"success": True, "preferred": profile.preferred_models[0]}


@router.post("/providers/{provider}/health")
async def provider_health(
    provider: str,
    live: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Check runtime/configuration and optionally perform a minimal live request."""
    provider = provider.lower().strip()
    if provider not in PROVIDER_REGISTRY:
        raise HTTPException(status_code=404, detail=f"未知Provider: {provider}")
    manager = get_key_manager(db, user_id=current_user["user_id"])
    api_key = await manager.get_key(provider) or getattr(settings, f"{provider}_api_key", "")
    preferred = await _preferred_model(db, current_user["user_id"])
    model = preferred["model"] if preferred and preferred["provider"] == provider else ""
    instance = get_provider(provider, api_key=api_key, model=model)
    return await instance.health_check(live=live)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """真实LLM对话"""
    try:
        engine = ChatEngine(
            provider_name=request.provider or "",
            model=request.model or "",
            db=db,
            user_id=current_user["user_id"],
            session_id=request.session_id,
        )
        kwargs = {}
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens

        result = await engine.chat(request.message, history=request.history, **kwargs)
        return ChatResponse(**result)
    except (RuntimeError, ValueError, LLMProviderError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"LLM对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"LLM调用失败: {e}") from e


@router.get("/chat/status")
async def chat_status(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """检查ChatEngine配置状态"""
    engine = ChatEngine(db=db, user_id=current_user["user_id"])
    return await engine.check_status()


__all__ = ["router"]
