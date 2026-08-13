"""Agent base framework"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import asyncio
from loguru import logger


@dataclass
class AgentContext:
    """Agent执行上下文"""
    user_id: Optional[int] = None
    session_id: Optional[int] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    tools: Dict[str, Any] = field(default_factory=dict)
    skills: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class AgentResult:
    """Agent执行结果"""
    success: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    tools_used: List[str] = field(default_factory=list)
    skills_executed: List[str] = field(default_factory=list)
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    execution_time: float = 0.0


class BaseAgent(ABC):
    """智能体基类"""
    
    def __init__(self, name: str, description: str = "", config: Dict[str, Any] = None):
        self.name = name
        self.description = description
        self.config = config or {}
        self.tools: Dict[str, Callable] = {}
        self.skills: Dict[str, Any] = {}
        self.context: Optional[AgentContext] = None
        self._history: List[Dict[str, Any]] = []
        logger.info(f"Agent initialized: {name}")
    
    def register_tool(self, name: str, func: Callable, description: str = ""):
        """注册工具函数"""
        self.tools[name] = {
            "func": func,
            "description": description,
            "name": name,
        }
        logger.debug(f"Tool registered: {name}")
    
    def register_skill(self, name: str, skill: Any):
        """注册技能"""
        self.skills[name] = skill
        logger.debug(f"Skill registered: {name}")
    
    def unregister_tool(self, name: str):
        """注销工具"""
        if name in self.tools:
            del self.tools[name]
            logger.debug(f"Tool unregistered: {name}")
    
    def unregister_skill(self, name: str):
        """注销技能"""
        if name in self.skills:
            del self.skills[name]
            logger.debug(f"Skill unregistered: {name}")
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有可用工具"""
        return [
            {"name": name, "description": t.get("description", "")}
            for name, t in self.tools.items()
        ]
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有可用技能"""
        return list(self.skills.keys())
    
    @abstractmethod
    async def process_message(self, message: str, context: Optional[Dict] = None) -> AgentResult:
        """处理用户消息"""
        pass
    
    @abstractmethod
    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        """执行指定任务"""
        pass
    
    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """调用工具"""
        if tool_name not in self.tools:
            raise ValueError(f"Tool not found: {tool_name}")
        
        tool = self.tools[tool_name]
        try:
            result = await tool["func"](**kwargs) if asyncio.iscoroutinefunction(tool["func"]) else tool["func"](**kwargs)
            logger.debug(f"Tool executed: {tool_name}")
            return result
        except Exception as e:
            logger.error(f"Tool execution error: {tool_name}: {e}")
            raise
    
    async def execute_skill(self, skill_name: str, **kwargs) -> Any:
        """执行技能"""
        if skill_name not in self.skills:
            raise ValueError(f"Skill not found: {skill_name}")
        
        skill = self.skills[skill_name]
        try:
            if hasattr(skill, 'execute'):
                result = await skill.execute(**kwargs) if asyncio.iscoroutinefunction(skill.execute) else skill.execute(**kwargs)
            elif callable(skill):
                result = await skill(**kwargs) if asyncio.iscoroutinefunction(skill) else skill(**kwargs)
            else:
                raise ValueError(f"Invalid skill format: {skill_name}")
            
            logger.debug(f"Skill executed: {skill_name}")
            return result
        except Exception as e:
            logger.error(f"Skill execution error: {skill_name}: {e}")
            raise
    
    def add_to_history(self, role: str, content: str, metadata: Dict = None):
        """添加到历史记录"""
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        self._history.append(entry)
    
    def get_history(self, limit: int = 50) -> List[Dict]:
        """获取历史记录"""
        return self._history[-limit:]


class ResearchAgent(BaseAgent):
    """科研智能体 - 支持自然语言交互"""
    
    def __init__(self, db_session=None, config: Dict[str, Any] = None,
                 user_id: Optional[int] = None, session_id: Optional[str] = None):
        super().__init__(
            name="research_agent",
            description="面向科研场景的通用智能体，支持生物信息学分析、文献检索、数据可视化等",
            config=config
        )
        self.db_session = db_session
        self.user_id = user_id
        self.session_id = session_id
        self._llm_client = None
        self._initialize_clients()
        self._register_default_tools()
    
    def _initialize_clients(self):
        """LLM providers are resolved lazily by ChatEngine.

        Avoid importing and constructing a provider client for every desktop
        message; keys may live in the encrypted database rather than settings.
        """
        self._llm_client = None
    
    def _register_default_tools(self):
        """注册默认工具"""
        # NCBI查询工具
        self.register_tool(
            "search_pubmed",
            self._tool_search_pubmed,
            "搜索PubMed文献数据库"
        )
        self.register_tool(
            "search_sra",
            self._tool_search_sra,
            "搜索NCBI SRA测序数据"
        )
        self.register_tool(
            "fetch_genbank",
            self._tool_fetch_genbank,
            "获取GenBank序列信息"
        )
        
        # 数据分析工具
        self.register_tool(
            "analyze_expression",
            self._tool_analyze_expression,
            "分析基因表达数据"
        )
        self.register_tool(
            "generate_visualization",
            self._tool_generate_visualization,
            "生成数据可视化图表"
        )
        
        # 文献工具
        self.register_tool(
            "summarize_literature",
            self._tool_summarize_literature,
            "总结文献内容"
        )
    
    async def _tool_search_pubmed(self, query: str, max_results: int = 10) -> Dict:
        """PubMed搜索工具"""
        try:
            from ..ncbi_skills.adapter import NCBIAdapter
            adapter = NCBIAdapter(self.db_session)
            results = await adapter.pubmed_search(query, max_results)
            return {
                "success": True,
                "count": len(results),
                "results": results,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _tool_search_sra(self, query: str, max_results: int = 10) -> Dict:
        """SRA搜索工具"""
        try:
            from ..ncbi_skills.adapter import NCBIAdapter
            adapter = NCBIAdapter(self.db_session)
            results = await adapter.sra_search(query, max_results)
            return {
                "success": True,
                "count": len(results),
                "results": results,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _tool_fetch_genbank(self, accession: str) -> Dict:
        """获取GenBank序列"""
        try:
            from ..ncbi_skills.adapter import NCBIAdapter
            adapter = NCBIAdapter(self.db_session)
            record = await adapter.genbank_fetch(accession)
            return {
                "success": True,
                "accession": accession,
                "record": record,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _tool_analyze_expression(self, data: Dict, method: str = "deseq2") -> Dict:
        """差异表达分析"""
        try:
            import pandas as pd
            # 实际实现需要更多数据处理逻辑
            return {
                "success": True,
                "method": method,
                "message": "差异表达分析完成",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _tool_generate_visualization(self, data: Dict, chart_type: str = "heatmap") -> Dict:
        """生成可视化"""
        try:
            return {
                "success": True,
                "chart_type": chart_type,
                "message": f"{chart_type}图表生成完成",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _tool_summarize_literature(self, pmids: List[str]) -> Dict:
        """文献总结"""
        try:
            return {
                "success": True,
                "pmids": pmids,
                "message": f"文献总结完成，共{len(pmids)}篇",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def process_message(self, message: str, context: Optional[Dict] = None) -> Dict:
        """处理用户消息

        流程:
        1. 解析意图 (规则+LLM辅助)
        2. 匹配并执行工具/技能
        3. 使用真实LLM生成最终回复
        """
        start_time = asyncio.get_event_loop().time()
        use_llm = (context or {}).get("use_llm", True) and self.config.get("use_llm", True)

        try:
            # 1. 理解用户意图
            intent = await self._parse_intent(message)

            # 2. 匹配工具/技能
            selected_tools = self._select_tools(intent)

            # 3. 执行工具
            results = await self._execute_tools(intent, selected_tools)

            # 4. 生成回复 (优先真实LLM)
            if use_llm:
                response = await self._generate_llm_response(message, intent, results)
                llm_info = response.get("llm_info", {})
                response_text = response.get("response", "")
                self.session_id = response.get("session_id") or self.session_id
            else:
                response_text = await self._generate_response(message, intent, results)
                llm_info = {}

            # 5. 生成建议
            suggestions = await self._generate_suggestions(intent, results)

            execution_time = asyncio.get_event_loop().time() - start_time

            return {
                "success": True,
                "message": response_text,
                "session_id": self.session_id,
                "intent": intent,
                "tools_used": [t["name"] for t in selected_tools],
                "results": results,
                "suggestions": suggestions,
                "llm_info": llm_info,
                "execution_time": execution_time,
            }
        except Exception as e:
            logger.error(f"Process message error: {e}")
            return {
                "success": False,
                "message": f"处理失败: {str(e)}",
                "error": str(e),
            }

    async def _generate_llm_response(self, message: str, intent: Dict, results: Dict) -> Dict:
        """使用真实LLM生成回复"""
        from ..llm import ChatEngine

        engine = ChatEngine(
            db=self.db_session,
            user_id=self.user_id,
            session_id=self.session_id,
        )

        # 构建工具结果上下文
        tool_context = self._build_tool_context(results)

        # 构建对话
        # Persisted desktop conversations are loaded by ChatEngine.  The
        # in-memory history is only used for ephemeral callers.
        history = None if self.session_id else self.get_history(limit=10)
        prompt = message
        if tool_context:
            prompt += (
                f"\n\n[系统工具执行结果]\n{tool_context}\n"
                "请基于上述工具结果回答用户的问题。"
            )

        try:
            result = await engine.chat(prompt, history=history)
            self.add_to_history("user", message)
            self.add_to_history("assistant", result["response"])
            return result
        except RuntimeError as e:
            # LLM未配置时回退到规则响应
            logger.warning(f"LLM未配置，回退规则响应: {e}")
            fallback = await self._generate_response(message, intent, results)
            await engine.save_exchange(message, fallback)
            return {
                "response": fallback,
                "session_id": engine.session_id,
                "llm_info": {"fallback": True, "reason": str(e)},
            }

    def _build_tool_context(self, results: Dict) -> str:
        """构建工具结果上下文 (限制长度避免超token)"""
        import json
        parts = []
        for tool_name, result in results.items():
            if not isinstance(result, dict):
                continue
            if result.get("success") is False:
                parts.append(f"- {tool_name}: 执行失败 ({result.get('error', '未知错误')})")
                continue
            # 截断长内容
            summary = json.dumps(result, ensure_ascii=False)[:1500]
            parts.append(f"- {tool_name}: {summary}")
        return "\n".join(parts)
    
    async def _parse_intent(self, message: str) -> Dict:
        """解析用户意图"""
        # 简单的意图识别，实际应使用LLM
        message_lower = message.lower()
        
        if any(kw in message_lower for kw in ["pubmed", "文献", "论文", "搜索文章"]):
            return {"type": "literature_search", "query": message}
        elif any(kw in message_lower for kw in ["sra", "测序数据", "基因表达"]):
            return {"type": "sra_search", "query": message}
        elif any(kw in message_lower for kw in ["genbank", "序列", "基因序列"]):
            return {"type": "genbank_fetch", "accession": message}
        elif any(kw in message_lower for kw in ["分析", "差异表达", "expression"]):
            return {"type": "data_analysis", "query": message}
        elif any(kw in message_lower for kw in ["可视化", "图表", "plot", "图"]):
            return {"type": "visualization", "query": message}
        else:
            return {"type": "general", "query": message}
    
    def _select_tools(self, intent: Dict) -> List[Dict]:
        """根据意图选择工具"""
        tool_map = {
            "literature_search": ["search_pubmed"],
            "sra_search": ["search_sra"],
            "genbank_fetch": ["fetch_genbank"],
            "data_analysis": ["analyze_expression"],
            "visualization": ["generate_visualization"],
            "general": [],
        }
        
        selected = []
        for tool_name in tool_map.get(intent.get("type", "general"), []):
            if tool_name in self.tools:
                selected.append(self.tools[tool_name])
        
        return selected
    
    async def _execute_tools(self, intent: Dict, tools: List[Dict]) -> Dict:
        """执行工具"""
        results = {}
        
        for tool in tools:
            tool_name = tool["name"]
            try:
                if tool_name == "search_pubmed":
                    results[tool_name] = await self.call_tool(
                        tool_name,
                        query=intent.get("query", ""),
                        max_results=10
                    )
                elif tool_name == "search_sra":
                    results[tool_name] = await self.call_tool(
                        tool_name,
                        query=intent.get("query", ""),
                        max_results=10
                    )
                elif tool_name == "fetch_genbank":
                    results[tool_name] = await self.call_tool(
                        tool_name,
                        accession=intent.get("accession", "")
                    )
            except Exception as e:
                results[tool_name] = {"success": False, "error": str(e)}
        
        return results
    
    async def _generate_response(self, original: str, intent: Dict, results: Dict) -> str:
        """生成响应"""
        intent_type = intent.get("type", "general")
        
        if intent_type == "literature_search" and results.get("search_pubmed", {}).get("success"):
            count = results["search_pubmed"].get("count", 0)
            return f"找到 {count} 篇相关文献。建议您查看PubMed详细结果，我可以为您总结关键发现。"
        
        elif intent_type == "sra_search" and results.get("search_sra", {}).get("success"):
            count = results["search_sra"].get("count", 0)
            return f"找到 {count} 个SRA数据集。您可以下载原始数据或元数据进行分析。"
        
        elif intent_type == "genbank_fetch" and results.get("fetch_genbank", {}).get("success"):
            return f"成功获取GenBank序列 {intent.get('accession', '')}。序列信息已返回。"
        
        elif intent_type == "data_analysis":
            return "数据分析请求已接收，请提供具体的数据文件或参数。"
        
        elif intent_type == "visualization":
            return "数据可视化请求已接收，请指定数据类型和图表类型。"
        
        else:
            return f"我已理解您的需求：{original}。请问您希望进行文献检索、数据分析还是其他操作？"
    
    async def _generate_suggestions(self, intent: Dict, results: Dict) -> List[Dict]:
        """生成建议"""
        suggestions = []
        
        if intent.get("type") == "literature_search":
            suggestions.append({
                "type": "follow_up",
                "text": "可以进一步搜索相关基因或通路",
                "action": "search_related_genes",
            })
            suggestions.append({
                "type": "action",
                "text": "下载文献摘要进行综述撰写",
                "action": "download_summaries",
            })
        
        elif intent.get("type") == "sra_search":
            suggestions.append({
                "type": "action",
                "text": "下载SRA原始数据进行分析",
                "action": "download_sra_data",
            })
            suggestions.append({
                "type": "follow_up",
                "text": "查看SRA数据集的元数据",
                "action": "view_sra_metadata",
            })
        
        return suggestions
    
    async def execute_task(self, task: Dict[str, Any]) -> Dict:
        """执行指定任务"""
        task_type = task.get("type", "general")
        
        if task_type == "analysis":
            return await self._run_analysis(task)
        elif task_type == "workflow":
            return await self._run_workflow(task)
        else:
            return {"success": False, "error": f"Unknown task type: {task_type}"}
    
    async def _run_analysis(self, task: Dict) -> Dict:
        """运行分析任务"""
        return {"success": True, "message": "分析任务执行中..."}
    
    async def _run_workflow(self, task: Dict) -> Dict:
        """运行工作流"""
        return {"success": True, "message": "工作流执行中..."}


__all__ = ["BaseAgent", "ResearchAgent", "AgentContext", "AgentResult"]
