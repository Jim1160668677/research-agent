"""Skill base classes and execution framework"""

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger


@dataclass
class SkillParameter:
    """技能参数定义"""
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class SkillOutput:
    """技能输出定义"""
    name: str
    type: str = "string"
    description: str = ""


@dataclass
class SkillResult:
    """技能执行结果"""
    success: bool
    skill_name: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    execution_time: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseSkill(ABC):
    """技能基类"""

    def __init__(
        self,
        name: str,
        description: str,
        category: str = "general",
        parameters: list[SkillParameter] = None,
        output_schema: list[SkillOutput] = None,
        modalities: list[str] = None,
        risk_level: str = "low",
        network_access: bool = False,
        writes_files: bool = False,
        timeout_seconds: int = 60,
    ):
        self.name = name
        self.description = description
        self.category = category
        self.parameters = parameters or []
        self.output_schema = output_schema or []
        self.version = "1.0.0"
        self.is_active = True
        self.modalities = modalities or ["text"]
        self.risk_level = risk_level
        self.network_access = network_access
        self.writes_files = writes_files
        self.timeout_seconds = min(max(int(timeout_seconds), 1), 300)

    @abstractmethod
    async def execute(self, **kwargs) -> dict[str, Any]:
        """执行技能"""
        pass

    def validate_parameters(self, params: dict[str, Any]) -> list[str]:
        """验证参数"""
        errors = []
        for param in self.parameters:
            if param.required and param.name not in params:
                if param.default is not None:
                    params[param.name] = param.default
                else:
                    errors.append(f"Missing required parameter: {param.name}")

        # 类型检查
        for param in self.parameters:
            if param.name in params:
                value = params[param.name]
                if param.type == "string" and not isinstance(value, str):
                    errors.append(f"Parameter {param.name} should be string")
                elif param.type == "integer" and not isinstance(value, int):
                    errors.append(f"Parameter {param.name} should be integer")
                elif param.type == "number" and not isinstance(value, int | float):
                    errors.append(f"Parameter {param.name} should be number")
                elif param.type == "boolean" and not isinstance(value, bool):
                    errors.append(f"Parameter {param.name} should be boolean")
                elif param.type == "list" and not isinstance(value, list):
                    errors.append(f"Parameter {param.name} should be list")

        # 枚举检查
        for param in self.parameters:
            if param.name in params and param.enum:
                if params[param.name] not in param.enum:
                    errors.append(f"Parameter {param.name} must be one of: {param.enum}")

        return errors

    def get_parameter_schema(self) -> dict[str, Any]:
        """获取参数Schema"""
        return {
            param.name: {
                "type": param.type,
                "description": param.description,
                "required": param.required,
                "default": param.default,
                "enum": param.enum,
            }
            for param in self.parameters
        }

    def get_output_schema(self) -> dict[str, Any]:
        """获取输出Schema"""
        return {
            output.name: {
                "type": output.type,
                "description": output.description,
            }
            for output in self.output_schema
        }

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "is_active": self.is_active,
            "parameters": self.get_parameter_schema(),
            "output_schema": self.get_output_schema(),
            "capabilities": {
                "modalities": self.modalities,
                "risk_level": self.risk_level,
                "network_access": self.network_access,
                "writes_files": self.writes_files,
                "timeout_seconds": self.timeout_seconds,
            },
        }


