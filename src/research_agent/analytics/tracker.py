"""用户行为追踪与需求收集模块

用于收集匿名化的用户使用数据，驱动产品决策和需求迭代。
遵循隐私优先原则:
- 默认仅收集聚合统计数据 (不收集个人内容)
- 用户可在设置中禁用追踪
- 所有数据本地聚合，定期上传 (可选)
"""

import json
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class EventTracker:
    """事件追踪器 - 收集用户行为数据用于需求分析"""

    def __init__(self, storage_dir: Path, enabled: bool = True):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self._events: list[dict] = []
        self._event_counts: dict[str, int] = defaultdict(int)
        self._session_start = time.time()
        self._lock = threading.Lock()
        self._flush_interval = 60  # 秒
        self._flush_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # 加载历史统计
        self._load_stats()

        # 启动后台刷新线程
        if self.enabled:
            self._start_flush_thread()

    def _load_stats(self):
        """加载历史统计数据"""
        stats_file = self.storage_dir / "usage_stats.json"
        try:
            if stats_file.exists():
                with open(stats_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self._event_counts = defaultdict(int, data.get("event_counts", {}))
        except (OSError, json.JSONDecodeError):
            pass

    def _save_stats(self):
        """保存统计数据到本地"""
        stats_file = self.storage_dir / "usage_stats.json"
        try:
            data = {
                "event_counts": dict(self._event_counts),
                "updated_at": datetime.now().isoformat(),
                "total_events": sum(self._event_counts.values()),
            }
            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            logger.debug(f"保存使用统计失败: {e}")

    def _start_flush_thread(self):
        """启动后台刷新线程"""
        def flush_loop():
            while not self._stop_event.wait(self._flush_interval):
                self._flush_events()

        self._flush_thread = threading.Thread(target=flush_loop, daemon=True)
        self._flush_thread.start()

    def _flush_events(self):
        """刷新事件到存储"""
        with self._lock:
            if self._events:
                self._save_events_batch()
                self._events.clear()

    def _save_events_batch(self):
        """保存事件批次"""
        if not self._events:
            return

        events_file = self.storage_dir / "events.jsonl"
        try:
            with open(events_file, "a", encoding="utf-8") as f:
                for event in self._events:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.debug(f"保存事件批次失败: {e}")

    def track(self, event_type: str, data: dict[str, Any] | None = None):
        """追踪事件"""
        if not self.enabled:
            return

        event = {
            "type": event_type,
            "timestamp": time.time(),
            "session_id": int(self._session_start),
            "data": data or {},
        }

        with self._lock:
            self._events.append(event)
            self._event_counts[event_type] += 1

        # 立即更新统计
        if len(self._events) >= 10:
            self._flush_events()

    # ---------- 预定义事件类型 ----------

    def track_page_view(self, page: str):
        """追踪页面访问"""
        self.track("page_view", {"page": page})

    def track_plugin_usage(self, plugin_name: str, action: str = "use"):
        """追踪插件使用"""
        self.track("plugin_usage", {"plugin": plugin_name, "action": action})

    def track_workflow_run(self, workflow_id: int, status: str):
        """追踪工作流执行"""
        self.track("workflow_run", {"workflow_id": workflow_id, "status": status})

    def track_chat_interaction(self, provider: str, model: str, turn_count: int):
        """追踪对话交互 (匿名化)"""
        self.track("chat_interaction", {
            "provider": provider,
            "model": model,
            "turn_count": turn_count,
        })

    def track_error(self, error_type: str, component: str):
        """追踪错误发生"""
        self.track("error", {"type": error_type, "component": component})

    def track_feature_usage(self, feature: str, metadata: dict | None = None):
        """追踪功能使用"""
        self.track("feature_usage", {"feature": feature, "metadata": metadata or {}})

    def track_search(self, query: str, results_count: int):
        """追踪搜索行为 (不记录查询内容原文)"""
        self.track("search", {
            "query_length": len(query),
            "results_count": results_count,
        })

    def track_time_spent(self, feature: str, duration_seconds: float):
        """追踪功能停留时间"""
        self.track("time_spent", {
            "feature": feature,
            "duration_seconds": round(duration_seconds, 1),
        })

    # ---------- 使用场景模拟 ----------

    def get_usage_summary(self) -> dict[str, Any]:
        """获取使用数据摘要 (用于需求分析)"""
        with self._lock:
            total = sum(self._event_counts.values())
            by_type = dict(self._event_counts)

            # 计算高频功能
            top_features = sorted(
                [(k, v) for k, v in self._event_counts.items()
                 if k.startswith("feature_usage") or k.startswith("plugin_usage")],
                key=lambda x: x[1],
                reverse=True,
            )[:10]

            # 错误统计
            error_count = self._event_counts.get("error", 0)

            return {
                "total_events": total,
                "event_types": len(by_type),
                "top_features": top_features,
                "error_count": error_count,
                "session_duration_minutes": round(
                    (time.time() - self._session_start) / 60, 1
                ),
                "event_counts": by_type,
            }

    def get_requirement_insights(self) -> list[dict[str, Any]]:
        """基于使用数据生成需求洞察"""
        insights = []
        summary = self.get_usage_summary()

        # 高频未满足功能检测
        low_usage_threshold = 5
        for event_type, count in summary["event_counts"].items():
            if count > 0 and event_type.startswith("error"):
                insights.append({
                    "type": "error_hotspot",
                    "severity": "high",
                    "description": f"错误事件 {event_type} 发生 {count} 次",
                    "suggestion": "检查相关组件的错误处理和日志",
                })

        # 低使用功能检测 (可能需要改善可达性)
        feature_usage = [
            (k, v) for k, v in summary["event_counts"].items()
            if k.startswith("feature_usage") and v < low_usage_threshold
        ]
        if feature_usage:
            insights.append({
                "type": "low_adoption",
                "severity": "medium",
                "description": f"{len(feature_usage)} 个功能使用率较低",
                "suggestion": "评估功能 discoverability 和用户引导",
            })

        return insights

    def shutdown(self):
        """关闭追踪器"""
        self._stop_event.set()
        self._flush_events()
        self._save_stats()
        logger.debug("事件追踪器已关闭")


# ============================================================
# 使用场景模拟器
# ============================================================

class UsageScenarioSimulator:
    """使用场景模拟器 - 帮助识别需求缺口"""

    SCENARIOS = {
        "molecular_docking": {
            "name": "分子对接",
            "steps": [
                "导入蛋白质结构",
                "导入小分子配体",
                "设置对接参数",
                "运行对接计算",
                "分析结合模式",
                "导出结果",
            ],
            "required_features": [
                "pdb_parser",
                "molecule_viewer",
                "docking_engine",
                "result_analyzer",
            ],
        },
        "literature_review": {
            "name": "文献综述",
            "steps": [
                "定义研究主题",
                "检索论文数据库",
                "筛选相关文献",
                "阅读和标注",
                "生成综述大纲",
                "输出引用列表",
            ],
            "required_features": [
                "ncbi_search",
                "pdf_reader",
                "citation_manager",
                "llm_summarizer",
            ],
        },
        "data_analysis": {
            "name": "数据分析",
            "steps": [
                "导入实验数据",
                "数据清洗",
                "统计分析",
                "生成可视化图表",
                "拟合模型",
                "生成报告",
            ],
            "required_features": [
                "data_importer",
                "statistical_tests",
                "plot_generator",
                "model_fitter",
            ],
        },
        "methodology_design": {
            "name": "实验方法设计",
            "steps": [
                "定义研究假设",
                "设计实验组",
                "计算样本量",
                "随机化方案",
                "生成实验方案",
                "风险评估",
            ],
            "required_features": [
                "hypothesis_tester",
                "sample_size_calculator",
                "randomization_tool",
                "protocol_generator",
            ],
        },
    }

    def __init__(self):
        self._completion_cache: dict[str, float] = {}

    def analyze_scenario(self, scenario_key: str, available_features: set) -> dict:
        """分析场景完成度和需求缺口"""
        scenario = self.SCENARIOS.get(scenario_key)
        if not scenario:
            return {"error": f"未知场景: {scenario_key}"}

        required = set(scenario["required_features"])
        available_in_scenario = required & available_features
        missing = required - available_features

        completion_rate = len(available_in_scenario) / len(required) if required else 1.0

        # 分析步骤依赖
        step_coverage = []
        for i, step in enumerate(scenario["steps"]):
            has_support = self._estimate_step_support(step, available_features)
            step_coverage.append({
                "step": step,
                "supported": has_support,
                "priority": i + 1,
            })

        return {
            "scenario": scenario["name"],
            "completion_rate": round(completion_rate, 2),
            "required_features": len(required),
            "available_features": len(available_in_scenario),
            "missing_features": list(missing),
            "step_coverage": step_coverage,
            "recommendations": self._generate_recommendations(
                scenario, missing, completion_rate
            ),
        }

    def _estimate_step_support(self, step: str, available: set) -> bool:
        """估算步骤是否有功能支持 (启发式)"""
        step_lower = step.lower()
        support_keywords = {
            "导入": {"importer", "parser", "loader"},
            "检索": {"search", "query", "retriever"},
            "分析": {"analyzer", "viewer"},
            "生成": {"generator", "plot", "report"},
            "计算": {"calculator", "engine", "solver"},
            "设计": {"designer", "builder", "creator"},
        }
        keywords = support_keywords.get(step_lower[:2], set())
        return bool(keywords & available)

    def _generate_recommendations(self, scenario: dict, missing: set,
                                    completion_rate: float) -> list[str]:
        """生成改进建议"""
        recommendations = []

        if completion_rate < 0.3:
            recommendations.append(
                f"场景 '{scenario['name']}' 完成度仅 {completion_rate:.0%}，"
                "建议优先构建核心功能模块"
            )

        for feature in missing:
            priority = "high" if len(missing) <= 3 else "medium"
            recommendations.append(
                f"- [{priority.upper()}] 需开发: {feature}"
            )

        return recommendations

    def get_all_scenario_analyses(self, available_features: set) -> list[dict]:
        """分析所有场景"""
        results = []
        for key in self.SCENARIOS:
            results.append(self.analyze_scenario(key, available_features))
        return results


__all__ = [
    "EventTracker",
    "UsageScenarioSimulator",
    "get_tracker",
    "set_tracker",
    "get_simulator",
    "set_simulator",
]


# ---------- 全局实例管理 ----------
_tracker_instance: Optional["EventTracker"] = None
_simulator_instance: Optional["UsageScenarioSimulator"] = None


def get_tracker() -> Optional["EventTracker"]:
    """获取全局 EventTracker 实例"""
    return _tracker_instance


def set_tracker(tracker: "EventTracker"):
    """设置全局 EventTracker 实例"""
    global _tracker_instance
    _tracker_instance = tracker


def get_simulator() -> Optional["UsageScenarioSimulator"]:
    """获取全局 UsageScenarioSimulator 实例"""
    return _simulator_instance


def set_simulator(simulator: "UsageScenarioSimulator"):
    """设置全局 UsageScenarioSimulator 实例"""
    global _simulator_instance
    _simulator_instance = simulator
