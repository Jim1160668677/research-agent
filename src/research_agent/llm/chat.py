"""LLM Chat 引擎 - 真实对话与系统提示词管理"""

from typing import Any

from loguru import logger

from ..core.app import settings
from ..runtime_coordinator import get_runtime_coordinator
from .keys import get_key_manager
from .provider import LLMMessage, LLMProvider, LLMProviderError, get_provider

try:
    from sqlalchemy import select

    from ..core.models.db import Conversation, UserProfile

    _db_available = True
except ImportError:
    _db_available = False


SYSTEM_PROMPT = """你是"科研智能体" (Research Agent)，一个面向生命科学研究的通用AI助手。

你的能力范围:
1. 文献检索与分析 (PubMed/SRA/GenBank等NCBI数据库)
2. 生物信息学分析 (差异表达、单细胞、序列分析)
3. 分子对接与蛋白质结构分析 (AutoDock Vina/Glide/GOLD/PyMOL/ChimeraX)
4. 统计建模与数据可视化
5. 实验设计建议

回答要求:
- 使用中文回答（用户使用中文时）
- 涉及专业内容时给出简洁准确的技术说明
- 推荐使用系统中的技能/工具完成具体任务
- 涉及实验设计/统计分析时说明假设与局限
"""


class ChatEngine:
    """LLM 对话引擎 - 支持内存和数据库双模式持久化"""

    def __init__(
        self,
        provider_name: str = "",
        model: str = "",
        db=None,
        user_id: int | None = None,
        session_id: str | None = None,
    ):
        self.provider_name = provider_name.lower().strip()
        self.requested_model = model.strip()
        self.db = db
        self.user_id = user_id
        self.session_id = session_id
        self._provider: LLMProvider | None = None
        self._conversation_history: list[dict[str, Any]] = []
        self._history_loaded = False
        self.system_prompt = SYSTEM_PROMPT

    async def _load_from_db(self):
        """从数据库加载会话历史"""
        try:
            conditions = [Conversation.session_id == self.session_id]
            if self.user_id is not None:
                conditions.append(Conversation.user_id == self.user_id)
            result = await self.db.execute(select(Conversation).where(*conditions))
            conv = result.scalar_one_or_none()
            if conv and conv.messages:
                self._conversation_history = list(conv.messages)
                if conv.provider and not self.provider_name:
                    self.provider_name = conv.provider
        except Exception as e:
            logger.warning(f"加载对话历史失败: {e}")
        finally:
            self._history_loaded = True

    async def _save_to_db(
        self, user_message: str, assistant_response: str, provider: str, model: str
    ):
        """保存对话到数据库"""
        if not _db_available or self.db is None:
            return

        try:
            # The caller appends the exchange before persistence. Copying that
            # state prevents the former duplicate user/assistant pair bug.
            messages = list(self._conversation_history)

            if self.session_id:
                # 更新现有会话
                conditions = [Conversation.session_id == self.session_id]
                if self.user_id is not None:
                    conditions.append(Conversation.user_id == self.user_id)
                result = await self.db.execute(select(Conversation).where(*conditions))
                conv = result.scalar_one_or_none()
                if conv:
                    conv.messages = messages
                    conv.provider = provider
                    conv.model = model
                else:
                    # 创建新会话
                    conv = Conversation(
                        user_id=self.user_id,
                        session_id=self.session_id,
                        provider=provider,
                        model=model,
                        messages=messages,
                    )
                    self.db.add(conv)
            else:
                # 创建新会话
                import uuid

                self.session_id = str(uuid.uuid4())
                conv = Conversation(
                    user_id=self.user_id,
                    session_id=self.session_id,
                    provider=provider,
                    model=model,
                    messages=messages,
                )
                self.db.add(conv)

            await self.db.commit()
        except Exception as e:
            logger.error(f"保存对话失败: {e}")

    async def save_exchange(
        self,
        user_message: str,
        assistant_response: str,
        provider: str = "local",
        model: str = "rules",
    ) -> None:
        """Append and persist a non-LLM fallback response."""
        if self.session_id and not self._history_loaded:
            await self._load_from_db()
        self._conversation_history.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_response},
            ]
        )
        await self._save_to_db(user_message, assistant_response, provider, model)

    async def _preferred_provider_model(self) -> tuple[str, str]:
        """Resolve one user-scoped model choice shared by chat and agents."""
        if self.provider_name:
            return self.provider_name, self.requested_model

        if _db_available and self.db is not None and self.user_id is not None:
            try:
                result = await self.db.execute(
                    select(UserProfile).where(UserProfile.user_id == self.user_id)
                )
                profile = result.scalars().first()
                for item in list(profile.preferred_models or []) if profile else []:
                    if isinstance(item, dict):
                        provider = str(item.get("provider") or "").lower().strip()
                        model = str(item.get("model") or "").strip()
                    else:
                        provider, _, model = str(item).partition(":")
                        provider = provider.lower().strip()
                    if provider:
                        return provider, model
            except Exception as error:
                logger.warning("读取用户模型偏好失败: {}", error)

        key_manager = get_key_manager(self.db, user_id=self.user_id)
        for provider in ("deepseek", "agnes", "openai", "anthropic", "google"):
            if await key_manager.get_key(provider):
                return provider, getattr(settings, f"{provider}_model", "")

        for provider in ("deepseek", "agnes", "openai", "anthropic", "google"):
            if getattr(settings, f"{provider}_api_key", ""):
                return provider, getattr(settings, f"{provider}_model", "")
        # Offline fallback: probe local Ollama instance
        try:
            import httpx
            resp = await httpx.AsyncClient(timeout=3).get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                return "ollama", "llama3"
        except Exception:
            pass  # Ollama not available

        return "openai", getattr(settings, "openai_model", "")

    async def _get_provider(self) -> LLMProvider:
        """获取配置好的Provider实例"""
        if self._provider is not None:
            return self._provider

        provider_name, preferred_model = await self._preferred_provider_model()
        self.provider_name = provider_name
        key_manager = get_key_manager(self.db, user_id=self.user_id)
        api_key = await key_manager.get_key(provider_name)

        # 从settings回退
        if not api_key:
            api_key = getattr(settings, f"{provider_name}_api_key", "")

        if not api_key:
            raise RuntimeError(
                f"{provider_name} API Key 未配置。请在 .env 中设置或通过 /api/v1/llm/keys 配置。"
            )

        model = (
            self.requested_model
            or preferred_model
            or getattr(settings, f"{provider_name}_model", "")
        )
        self._provider = get_provider(provider_name, api_key=api_key, model=model)
        return self._provider

    async def chat(
        self, user_message: str, history: list[dict] | None = None, **kwargs
    ) -> dict[str, Any]:
        """发送对话请求

        Args:
            user_message: 用户消息
            history: 历史消息 [{role, content}, ...]
        """
        messages = [LLMMessage(role="system", content=self.system_prompt)]

        if history is None and self.session_id and not self._history_loaded:
            await self._load_from_db()

        # 加入历史 (优先使用传入的 history, 否则用内存中的)
        conv_history = history if history is not None else self._conversation_history
        for msg in conv_history:
            role = msg.get("role", "user")
            if role in ("user", "assistant"):
                messages.append(LLMMessage(role=role, content=msg.get("content", "")))

        messages.append(LLMMessage(role="user", content=user_message))

        provider = await self._get_provider()
        operation_id = self.session_id or f"user-{self.user_id or 'anonymous'}"
        response = None
        _used_ollama = False
        try:
            async with get_runtime_coordinator().lease("llm", operation_id):
                response = await provider.chat(messages, **kwargs)
        except LLMProviderError as _err:
            logger.warning("Primary provider failed ({}): {}, trying Ollama fallback", provider.name, _err.code)
            if provider.name != "ollama":
                try:
                    from .provider import OllamaProvider
                    ollama = OllamaProvider(model="llama3")
                    async with get_runtime_coordinator().lease("llm", operation_id):
                        response = await ollama.chat(messages, **kwargs)
                    _used_ollama = True
                    logger.info("Fell back to Ollama successfully")
                except Exception as _ollama_err:
                    logger.error("Ollama fallback also failed: {}", _ollama_err)
                    raise RuntimeError(
                        f"All LLM providers failed: primary={_err}, ollama={_ollama_err}"
                    ) from _ollama_err
            else:
                raise

        if response is None:
            raise RuntimeError("LLM call returned no response from any provider")

        # 记录对话到内存
        self._conversation_history.append(
            {
                "role": "user",
                "content": user_message,
            }
        )
        self._conversation_history.append(
            {
                "role": "assistant",
                "content": response.content,
            }
        )

        # 持久化到数据库
        await self._save_to_db(user_message, response.content, response.provider, response.model)

        return {
            "success": True,
            "response": response.content,
            "provider": response.provider,
            "model": response.model,
            "usage": response.usage or {},
            "attempts": response.attempts,
            "latency_ms": response.latency_ms,
            "provider_info": provider.to_dict(),
            "session_id": self.session_id,
        }

    async def check_status(self) -> dict[str, Any]:
        """检查LLM配置状态"""
        try:
            provider = await self._get_provider()
            return {
                "success": True,
                "provider": provider.name,
                "model": provider.model,
                "configured": True,
                "key_masked": provider._mask_key(),
            }
        except RuntimeError as e:
            return {"success": False, "error": str(e), "configured": False}
        except Exception as e:
            return {"success": False, "error": str(e), "configured": False}

    def clear_history(self):
        """清空对话历史"""
        self._conversation_history = []

    def get_history(self, limit: int = 50) -> list[dict]:
        """获取对话历史"""
        return self._conversation_history[-limit:]


__all__ = ["ChatEngine", "SYSTEM_PROMPT"]