class SkillRegistry:
    """技能注册表"""

    _skills: dict[str, BaseSkill] = {}
    _categories: dict[str, list[str]] = {}

    @classmethod
    def register(cls, skill: BaseSkill):
        """注册技能"""
        previous = cls._skills.get(skill.name)
        if previous and previous.category in cls._categories:
            cls._categories[previous.category] = [
                name for name in cls._categories[previous.category] if name != skill.name
            ]
        cls._skills[skill.name] = skill
        if skill.category not in cls._categories:
            cls._categories[skill.category] = []
        if skill.name not in cls._categories[skill.category]:
            cls._categories[skill.category].append(skill.name)
        logger.info(f"Skill registered: {skill.name} (category: {skill.category})")

    @classmethod
    def unregister(cls, name: str):
        """注销技能"""
        if name in cls._skills:
            skill = cls._skills.pop(name)
            if skill.category in cls._categories:
                cls._categories[skill.category].remove(name)
            logger.info(f"Skill unregistered: {name}")

    @classmethod
    def get(cls, name: str) -> BaseSkill | None:
        """获取技能"""
        return cls._skills.get(name)

    @classmethod
    def list_all(cls) -> dict[str, Any]:
        """列出所有技能"""
        return {
            name: skill.to_dict()
            for name, skill in cls._skills.items()
            if skill.is_active
        }

    @classmethod
    def list_by_category(cls, category: str) -> list[str]:
        """按分类列出技能"""
        return cls._categories.get(category, [])

    @classmethod
    def search(cls, keyword: str) -> list[str]:
        """搜索技能"""
        keyword_lower = keyword.lower()
        results = []
        for name, skill in cls._skills.items():
            if (keyword_lower in name.lower() or
                keyword_lower in skill.description.lower()):
                results.append(name)
        return results

    @classmethod
    def initialize_builtin(cls):
        """初始化内置技能"""
        from .builtin import initialize_builtin_skills
        initialize_builtin_skills()
        return cls


class SkillExecutor:
    """技能执行器"""

    def __init__(self):
        self.registry = SkillRegistry
        self._execution_log = deque(maxlen=500)

    @staticmethod
    def _safe_parameter_log(params: dict[str, Any]) -> dict[str, Any]:
        """记录形状而非原始科研数据或密钥。"""
        safe = {}
        for key, value in params.items():
            if any(token in key.lower() for token in ("key", "token", "secret", "password")):
                safe[key] = "[REDACTED]"
            elif isinstance(value, list):
                safe[key] = {"type": "list", "length": len(value)}
            elif isinstance(value, dict):
                safe[key] = {"type": "object", "keys": list(value)[:20]}
            elif isinstance(value, str) and len(value) > 160:
                safe[key] = value[:160] + "…"
            else:
                safe[key] = value
        return safe

    async def execute(self, skill_name: str, **kwargs) -> SkillResult:
        """执行技能"""
        start_time = datetime.now()

        try:
            skill = self.registry.get(skill_name)
            if not skill:
                return SkillResult(
                    success=False,
                    skill_name=skill_name,
                    error=f"Skill not found: {skill_name}",
                )

            # 验证参数
            errors = skill.validate_parameters(kwargs)
            if errors:
                return SkillResult(
                    success=False,
                    skill_name=skill_name,
                    error=f"Parameter validation errors: {errors}",
                )

            # 执行技能
            result = await asyncio.wait_for(
                skill.execute(**kwargs),
                timeout=skill.timeout_seconds,
            )
            if not isinstance(result, dict):
                raise TypeError("Skill output must be a dictionary")

            execution_time = (datetime.now() - start_time).total_seconds()

            # 记录执行日志
            self._execution_log.append({
                "skill_name": skill_name,
                "parameters": self._safe_parameter_log(kwargs),
                "result_keys": list(result)[:50],
                "execution_time": execution_time,
                "timestamp": start_time.isoformat(),
            })

            return SkillResult(
                success=True,
                skill_name=skill_name,
                output=result,
                execution_time=execution_time,
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"Skill execution error: {skill_name}: {e}")

            return SkillResult(
                success=False,
                skill_name=skill_name,
                error=str(e),
                execution_time=execution_time,
            )

    def get_execution_log(self, limit: int = 100) -> list[dict]:
        """获取执行日志"""
        return list(self._execution_log)[-limit:]


# 全局执行器实例
_executor = SkillExecutor()


def get_executor() -> SkillExecutor:
    """获取全局执行器"""
    return _executor


__all__ = [
    "BaseSkill",
    "SkillParameter",
    "SkillOutput",
    "SkillResult",
    "SkillRegistry",
    "SkillExecutor",
    "get_executor",
]
