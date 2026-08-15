"""Contextual, user-scoped recommendations for executable system capabilities."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select

from ..agents.skills.base import SkillRegistry
from ..core.db import AsyncSession
from ..core.models.db import (
    Plugin,
    PluginInstallation,
    Recommendation,
    UserProfile,
    Workflow,
    WorkflowRun,
)


def _tokens(value: Any) -> set[str]:
    if isinstance(value, dict):
        text = " ".join(f"{key} {_flatten(item)}" for key, item in value.items())
    else:
        text = _flatten(value)
    return {token for token in re.findall(r"[\w-]{2,}", text.lower()) if not token.isdigit()}


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list | tuple | set):
        return " ".join(_flatten(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten(item)}" for key, item in value.items())
    return str(value)


class RecommendationEngine:
    """Rank real skills, plugins and workflows using context and user history."""

    _CATEGORY_PRIORS: dict[str, dict[str, float]] = {
        "literature_search": {
            "literature": 0.62,
            "writing": 0.24,
            "integrity": 0.18,
        },
        "data_analysis": {
            "statistics": 0.60,
            "visualization": 0.50,
            "analysis": 0.40,
            "differential_expression": 0.42,
        },
        "ncbi_search": {
            "genomics": 0.60,
            "literature": 0.42,
            "database": 0.35,
        },
        "experimental_design": {"research": 0.66, "statistics": 0.35},
        "writing": {"writing": 0.68, "integrity": 0.44, "literature": 0.34},
        "docking": {"docking": 0.68, "structure": 0.52},
        "general": {"research": 0.24, "literature": 0.20, "genomics": 0.18},
    }

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get_recommendations(
        self,
        user_id: int,
        context_type: str = "general",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(Recommendation)
            .where(
                Recommendation.user_id == user_id,
                Recommendation.context_type == context_type,
            )
            .order_by(Recommendation.created_at.desc())
            .limit(max(1, min(limit, 20)))
        )
        return [self._item_to_dict(item) for item in result.scalars().all()]

    async def recommend_for_context(
        self,
        user_id: int,
        context_type: str,
        context_data: dict[str, Any],
        limit: int = 5,
    ) -> dict[str, Any]:
        context_type = (context_type or "general").strip().lower()
        limit = max(1, min(int(limit), 20))
        profile = await self._get_profile(user_id)
        history = await self._history_signals(user_id)
        candidates = await self._load_candidates(user_id, history)
        ranked = self._rank_candidates(
            candidates,
            context_type=context_type,
            context_data=context_data or {},
            profile=profile,
            history=history,
        )[:limit]

        context_fingerprint = hashlib.sha256(
            json.dumps(
                {"type": context_type, "data": context_data or {}},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:20]
        confidence = round(
            sum(float(item["score"]) for item in ranked) / max(len(ranked), 1), 3
        )
        record = Recommendation(
            user_id=user_id,
            context_type=context_type,
            context_id=context_fingerprint,
            recommended_items=ranked,
            reason="基于当前任务、研究领域、既有工作流/插件和显式反馈进行排序",
            confidence=confidence,
            created_at=datetime.now(),
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return self._item_to_dict(record)

    async def get_history(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(Recommendation)
            .where(Recommendation.user_id == user_id)
            .order_by(Recommendation.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        return [self._item_to_dict(item) for item in result.scalars().all()]

    async def record_feedback(
        self,
        user_id: int,
        *,
        item_type: str,
        item_name: str,
        accepted: bool,
    ) -> dict[str, Any]:
        if item_type not in {"skill", "plugin", "workflow"}:
            raise ValueError("item_type must be skill, plugin or workflow")
        item_name = item_name.strip()
        if not item_name:
            raise ValueError("item_name must not be empty")
        profile = await self._get_profile(user_id, create=True)
        preferences = dict(profile.skill_preferences or {})
        feedback = dict(preferences.get("recommendation_feedback") or {})
        key = f"{item_type}:{item_name}"
        stats = dict(feedback.get(key) or {})
        field = "accepted" if accepted else "rejected"
        stats[field] = int(stats.get(field, 0)) + 1
        stats["updated_at"] = datetime.now().isoformat()
        feedback[key] = stats
        preferences["recommendation_feedback"] = feedback
        profile.skill_preferences = preferences
        await self.db.commit()
        return {"item_key": key, **stats}

    async def _get_profile(self, user_id: int, create: bool = False) -> UserProfile | None:
        result = await self.db.execute(
            select(UserProfile)
            .where(UserProfile.user_id == user_id)
            .order_by(UserProfile.id.desc())
        )
        profile = result.scalars().first()
        if profile is None and create:
            profile = UserProfile(user_id=user_id, research_fields=[], skill_preferences={})
            self.db.add(profile)
            await self.db.flush()
        return profile

    async def _history_signals(self, user_id: int) -> dict[str, Any]:
        installation_result = await self.db.execute(
            select(PluginInstallation.plugin_id).where(
                PluginInstallation.user_id == user_id,
                PluginInstallation.status == "installed",
            )
        )
        installed_plugins = set(installation_result.scalars().all())

        run_result = await self.db.execute(
            select(WorkflowRun.workflow_id)
            .where(WorkflowRun.user_id == user_id)
            .order_by(WorkflowRun.created_at.desc())
            .limit(200)
        )
        workflow_runs: dict[int, int] = {}
        for workflow_id in run_result.scalars().all():
            workflow_runs[int(workflow_id)] = workflow_runs.get(int(workflow_id), 0) + 1
        return {
            "installed_plugins": installed_plugins,
            "workflow_runs": workflow_runs,
        }

    async def _load_candidates(
        self,
        user_id: int,
        history: dict[str, Any],
    ) -> list[dict[str, Any]]:
        SkillRegistry.initialize_builtin()
        candidates: list[dict[str, Any]] = []
        for name, metadata in SkillRegistry.list_all().items():
            candidates.append(
                {
                    "type": "skill",
                    "name": name,
                    "description": metadata.get("description", ""),
                    "category": metadata.get("category", ""),
                    "tags": metadata.get("modalities", []),
                    "executable": True,
                }
            )

        plugin_result = await self.db.execute(
            select(Plugin).where(Plugin.status.notin_(["disabled", "archived"]))
        )
        installed = history["installed_plugins"]
        for plugin in plugin_result.scalars().all():
            candidates.append(
                {
                    "type": "plugin",
                    "id": plugin.id,
                    "name": plugin.name,
                    "description": plugin.description or "",
                    "category": plugin.category or "",
                    "tags": plugin.tags or [],
                    "version": plugin.latest_version or plugin.version,
                    "installed": plugin.id in installed,
                    "executable": plugin.id in installed,
                }
            )

        workflow_result = await self.db.execute(
            select(Workflow).where(
                or_(Workflow.author == user_id, Workflow.is_public.is_(True)),
                Workflow.status != "archived",
            )
        )
        workflow_runs = history["workflow_runs"]
        for workflow in workflow_result.scalars().all():
            candidates.append(
                {
                    "type": "workflow",
                    "id": workflow.id,
                    "name": workflow.name,
                    "description": workflow.description or "",
                    "category": workflow.category or "",
                    "tags": workflow.tags or [],
                    "version": workflow.version,
                    "run_count": workflow_runs.get(workflow.id, 0),
                    "executable": True,
                }
            )
        return candidates

    def _rank_candidates(
        self,
        candidates: Iterable[dict[str, Any]],
        *,
        context_type: str,
        context_data: dict[str, Any],
        profile: UserProfile | None,
        history: dict[str, Any],
    ) -> list[dict[str, Any]]:
        priors = self._CATEGORY_PRIORS.get(context_type, self._CATEGORY_PRIORS["general"])
        context_tokens = _tokens({"context_type": context_type, **context_data})
        research_tokens = _tokens(profile.research_fields if profile else [])
        preferences = dict(profile.skill_preferences or {}) if profile else {}
        feedback = dict(preferences.get("recommendation_feedback") or {})
        ranked: list[dict[str, Any]] = []

        for original in candidates:
            item = dict(original)
            category = str(item.get("category") or "").lower()
            candidate_tokens = _tokens(
                {
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "category": category,
                    "tags": item.get("tags", []),
                }
            )
            score = 0.08
            reasons: list[str] = []
            prior = priors.get(category, 0.0)
            if prior:
                score += prior
                reasons.append(f"匹配 {context_type} 场景")

            overlap = context_tokens & candidate_tokens
            if overlap:
                score += min(0.32, 0.08 * len(overlap))
                reasons.append("匹配任务关键词: " + ", ".join(sorted(overlap)[:4]))

            research_overlap = research_tokens & candidate_tokens
            if research_overlap:
                score += min(0.20, 0.07 * len(research_overlap))
                reasons.append("符合用户研究领域")

            if item["type"] == "plugin" and item.get("installed"):
                score += 0.10
                reasons.append("用户已安装")
            if item["type"] == "workflow" and item.get("run_count"):
                score += min(0.18, 0.04 * math.log2(item["run_count"] + 1))
                reasons.append("近期使用过该工作流")

            stats = feedback.get(f"{item['type']}:{item['name']}", {})
            accepted = int(stats.get("accepted", 0))
            rejected = int(stats.get("rejected", 0))
            if accepted or rejected:
                score += max(-0.30, min(0.25, 0.08 * (accepted - rejected)))
                reasons.append("已结合历史反馈")

            item["score"] = round(max(0.0, min(score, 0.99)), 3)
            item["reasons"] = reasons or ["系统中可用的通用能力"]
            ranked.append(item)

        ranked.sort(key=lambda item: (-item["score"], item["type"], item["name"]))
        return ranked

    @staticmethod
    def _item_to_dict(item: Recommendation) -> dict[str, Any]:
        return {
            "id": item.id,
            "user_id": item.user_id,
            "context_type": item.context_type,
            "context_id": item.context_id,
            "recommended_items": item.recommended_items or [],
            "reason": item.reason,
            "confidence": item.confidence,
            "created_at": item.created_at,
        }


__all__ = ["RecommendationEngine"]
