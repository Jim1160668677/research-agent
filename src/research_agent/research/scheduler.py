"""能力前置策略过滤、并发限制、超时和有界重试。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .contracts import CapabilityHandler, CapabilityResult, CapabilitySpec


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""


class ToolPolicy:
    """在能力交给模型或执行器前完成硬性过滤。"""

    def __init__(self, policy: dict[str, Any]):
        self.network_allowed = bool(policy.get("network_allowed", True))
        self.allowed = set(policy.get("allowed_capabilities") or [])
        self.approved = set(policy.get("approved_capabilities") or [])
        self.deny_unlisted = bool(policy.get("deny_unlisted", True))

    def evaluate(self, spec: CapabilitySpec) -> PolicyDecision:
        if self.deny_unlisted and spec.name not in self.allowed:
            return PolicyDecision(False, f"能力 {spec.name} 不在本次运行白名单中")
        if spec.network_access and not self.network_allowed:
            return PolicyDecision(False, f"能力 {spec.name} 需要网络，但本次运行禁止联网")
        if spec.requires_approval and spec.name not in self.approved:
            return PolicyDecision(False, f"能力 {spec.name} 尚未获得用户批准")
        return PolicyDecision(True)


@dataclass
class ScheduledResult:
    result: CapabilityResult
    attempts: int


class CapabilityScheduler:
    def __init__(self, global_semaphore: asyncio.Semaphore, per_run_concurrency: int = 2):
        self.global_semaphore = global_semaphore
        self.run_semaphore = asyncio.Semaphore(min(max(per_run_concurrency, 1), 4))

    async def execute(
        self,
        spec: CapabilitySpec,
        handler: CapabilityHandler,
        payload: dict[str, Any],
        policy: ToolPolicy,
    ) -> ScheduledResult:
        decision = policy.evaluate(spec)
        if not decision.allowed:
            return ScheduledResult(
                CapabilityResult(
                    status="blocked",
                    output={"policy_decision": "denied"},
                    warnings=[decision.reason],
                    confidence=1.0,
                ),
                attempts=0,
            )

        attempts = 0
        last_error = ""
        while attempts <= spec.max_retries:
            attempts += 1
            try:
                from ..runtime_coordinator import get_runtime_coordinator
                coordinator = get_runtime_coordinator()
                operation_id = f"{payload.get('run_id', 'unknown')}:{spec.name}"
                async with coordinator.lease("research", operation_id):
                    async with self.global_semaphore:
                        async with self.run_semaphore:
                            result = await asyncio.wait_for(
                                handler(payload), timeout=spec.timeout_seconds
                            )
                if result.status not in {"completed", "degraded", "blocked"}:
                    result.status = "degraded"
                return ScheduledResult(result=result, attempts=attempts)
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                last_error = f"执行超过 {spec.timeout_seconds} 秒"
            except Exception as exc:
                last_error = str(exc)[:500]
            if attempts <= spec.max_retries:
                await asyncio.sleep(min(0.25 * attempts, 1.0))

        return ScheduledResult(
            CapabilityResult(
                status="failed",
                output={},
                warnings=[f"能力执行失败: {last_error}"],
                confidence=0.0,
            ),
            attempts=attempts,
        )
