"""科研辅助技能 - 文献分析、统计建模、数据可视化"""

from typing import Dict, List, Any
from ..base import BaseSkill, SkillParameter, SkillOutput


class LiteratureSummarySkill(BaseSkill):
    """文献摘要技能"""

    def __init__(self):
        super().__init__(
            name="literature_summary",
            description="对文献集合进行主题归纳与摘要生成",
            category="literature",
            parameters=[
                SkillParameter("pmids", "list", "文献PMID列表", required=True),
                SkillParameter("max_length", "integer", "摘要最大长度", default=500),
            ],
            output_schema=[
                SkillOutput("summary", "string", "文献摘要"),
            ],
            modalities=["text", "bibliography"],
            risk_level="medium",
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        pmids = kwargs["pmids"]
        return {
            "summary": "仅收到文献标识符，尚未取得摘要或全文，因此未生成事实性综述。",
            "evidence_ids": [str(item) for item in pmids],
            "status": "needs_source_content",
            "warning": "请先检索文献元数据/摘要，正式综述还需全文筛选与偏倚评估。",
        }


class ExperimentalDesignSkill(BaseSkill):
    """实验设计建议技能"""

    def __init__(self):
        super().__init__(
            name="experimental_design",
            description="根据研究目标和已有数据提供实验设计方案建议",
            category="research",
            parameters=[
                SkillParameter("objective", "string", "研究目标", required=True),
                SkillParameter("data_type", "string", "数据类型: rna_seq/chip_seq/单细胞/蛋白组", required=True),
                SkillParameter("samples", "integer", "样本数", default=3),
            ],
            risk_level="medium",
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        from ....research.services import experimental_design

        objective = kwargs["objective"]
        result = await experimental_design({
            "objective": objective,
            "context": {"data_type": kwargs["data_type"], "nominal_replicates": kwargs.get("samples", 3)},
        })
        output = dict(result.output)
        output.update({
            "data_type": kwargs["data_type"],
            "suggestion": "先定义主要结局与估计目标，再用效应量、变异和功效计算样本量。",
            "replicates": kwargs.get("samples", 3),
            "steps": ["明确估计目标", "设计对照与偏倚控制", "完成样本量计算", "预注册分析计划", "通过伦理与质量门"],
            "warnings": result.warnings,
        })
        return output


class EvidenceSynthesisSkill(BaseSkill):
    """对已提供的文献记录生成带定位信息的证据表。"""

    def __init__(self):
        super().__init__(
            name="evidence_synthesis",
            description="对已提供的文献元数据/摘要去重并生成可追溯证据表",
            category="literature",
            parameters=[
                SkillParameter("query", "string", "研究问题", required=True),
                SkillParameter("records", "list", "包含 PMID/DOI/标题/摘要的文献记录", required=True),
            ],
            modalities=["text", "bibliography"],
            risk_level="medium",
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        from ....research.services import evidence_review

        result = await evidence_review({
            "query": kwargs["query"],
            "context": {"literature_records": kwargs["records"]},
        })
        return {**result.output, "confidence": result.confidence, "warnings": result.warnings}


class ResearchWritingSupportSkill(BaseSkill):
    """生成证据约束的科研写作结构。"""

    def __init__(self):
        super().__init__(
            name="research_writing_support",
            description="生成科研写作脚手架与主张—证据矩阵，不虚构引用",
            category="writing",
            parameters=[
                SkillParameter("objective", "string", "研究目标", required=True),
                SkillParameter("evidence_records", "list", "归一化证据记录", required=False, default=[]),
            ],
            risk_level="medium",
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        from ....research.services import research_writing

        result = await research_writing({
            "objective": kwargs["objective"],
            "context": {},
            "dependency_outputs": {"literature": {"evidence_table": kwargs.get("evidence_records", [])}},
        })
        return {**result.output, "confidence": result.confidence, "warnings": result.warnings}


class AcademicIntegrityCheckSkill(BaseSkill):
    """检查学术写作中的可定位规范问题。"""

    def __init__(self):
        super().__init__(
            name="academic_integrity_check",
            description="检查引用、统计报告、因果措辞和人/动物伦理声明",
            category="integrity",
            parameters=[
                SkillParameter("text", "string", "待检查手稿", required=True),
                SkillParameter("objective", "string", "研究目标", required=False, default=""),
            ],
            risk_level="medium",
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        from ....research.services import integrity_check

        result = await integrity_check({
            "text": kwargs["text"],
            "objective": kwargs.get("objective", ""),
            "context": {},
            "dependency_outputs": {},
        })
        return {**result.output, "confidence": result.confidence, "warnings": result.warnings}


class StatisticalTestSkill(BaseSkill):
    """统计检验技能"""

    def __init__(self):
        super().__init__(
            name="statistical_test",
            description="执行常用统计检验 (t检验、方差分析、卡方检验、秩和检验)",
            category="statistics",
            parameters=[
                SkillParameter("group1", "list", "第一组数据", required=True),
                SkillParameter("group2", "list", "第二组数据", required=False),
                SkillParameter("test", "string", "检验方法: ttest/anova/chi2/mannwhitney/wilcoxon", default="ttest"),
                SkillParameter("paired", "boolean", "是否配对", default=False),
            ],
            output_schema=[
                SkillOutput("statistic", "number", "统计量"),
                SkillOutput("p_value", "number", "P值"),
                SkillOutput("significant", "boolean", "是否显著"),
            ],
            modalities=["table"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        import scipy.stats as stats
        import numpy as np

        test = kwargs.get("test", "ttest")
        g1 = np.array(kwargs["group1"], dtype=float)
        g2 = np.array(kwargs.get("group2", []), dtype=float) if kwargs.get("group2") else None
        paired = kwargs.get("paired", False)

        if len(g1) < 2 or not np.all(np.isfinite(g1)):
            raise ValueError("第一组至少需要 2 个有限数值")
        if g2 is not None and (len(g2) < 2 or not np.all(np.isfinite(g2))):
            raise ValueError("第二组至少需要 2 个有限数值")
        if paired and (g2 is None or len(g1) != len(g2)):
            raise ValueError("配对检验要求两组长度相同")

        if test == "ttest" and g2 is not None:
            if paired and len(g1) == len(g2):
                statistic, p = stats.ttest_rel(g1, g2)
            else:
                statistic, p = stats.ttest_ind(g1, g2, equal_var=False)
        elif test == "mannwhitney" and g2 is not None:
            statistic, p = stats.mannwhitneyu(g1, g2)
        elif test == "wilcoxon" and g2 is not None:
            statistic, p = stats.wilcoxon(g1, g2)
        elif test == "anova":
            if g2 is None:
                raise ValueError("ANOVA需要至少两组数据")
            statistic, p = stats.f_oneway(g1, g2)
        elif test == "chi2":
            if g2 is None:
                raise ValueError("卡方检验需要两个组数据")
            observed = np.array([g1, g2])
            statistic, p, _, _ = stats.chi2_contingency(observed)
        elif test == "ttest" and g2 is None:
            statistic, p = stats.ttest_1samp(g1, 0)
        else:
            raise ValueError(f"未知或参数不完整的检验方法: {test}")

        if not np.isfinite(statistic) or not np.isfinite(p):
            raise ValueError("统计量不可计算；请检查常数列、样本量或输入分布")

        return {
            "statistic": float(statistic),
            "p_value": float(p),
            "significant": bool(p < 0.05),
            "test": test,
            "alpha": 0.05,
            "reporting_note": "请同时报告效应量、95%置信区间、样本量、假设检验和多重比较策略。",
        }


class CorrelationSkill(BaseSkill):
    """相关性分析技能"""

    def __init__(self):
        super().__init__(
            name="correlation_analysis",
            description="计算两组数据的相关性 (Pearson/Spearman)",
            category="statistics",
            parameters=[
                SkillParameter("x", "list", "X数据", required=True),
                SkillParameter("y", "list", "Y数据", required=True),
                SkillParameter("method", "string", "方法: pearson/spearman/kendall", default="pearson"),
            ],
            modalities=["table"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        import scipy.stats as stats
        import numpy as np

        x = np.array(kwargs["x"], dtype=float)
        y = np.array(kwargs["y"], dtype=float)
        method = kwargs.get("method", "pearson")

        if len(x) != len(y):
            raise ValueError("X和Y的长度必须一致")
        if len(x) < 3 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError("相关分析至少需要 3 对有限数值")
        if np.all(x == x[0]) or np.all(y == y[0]):
            raise ValueError("常数序列无法计算相关系数")

        if method == "pearson":
            r, p = stats.pearsonr(x, y)
        elif method == "spearman":
            r, p = stats.spearmanr(x, y)
        elif method == "kendall":
            r, p = stats.kendalltau(x, y)
        else:
            raise ValueError(f"未知方法: {method}")

        return {
            "correlation": float(r),
            "p_value": float(p),
            "method": method,
            "n": len(x),
            "significant": bool(p < 0.05),
        }


class VolcanoPlotSkill(BaseSkill):
    """火山图绘制技能"""

    def __init__(self):
        super().__init__(
            name="volcano_plot",
            description="绘制差异表达火山图",
            category="visualization",
            parameters=[
                SkillParameter("log2fc", "list", "log2倍数变化列表", required=True),
                SkillParameter("pvalues", "list", "P值列表", required=True),
                SkillParameter("labels", "list", "基因标签列表", required=False),
                SkillParameter("output_path", "string", "输出文件路径", default="./volcano_plot.png"),
            ],
            modalities=["table", "image"],
            writes_files=True,
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        log2fc = np.array(kwargs["log2fc"], dtype=float)
        pvalues = np.array(kwargs["pvalues"], dtype=float)
        labels = kwargs.get("labels")
        output_path = kwargs.get("output_path", "./volcano_plot.png")

        if len(log2fc) != len(pvalues) or not len(log2fc):
            raise ValueError("log2fc 与 pvalues 必须为相同长度的非空列表")
        if not np.all(np.isfinite(log2fc)) or not np.all(np.isfinite(pvalues)):
            raise ValueError("绘图数据必须是有限数值")
        if np.any(pvalues < 0) or np.any(pvalues > 1):
            raise ValueError("P 值必须位于 [0, 1]")

        # 避免log(0)
        pvalues = np.clip(pvalues, 1e-300, None)
        neg_log10p = -np.log10(pvalues)

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.scatter(log2fc, neg_log10p, alpha=0.6, s=20, c="gray")

        # 显著性阈值线
        ax.axhline(-np.log10(0.05), color="gray", linestyle="--", linewidth=0.8)
        ax.axvline(1, color="gray", linestyle="--", linewidth=0.8)
        ax.axvline(-1, color="gray", linestyle="--", linewidth=0.8)

        # 标注显著基因
        if labels is not None:
            significant = (np.abs(log2fc) > 1) & (pvalues < 0.05)
            for i, label in enumerate(labels):
                if significant[i] and i < 50:
                    ax.annotate(label, (log2fc[i], neg_log10p[i]), fontsize=6, alpha=0.7)

        ax.set_xlabel("log2 Fold Change")
        ax.set_ylabel("-log10(P-value)")
        ax.set_title("Volcano Plot")

        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)

        return {
            "success": True,
            "output_path": output_path,
            "total_genes": len(log2fc),
            "upregulated": int(np.sum((log2fc > 1) & (pvalues < 0.05))),
            "downregulated": int(np.sum((log2fc < -1) & (pvalues < 0.05))),
        }


class HeatmapSkill(BaseSkill):
    """热图绘制技能"""

    def __init__(self):
        super().__init__(
            name="heatmap",
            description="绘制基因表达热图",
            category="visualization",
            parameters=[
                SkillParameter("data", "list", "数据矩阵 (二维列表)", required=True),
                SkillParameter("row_labels", "list", "行标签", required=False),
                SkillParameter("col_labels", "list", "列标签", required=False),
                SkillParameter("output_path", "string", "输出文件路径", default="./heatmap.png"),
                SkillParameter("cmap", "string", "颜色映射", default="RdBu_r"),
            ],
            modalities=["table", "image"],
            writes_files=True,
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        data = np.array(kwargs["data"], dtype=float)
        row_labels = kwargs.get("row_labels")
        col_labels = kwargs.get("col_labels")
        output_path = kwargs.get("output_path", "./heatmap.png")
        cmap = kwargs.get("cmap", "RdBu_r")

        if data.ndim != 2 or data.size == 0 or not np.all(np.isfinite(data)):
            raise ValueError("热图数据必须是非空的二维有限数值矩阵")

        fig, ax = plt.subplots(figsize=(10, 8))
        im = ax.imshow(data, cmap=cmap, aspect="auto")

        if row_labels:
            ax.set_yticks(range(len(row_labels)))
            ax.set_yticklabels(row_labels, fontsize=7)
        if col_labels:
            ax.set_xticks(range(len(col_labels)))
            ax.set_xticklabels(col_labels, rotation=45, ha="right", fontsize=8)

        fig.colorbar(im, ax=ax, label="Expression")
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)

        return {
            "success": True,
            "output_path": output_path,
            "shape": list(data.shape),
        }


def register_research_skills(registry):
    """注册所有科研辅助技能"""
    registry.register(LiteratureSummarySkill())
    registry.register(ExperimentalDesignSkill())
    registry.register(EvidenceSynthesisSkill())
    registry.register(ResearchWritingSupportSkill())
    registry.register(AcademicIntegrityCheckSkill())
    registry.register(StatisticalTestSkill())
    registry.register(CorrelationSkill())
    registry.register(VolcanoPlotSkill())
    registry.register(HeatmapSkill())


__all__ = ["register_research_skills"]
