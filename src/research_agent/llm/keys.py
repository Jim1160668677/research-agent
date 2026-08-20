"""API Key 安全管理器

安全策略:
1. API Key 使用 Fernet 对称加密后存储于数据库 (api_keys 表)
2. 支持环境变量回退 (包括 DEEPSEEK_API_KEY / AGNES_API_KEY)
3. 加密密钥从服务端 JWT_SECRET 派生，不直接存储
4. API 返回时仅返回掩码后的 key
"""

import os
from typing import Any

from loguru import logger
from sqlalchemy import select

from ..core.db import AsyncSession
from ..core.models.db import ApiKey
from ..security import CryptoService

# 环境变量映射
ENV_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "agnes": "AGNES_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "ollama": "",  # Ollama requires no API key
}


class APIKeyManager:
    """API Key 管理器"""

    def __init__(self, db: AsyncSession | None = None, user_id: int | None = None):
        self.db = db
        self.user_id = user_id
        self._memory_cache: dict[str, str] = {}

    @staticmethod
    def mask_key(key: str) -> str:
        """掩码API Key"""
        if not key:
            return ""
        if len(key) <= 8:
            return "*" * len(key)
        return key[:6] + "..." + key[-4:]

    async def save_key(
        self,
        provider: str,
        api_key: str,
        name: str = "",
        is_active: bool = True,
        created_by: int = None,
    ) -> dict[str, Any]:
        """加密保存API Key"""
        provider = provider.lower()
        if provider not in ENV_KEY_MAP:
            raise ValueError(f"不支持的Provider: {provider}，可用: {list(ENV_KEY_MAP.keys())}")

        encrypted = CryptoService.encrypt(api_key)

        if self.db is None:
            # 无数据库时使用内存缓存 (进程级)
            self._memory_cache[provider] = api_key
            return {
                "provider": provider,
                "name": name,
                "key_masked": self.mask_key(api_key),
                "is_active": is_active,
                "storage": "memory",
            }

        # 检查是否已存在
        query = select(ApiKey).where(ApiKey.provider == provider)
        owner_id = created_by if created_by is not None else self.user_id
        if owner_id is not None:
            query = query.where(ApiKey.created_by == owner_id)
        result = await self.db.execute(query)
        existing = result.scalars().first()

        if existing:
            existing.encrypted_key = encrypted
            existing.key_prefix = api_key[:6]
            existing.name = name
            existing.is_active = is_active
        else:
            self.db.add(
                ApiKey(
                    provider=provider,
                    name=name,
                    encrypted_key=encrypted,
                    key_prefix=api_key[:6],
                    is_active=is_active,
                    created_by=owner_id,
                )
            )
        await self.db.commit()

        logger.info(f"API Key 已保存 (provider={provider}, masked={self.mask_key(api_key)})")
        return {
            "provider": provider,
            "name": name,
            "key_masked": self.mask_key(api_key),
            "is_active": is_active,
            "storage": "database",
        }

    async def get_key(self, provider: str) -> str | None:
        """获取明文API Key

        查找顺序:
        1. 数据库 (加密存储)
        2. 内存缓存
        3. 环境变量
        """
        provider = provider.lower()

        # 1. 数据库
        if self.db is not None:
            query = select(ApiKey).where(
                ApiKey.provider == provider,
                ApiKey.is_active == True,  # noqa: E712
            )
            if self.user_id is not None:
                query = query.where(ApiKey.created_by == self.user_id)
            result = await self.db.execute(query)
            record = result.scalars().first()
            if record and record.encrypted_key:
                return CryptoService.decrypt(record.encrypted_key)

        # 2. 内存缓存
        if provider in self._memory_cache:
            return self._memory_cache[provider]

        # 3. 环境变量
        env_name = ENV_KEY_MAP.get(provider)
        if env_name:
            env_value = os.getenv(env_name, "")
            if env_value:
                return env_value

        return None

    async def list_keys(self) -> list[dict[str, Any]]:
        """列出所有已配置的Key (仅掩码)"""
        result = []
        for provider in ENV_KEY_MAP:
            key = await self.get_key(provider)
            env_configured = bool(os.getenv(ENV_KEY_MAP[provider], ""))
            memory_configured = provider in self._memory_cache
            if key:
                result.append(
                    {
                        "provider": provider,
                        "configured": True,
                        "key_masked": self.mask_key(key),
                        "source": (
                            "environment"
                            if env_configured
                            else "memory"
                            if memory_configured
                            else "database"
                        ),
                    }
                )
            else:
                result.append(
                    {
                        "provider": provider,
                        "configured": False,
                        "key_masked": "",
                        "source": None,
                    }
                )
        return result

    async def delete_key(self, provider: str) -> bool:
        """删除API Key"""
        provider = provider.lower()
        self._memory_cache.pop(provider, None)

        if self.db is not None:
            query = select(ApiKey).where(ApiKey.provider == provider)
            if self.user_id is not None:
                query = query.where(ApiKey.created_by == self.user_id)
            result = await self.db.execute(query)
            record = result.scalars().first()
            if record:
                await self.db.delete(record)
                await self.db.commit()
                logger.info(f"API Key 已删除 (provider={provider})")
                return True
        return False

    def get_provider_config(self, provider: str) -> dict[str, Any]:
        """获取Provider配置状态"""
        return {
            "provider": provider,
            "env_var": ENV_KEY_MAP.get(provider, ""),
        }

    async def get_all_provider_status(self) -> dict[str, Any]:
        """获取所有Provider的状态"""
        keys = await self.list_keys()
        status = {}
        for k in keys:
            status[k["provider"]] = {
                "configured": k["configured"],
                "key_masked": k["key_masked"],
                "source": k["source"],
            }
        return status


# 全局实例 (无DB依赖的配置查询)
_memory_manager = APIKeyManager(db=None)


def get_key_manager(
    db: AsyncSession | None = None,
    user_id: int | None = None,
) -> APIKeyManager:
    """获取Key管理器"""
    if db is not None:
        return APIKeyManager(db=db, user_id=user_id)
    return _memory_manager


__all__ = ["APIKeyManager", "get_key_manager", "ENV_KEY_MAP"]
