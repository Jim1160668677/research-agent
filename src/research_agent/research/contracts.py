"""科研任务运行时的稳定数据契约。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    title: str
    description: str
    category: str
    modalities: tuple[str, ...] = ("text",)
    risk: RiskLevel = RiskLevel.LOW
    network_access: bool = False
    writes_artifacts: bool = False
    requires_human_review: bool = False
    requires_approval: bool = False
    timeout_seconds: int = 45
    max_retries: int = 0
    cost_units: int = 1

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["risk"] = self.risk.value
        value["modalities"] = list(self.modalities)
        return value


@dataclass
class PlanStep:
    key: str
    title: str
    capability: str
    dependencies: list[str] = field(default_factory=list)
    input_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchPlan:
    id: str
    objective: str
    domains: list[str]
    steps: list[PlanStep]
    assumptions: list[str]
    review_gates: list[str]
    budget: dict[str, Any]
    policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["steps"] = [step.to_dict() for step in self.steps]
        return value


@dataclass
class EvidenceRecord:
    id: str
    source_type: str
    locator: str
    title: str
    excerpt: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    doi: str = ""
    relevance: float = 0.0
    quality_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityResult:
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    generated_artifacts: list[dict[str, Any]] = field(default_factory=list)


CapabilityHandler = Callable[[dict[str, Any]], Awaitable[CapabilityResult]]


CAPABILITIES: dict[str, CapabilitySpec] = {
    "artifact_intake": CapabilitySpec(
        name="artifact_intake",
        title="多模态材料预检",
        description="保留原始文件并提取可验证的文本、表格或图像元数据。",
        category="multimodal",
        modalities=("text", "table", "image", "pdf"),
        writes_artifacts=False,
        timeout_seconds=60,
        cost_units=1,
    ),
    "evidence_review": CapabilitySpec(
        name="evidence_review",
        title="文献检索与证据表",
        description="检索文献、去重并输出带来源定位的证据表和证据缺口。",
        category="literature",
        modalities=("text", "bibliography"),
        network_access=True,
        timeout_seconds=50,
        max_retries=1,
        cost_units=3,
    ),
    "hypothesis_generation": CapabilitySpec(
        name="hypothesis_generation",
        title="候选假设生成",
        description="根据目标与可定位证据生成多个候选假设，并明确机制、可检验预测与证据缺口。",
        category="discovery",
        requires_human_review=True,
        timeout_seconds=20,
        cost_units=2,
    ),
    "hypothesis_reflection": CapabilitySpec(
        name="hypothesis_reflection",
        title="假设反思与反证",
        description="按可信性、新颖性、可检验性和安全性寻找反例、混杂与证据薄弱点。",
        category="discovery",
        requires_human_review=True,
        timeout_seconds=20,
        cost_units=2,
    ),
    "hypothesis_ranking": CapabilitySpec(
        name="hypothesis_ranking",
        title="成对辩论与排序",
        description="用位置无关的评分量表和成对比较排序候选假设。",
        category="discovery",
        requires_human_review=True,
        timeout_seconds=20,
        cost_units=2,
    ),
    "hypothesis_evolution": CapabilitySpec(
        name="hypothesis_evolution",
        title="假设演化",
        description="针对高价值批评修订优胜假设并保留版本与变化理由。",
        category="discovery",
        requires_human_review=True,
        timeout_seconds=20,
        cost_units=2,
    ),
    "hypothesis_meta_review": CapabilitySpec(
        name="hypothesis_meta_review",
        title="元审查与研究决策",
        description="汇总演化轨迹、剩余风险、证据缺口和下一步实验决策。",
        category="discovery",
        requires_human_review=True,
        timeout_seconds=20,
        cost_units=2,
    ),
    "experimental_design": CapabilitySpec(
        name="experimental_design",
        title="实验设计与质量门",
        description="明确估计目标、变量、对照、偏倚控制、统计计划和伦理门槛。",
        category="experiment",
        risk=RiskLevel.MEDIUM,
        requires_human_review=True,
        timeout_seconds=20,
        cost_units=2,
    ),
    "data_analysis": CapabilitySpec(
        name="data_analysis",
        title="数据质控与可视化",
        description="剖析表格数据，检查缺失与类型并生成可追溯预览图。",
        category="data",
        modalities=("table", "text"),
        writes_artifacts=True,
        timeout_seconds=60,
        cost_units=3,
    ),
    "pipeline_execution": CapabilitySpec(
        name="pipeline_execution",
        title="生产流程执行",
        description=(
            "运行固定版本 nf-core 流程（rnaseq/sarek），把 counts/VCF/报告与任务统计"
            "纳入证据与加密制品，作为下游统计与写作的输入。"
        ),
        category="analysis",
        modalities=("table", "text"),
        risk=RiskLevel.HIGH,
        network_access=True,
        writes_artifacts=True,
        requires_human_review=True,
        timeout_seconds=3600,
        max_retries=0,
        cost_units=20,
    ),
    "research_writing": CapabilitySpec(
        name="research_writing",
        title="证据约束科研写作",
        description="生成章节脚手架与主张—证据矩阵，不补写来源不明的事实。",
        category="writing",
        requires_human_review=True,
        timeout_seconds=25,
        cost_units=2,
    ),
    "integrity_check": CapabilitySpec(
        name="integrity_check",
        title="学术规范与伦理检查",
        description="检查引用、统计报告、因果措辞、伦理声明和可重复性要素。",
        category="integrity",
        requires_human_review=True,
        timeout_seconds=25,
        cost_units=2,
    ),
    "pipeline_evolution": CapabilitySpec(
        name="pipeline_evolution",
        title="流水线参数进化提案",
        description=(
            "基于历史运行结果与用户反馈，生成参数优化或流程改进提案，"
            "提交待人工审核后作为下一次运行的输入基准。"
        ),
        category="analysis",
        writes_artifacts=False,
        requires_human_review=True,
        timeout_seconds=30,
        cost_units=1,
    ),
    "multi_omics_fusion": CapabilitySpec(
        name="multi_omics_fusion",
        title="多组学智能融合分析",
        description=(
            "对 scRNA-seq 与空间转录组数据进行联合分析：统一基因空间、"
            "标准化表达矩阵、细胞类型空间定位与微环境推断。"
        ),
        category="analysis",
        modalities=("table", "text"),
        risk=RiskLevel.HIGH,
        writes_artifacts=True,
        requires_human_review=True,
        timeout_seconds=300,
        cost_units=10,
    ),
}


def list_capabilities() -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in CAPABILITIES.values()]
