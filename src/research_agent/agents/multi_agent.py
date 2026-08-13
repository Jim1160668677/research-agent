"""LangGraph 多智能体系统

架构:
    User → Coordinator (路由器) → 专业智能体
                                ├── LiteratureAgent   文献检索/分析
                                ├── AnalysisAgent     数据分析/统计
                                ├── DataAgent         NCBI数据获取
                                └── VisualizationAgent 可视化/结构渲染

Coordinator 通过 LangGraph StateGraph 调度，每个智能体执行后返回结果
由 Coordinator 汇总为最终回复 (LLM或规则)。
"""

import json
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from loguru import logger


class AgentState(TypedDict):
    """智能体共享状态"""

    user_message: str
    intent: str
    tools_used: list[str]
    skills_used: list[str]
    results: dict[str, Any]
    final_response: str
    suggestions: list[dict[str, Any]]
    error: str | None


class BaseSpecialistAgent:
    """专业智能体基类"""

    name: str = "base"
    description: str = ""

    def __init__(self, db=None):
        self.db = db
        self.skills_used: list[str] = []

    async def run(self, state: AgentState) -> dict[str, Any]:
        """执行任务，返回状态更新"""
        try:
            result = await self.execute(state)
            return {
                "results": {**state.get("results", {}), self.name: result},
                "skills_used": [*state.get("skills_used", []), *self.skills_used],
            }
        except Exception as e:
            logger.error(f"Agent [{self.name}] 执行失败: {e}")
            return {
                "results": {
                    **state.get("results", {}),
                    self.name: {"success": False, "error": str(e)},
                },
                "error": str(e),
            }

    async def execute(self, state: AgentState) -> dict[str, Any]:
        """子类实现具体逻辑"""
        raise NotImplementedError


class LiteratureAgent(BaseSpecialistAgent):
    """文献检索与分析智能体"""

    name = "literature"
    description = "检索PubMed文献、总结文献内容"

    async def execute(self, state: AgentState) -> dict[str, Any]:
        from .skills import get_executor

        message = state["user_message"]
        import re

        keywords = re.sub(r"[?？。！，,.：:]", "", message)
        keywords = keywords.replace("搜索", "").replace("查找", "").replace("检索", "")
        keywords = keywords.replace("关于", "").replace("最新", "").replace("文献", "").strip()

        executor = get_executor()
        if not keywords:
            return {"success": False, "error": "无法提取检索关键词"}

        result = await executor.execute("pubmed_search", query=keywords, max_results=10)
        self.skills_used = ["pubmed_search"]
        return result.output if result.success else {"success": False, "error": result.error}


class AnalysisAgent(BaseSpecialistAgent):
    """数据分析与统计智能体"""

    name = "analysis"
    description = "统计分析、差异表达分析、实验设计建议"

    async def execute(self, state: AgentState) -> dict[str, Any]:
        from .skills import get_executor

        message = state["user_message"].lower()
        executor = get_executor()
        results = {}

        if "实验设计" in message or "设计方案" in message or "design" in message:
            r = await executor.execute(
                "experimental_design", objective=state["user_message"], data_type="rna_seq"
            )
            results["experimental_design"] = r.output
            self.skills_used = ["experimental_design"]
        elif "相关" in message or "correlation" in message:
            results["correlation"] = {
                "success": False,
                "error": "相关性分析需要提供数据 (x/y)，请通过技能接口执行",
            }
            self.skills_used = ["correlation_analysis"]
        else:
            results["analysis"] = {
                "success": True,
                "message": "数据分析建议: 请提供具体数据文件或使用 /api/v1/skills/ 接口执行统计技能",
            }
        return results


class DataAgent(BaseSpecialistAgent):
    """NCBI数据获取智能体"""

    name = "data"
    description = "从NCBI获取SRA/GenBank/Gene数据"

    async def execute(self, state: AgentState) -> dict[str, Any]:
        from .skills import get_executor

        message = state["user_message"]
        executor = get_executor()
        results = {}

        if "sra" in message.lower() or "测序数据" in message or "rna-seq" in message.lower():
            r = await executor.execute("sra_search", query=message, max_results=5)
            results["sra_search"] = r.output
            self.skills_used = ["sra_search"]
        elif "genbank" in message.lower() or "序列" in message:
            import re

            accession = re.search(r"[A-Z]{2,}_?\d+(\.\d+)?", message)
            if accession:
                r = await executor.execute("genbank_fetch", accession=accession.group(0))
                results["genbank_fetch"] = r.output
                self.skills_used = ["genbank_fetch"]
            else:
                results["genbank_fetch"] = {"success": False, "error": "未提取到Accession号"}
        elif "gene" in message.lower() or "基因" in message:
            r = await executor.execute("gene_search", gene_name=message)
            results["gene_search"] = r.output
            self.skills_used = ["gene_search"]
        else:
            results["data"] = {
                "success": False,
                "error": "未识别数据库类型，支持: sra/genbank/gene",
            }
        return results


class VisualizationAgent(BaseSpecialistAgent):
    """可视化与结构渲染智能体"""

    name = "visualization"
    description = "数据可视化、蛋白质结构渲染"

    async def execute(self, state: AgentState) -> dict[str, Any]:
        from .skills import get_executor

        message = state["user_message"].lower()
        executor = get_executor()
        results = {}

        if "pdb" in message or "结构" in message or "pymol" in message or "chimerax" in message:
            r = await executor.execute("docking_status")
            results["structure_tools"] = r.output
            self.skills_used = ["docking_status"]
        elif "火山图" in message or "volcano" in message:
            results["visualization"] = {
                "success": True,
                "message": "火山图需要差异表达数据 (log2fc/pvalues)，请通过技能接口提供",
            }
            self.skills_used = ["volcano_plot"]
        else:
            results["visualization"] = {
                "success": True,
                "message": "支持的可视化: 火山图(volcano_plot)、热图(heatmap)、蛋白质结构渲染(pymol/chimerax)",
            }
        return results


