"""可解释、确定性的科研任务规划器。"""

from __future__ import annotations

import uuid
from typing import Any

from .contracts import CAPABILITIES, PlanStep, ResearchPlan


class ResearchPlanner:
    """把研究目标拆成有依赖关系、可校验的能力调用。

    规划本身不调用外部模型，因此即使没有 API Key 也能稳定工作。LLM 只可
    在能力内部增强内容，不能绕过此处的预算、权限和人工复核门。
    """

    DOMAIN_ORDER = [
        "multimodal",
        "literature",
        "discovery",
        "experiment",
        "data",
        "multi_omics",
        "writing",
        "integrity",
    ]
    KEYWORDS = {
        "literature": ("文献", "论文", "综述", "pubmed", "证据", "研究进展", "literature"),
        "discovery": ("假设", "机制", "靶点", "新颖", "创新", "hypothesis", "mechanism", "target"),
        "experiment": ("实验", "试验", "样本量", "对照", "随机", "盲法", "design", "protocol"),
        "data": ("数据", "统计", "分析", "可视化", "csv", "tsv", "表达矩阵", "dataset"),
        "writing": ("写作", "论文", "摘要", "引言", "方法", "讨论", "manuscript", "writing"),
        "integrity": ("规范", "伦理", "引用", "学术", "查重", "合规", "consort", "prisma"),
        "multi_omics": ("scRNA", "scRNA-seq", "单细胞", "空间转录", "spatial", "multi-omics", "多组学融合", "融合分析"),
    }
    DOMAIN_CAPABILITY = {
        "multimodal": "artifact_intake",
        "literature": "evidence_review",
        "discovery": "hypothesis_generation",
        "experiment": "experimental_design",
        "data": "data_analysis",
        "writing": "research_writing",
        "integrity": "integrity_check",
        "multi_omics": "multi_omics_fusion",
    }

    def infer_domains(
        self,
        objective: str,
        requested: list[str] | None = None,
        artifact_ids: list[str] | None = None,
    ) -> list[str]:
        if requested:
            invalid = sorted(set(requested) - set(self.DOMAIN_ORDER))
            if invalid:
                raise ValueError(f"不支持的研究域: {', '.join(invalid)}")
            domains = set(requested)
        else:
            lower = objective.lower()
            domains = {
                domain
                for domain, keywords in self.KEYWORDS.items()
                if any(keyword in lower for keyword in keywords)
            }
            if not domains:
                domains = {"literature", "experiment", "writing", "integrity"}

        if artifact_ids:
            domains.update({"multimodal", "data"})
        if "writing" in domains:
            domains.add("integrity")
        return [domain for domain in self.DOMAIN_ORDER if domain in domains]

    def plan(
        self,
        objective: str,
        domains: list[str] | None = None,
        artifact_ids: list[str] | None = None,
        context: dict[str, Any] | None = None,
        network_allowed: bool = True,
        max_concurrency: int = 2,
    ) -> ResearchPlan:
        objective = " ".join(objective.split()).strip()
        if len(objective) < 6:
            raise ValueError("研究目标过短，请至少描述研究对象和要解决的问题")
        if len(objective) > 4000:
            raise ValueError("研究目标不能超过 4000 个字符")

        artifact_ids = list(dict.fromkeys(artifact_ids or []))[:20]
        context = dict(context or {})
        selected = self.infer_domains(objective, domains, artifact_ids)
        steps: list[PlanStep] = []

        if "multimodal" in selected:
            steps.append(
                PlanStep(
                    key="intake",
                    title=CAPABILITIES["artifact_intake"].title,
                    capability="artifact_intake",
                    input_data={"artifact_ids": artifact_ids},
                )
            )

        if "literature" in selected:
            steps.append(
                PlanStep(
                    key="literature",
                    title=CAPABILITIES["evidence_review"].title,
                    capability="evidence_review",
                    input_data={
                        "query": context.get("literature_query") or objective,
                        "max_results": min(max(int(context.get("max_literature", 8)), 1), 20),
                    },
                )
            )

        if "discovery" in selected:
            previous = "literature" if "literature" in selected else None
            discovery_steps = [
                ("generation", "hypothesis_generation", ["literature"] if previous else []),
                ("reflection", "hypothesis_reflection", ["generation"]),
                ("ranking", "hypothesis_ranking", ["generation", "reflection"]),
                ("evolution", "hypothesis_evolution", ["generation", "reflection", "ranking"]),
                ("meta_review", "hypothesis_meta_review", ["evolution"]),
            ]
            for key, capability, dependencies in discovery_steps:
                steps.append(
                    PlanStep(
                        key=key,
                        title=CAPABILITIES[capability].title,
                        capability=capability,
                        dependencies=dependencies,
                        input_data={"objective": objective},
                    )
                )

        if "experiment" in selected:
            dependencies = (
                ["meta_review"]
                if "discovery" in selected
                else ["literature"]
                if "literature" in selected
                else []
            )
            steps.append(
                PlanStep(
                    key="experiment",
                    title=CAPABILITIES["experimental_design"].title,
                    capability="experimental_design",
                    dependencies=dependencies,
                    input_data={"objective": objective},
                )
            )

        if "data" in selected:
            dependencies = ["intake"] if "multimodal" in selected else []
            steps.append(
                PlanStep(
                    key="data",
                    title=CAPABILITIES["data_analysis"].title,
                    capability="data_analysis",
                    dependencies=dependencies,
                    input_data={"artifact_ids": artifact_ids},
                )
            )

        # multi_omics_fusion: triggered when scRNA-seq + spatial keywords detected
        if "multi_omics" in selected:
            omics_deps = ["intake"] if "multimodal" in selected else []
            steps.append(
                PlanStep(
                    key="multi_omics",
                    title=CAPABILITIES["multi_omics_fusion"].title,
                    capability="multi_omics_fusion",
                    dependencies=omics_deps,
                    input_data={"artifact_ids": artifact_ids},
                )
            )

        pipeline_request = context.get("pipeline")
        if isinstance(pipeline_request, dict) and pipeline_request.get("pipeline_id"):
            pipeline_dependencies = ["intake"] if "multimodal" in selected else []
            steps.append(
                PlanStep(
                    key="pipeline",
                    title=CAPABILITIES["pipeline_execution"].title,
                    capability="pipeline_execution",
                    dependencies=pipeline_dependencies,
                    input_data={"pipeline": pipeline_request},
                )
            )

        # pipeline_evolution: non-blocking proposal step after pipeline execution
        if isinstance(pipeline_request, dict) and pipeline_request.get("pipeline_id"):
            steps.append(
                PlanStep(
                    key="pipeline_evolution",
                    title=CAPABILITIES["pipeline_evolution"].title,
                    capability="pipeline_evolution",
                    dependencies=["pipeline"],
                    input_data={
                        "run_id": context.get("run_id", ""),
                        "user_id": context.get("user_id", 0),
                    },
                )
            )

        if "writing" in selected:
            dependencies = [
                step.key
                for step in steps
                if step.key in {"literature", "meta_review", "experiment", "data", "multi_omics", "pipeline", "pipeline_evolution"}
            ]
            steps.append(
                PlanStep(
                    key="writing",
                    title=CAPABILITIES["research_writing"].title,
                    capability="research_writing",
                    dependencies=dependencies,
                    input_data={
                        "objective": objective,
                        "document_type": context.get("document_type", "research_brief"),
                    },
                )
            )

        if "integrity" in selected:
            dependencies = ["writing"] if "writing" in selected else []
            steps.append(
                PlanStep(
                    key="integrity",
                    title=CAPABILITIES["integrity_check"].title,
                    capability="integrity_check",
                    dependencies=dependencies,
                    input_data={"text": context.get("manuscript", ""), "objective": objective},
                )
            )

        total_cost = sum(CAPABILITIES[step.capability].cost_units for step in steps)
        review_gates = [
            step.key for step in steps if CAPABILITIES[step.capability].requires_human_review
        ]
        assumptions = [
            "输出用于科研决策支持，不替代领域专家、伦理委员会或统计师审核。",
            "没有来源定位的内容只作为待验证建议，不作为已证实事实。",
        ]
        learned = context.get("learned_preferences") or []
        if learned:
            assumptions.append(f"已应用 {min(len(learned), 10)} 条经用户审核的规划偏好。")

        return ResearchPlan(
            id=str(uuid.uuid4()),
            objective=objective,
            domains=selected,
            steps=steps,
            assumptions=assumptions,
            review_gates=review_gates,
            budget={
                "max_steps": 14,
                "max_concurrency": min(max(max_concurrency, 1), 4),
                "cost_units": total_cost,
                "deadline_seconds": max(
                    90, sum(CAPABILITIES[s.capability].timeout_seconds for s in steps)
                ),
            },
            policy={
                "network_allowed": bool(network_allowed),
                "allowed_capabilities": [step.capability for step in steps],
                "approval_required": [
                    step.capability
                    for step in steps
                    if CAPABILITIES[step.capability].requires_approval
                ],
                "deny_unlisted": True,
            },
        )

    @staticmethod
    def validate_plan(plan: dict[str, Any]) -> list[str]:
        """在执行前验证计划的能力、唯一键与 DAG。"""
        errors: list[str] = []
        steps = plan.get("steps") or []
        keys = [step.get("key") for step in steps]
        if len(keys) != len(set(keys)):
            errors.append("步骤键必须唯一")
        if len(steps) > int((plan.get("budget") or {}).get("max_steps", 10)):
            errors.append("计划超过最大步骤预算")
        key_set = set(keys)
        for step in steps:
            if step.get("capability") not in CAPABILITIES:
                errors.append(f"未知能力: {step.get('capability')}")
            missing = set(step.get("dependencies") or []) - key_set
            if missing:
                errors.append(f"步骤 {step.get('key')} 存在未知依赖: {sorted(missing)}")

        graph = {step.get("key"): set(step.get("dependencies") or []) for step in steps}
        resolved: set[str] = set()
        while len(resolved) < len(graph):
            ready = {key for key, deps in graph.items() if key not in resolved and deps <= resolved}
            if not ready:
                errors.append("计划依赖图存在环")
                break
            resolved.update(ready)
        return errors
