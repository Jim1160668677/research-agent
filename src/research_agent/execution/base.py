"""Stable contracts shared by external scientific execution backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExecutionPlan:
    backend: str
    run_id: str
    argv: list[str]
    display_argv: list[str]
    cwd: Path
    environment: dict[str, str]
    work_dir: Path
    output_dir: Path
    report_paths: dict[str, Path]
    timeout_seconds: int
    control_paths: dict[str, Path] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "run_id": self.run_id,
            "argv": self.display_argv,
            "reports": sorted(self.report_paths),
            "timeout_seconds": self.timeout_seconds,
            "provenance": self.provenance,
        }


@dataclass(slots=True)
class ExecutionResult:
    run_id: str
    status: str
    exit_code: int | None
    stdout_tail: str = ""
    stderr_tail: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    task_summary: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "artifacts": self.artifacts,
            "task_summary": self.task_summary,
            "provenance": self.provenance,
            "error": self.error,
        }


class ExecutionBackend(ABC):
    """No backend may bypass planning, bounded paths, or explicit cancellation."""

    backend_id: str

    @abstractmethod
    async def capabilities(self, *, deep: bool = False) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def preflight(
        self,
        *,
        pipeline_id: str,
        revision: str,
        profile: str,
        network_allowed: bool,
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def prepare_pipeline(
        self,
        *,
        pipeline_id: str,
        revision: str,
        network_allowed: bool,
    ) -> dict[str, Any]:
        """Prepare immutable backend assets before allocating compute.

        Backends without external assets may keep this no-op implementation.
        Implementations must not return credentials or physical cache paths.
        """
        return {"status": "not_required"}

    @abstractmethod
    async def build_plan(
        self,
        *,
        run_id: str,
        user_id: int,
        pipeline_id: str,
        revision: str,
        profile: str,
        parameters: dict[str, Any],
        artifact_paths: dict[str, Path],
        resume: bool,
        network_allowed: bool,
        timeout_seconds: int,
    ) -> ExecutionPlan:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        raise NotImplementedError


__all__ = ["ExecutionBackend", "ExecutionPlan", "ExecutionResult"]
