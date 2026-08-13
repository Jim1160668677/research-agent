"""科研任务运行时：计划、策略、能力调度、证据与受控学习。"""

from .manager import get_run_manager, recover_research_runs, shutdown_run_manager
from .planner import ResearchPlanner

__all__ = ["ResearchPlanner", "get_run_manager", "recover_research_runs", "shutdown_run_manager"]