class CoordinatorAgent:
    """协调智能体 - 基于LangGraph编排"""

    ROUTING_KEYWORDS: dict[str, list[str]] = {
        "data": ["sra", "genbank", "gene", "accession", "测序数据", "序列", "ncbi"],
        "literature": ["pubmed", "文献", "paper", "文章", "综述", "检索"],
        "visualization": [
            "pymol",
            "chimerax",
            "火山图",
            "heatmap",
            "docking",
            "对接",
            "结构渲染",
            "可视化",
            "绘图",
            "渲染",
        ],
        "analysis": ["分析", "统计", "实验设计", "差异表达", "correlation", "design", "方案"],
    }

    def __init__(self, db=None, use_llm: bool = True, user_id: int | None = None):
        self.db = db
        self.use_llm = use_llm
        self.user_id = user_id
        self.specialists: dict[str, BaseSpecialistAgent] = {
            "literature": LiteratureAgent(db),
            "analysis": AnalysisAgent(db),
            "data": DataAgent(db),
            "visualization": VisualizationAgent(db),
        }
        self.graph = self._build_graph()
        logger.info("多智能体系统初始化完成")

    def route(self, state: AgentState) -> str:
        """路由决策: 按关键词匹配"""
        message = state.get("user_message", "").lower()

        for agent_name, keywords in self.ROUTING_KEYWORDS.items():
            for kw in keywords:
                if kw in message:
                    return agent_name

        return "analysis"

    def _build_graph(self):
        """构建 LangGraph 状态图"""
        builder = StateGraph(AgentState)

        for name, agent in self.specialists.items():
            builder.add_node(name, agent.run)

        builder.add_node("synthesize", self.synthesize)

        builder.set_conditional_entry_point(
            self.route,
            {
                "literature": "literature",
                "analysis": "analysis",
                "data": "data",
                "visualization": "visualization",
            },
        )

        for name in self.specialists:
            builder.add_edge(name, "synthesize")

        builder.add_edge("synthesize", END)

        return builder.compile()

    async def synthesize(self, state: AgentState) -> dict[str, Any]:
        """汇总各智能体结果，生成最终回复"""
        results = state.get("results", {})
        user_message = state.get("user_message", "")

        success_parts = []
        for agent_name, result in results.items():
            if isinstance(result, dict) and result.get("success"):
                success_parts.append(f"[{agent_name}]")
                for key, value in result.items():
                    if key not in ("success", "error") and value:
                        summary = json.dumps(value, ensure_ascii=False)[:800]
                        success_parts.append(f"  {key}: {summary}")

        errors = []
        for agent_name, result in results.items():
            if isinstance(result, dict) and result.get("success") is False:
                errors.append(f"{agent_name}: {result.get('error', '未知错误')}")

        if self.use_llm:
            try:
                from ..llm import ChatEngine

                engine = ChatEngine(db=self.db, user_id=self.user_id)
                context = "\n".join(success_parts) if success_parts else ""
                prompt = (
                    f"用户请求: {user_message}\n\n"
                    f"智能体执行结果:\n{context or '无成功结果'}\n\n"
                    + ("错误信息: " + "; ".join(errors) + "\n" if errors else "")
                    + "请基于结果给出专业、简洁的回复。"
                )
                llm_result = await engine.chat(prompt)
                return {
                    "final_response": llm_result["response"],
                    "suggestions": [
                        {
                            "type": "follow_up",
                            "text": "需要更详细的分析结果吗？",
                            "action": "detail",
                        },
                    ],
                }
            except Exception:
                pass

        if success_parts:
            response = f"任务完成。{' '.join(success_parts)}"
        elif errors:
            response = "任务执行遇到问题: " + "; ".join(errors)
        else:
            response = "未能完成请求，请尝试更具体的描述。"

        return {
            "final_response": response,
            "suggestions": [
                {"type": "follow_up", "text": "需要更详细的分析结果吗？", "action": "detail"},
            ],
        }

    async def run(self, user_message: str) -> dict[str, Any]:
        """执行多智能体协作"""
        logger.info(f"多智能体任务: {user_message[:100]}")
        try:
            result = await self.graph.ainvoke(
                {
                    "user_message": user_message,
                    "intent": "",
                    "tools_used": [],
                    "skills_used": [],
                    "results": {},
                    "final_response": "",
                    "suggestions": [],
                    "error": None,
                }
            )
            return {
                "success": True,
                "response": result.get("final_response", ""),
                "skills_used": result.get("skills_used", []),
                "results": result.get("results", {}),
                "suggestions": result.get("suggestions", []),
                "agents_used": list(result.get("results", {}).keys()),
            }
        except Exception as e:
            logger.exception("多智能体执行失败")
            return {
                "success": False,
                "response": f"多智能体执行失败: {e}",
                "error": str(e),
                "results": {},
                "skills_used": [],
                "suggestions": [],
            }


__all__ = [
    "CoordinatorAgent",
    "BaseSpecialistAgent",
    "LiteratureAgent",
    "AnalysisAgent",
    "DataAgent",
    "VisualizationAgent",
]
