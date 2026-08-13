# 多智能体系统文档 (LangGraph)

## 1. 架构

```
用户消息
   │
   ▼
CoordinatorAgent (LangGraph StateGraph)
   │  条件路由 (route)
   ├──► LiteratureAgent    文献检索/分析
   ├──► AnalysisAgent      统计/实验设计
   ├──► DataAgent          NCBI数据获取
   └──► VisualizationAgent 可视化/结构渲染
          │
          ▼
   synthesize (结果汇总, LLM或规则)
          │
          ▼
   最终回复 + 建议
```

## 2. 路由规则

按关键词匹配，专有名词优先：
| 智能体 | 触发关键词 |
|--------|-----------|
| data | sra, genbank, gene, accession, 测序数据, 序列, ncbi |
| literature | pubmed, 文献, paper, 文章, 综述, 检索 |
| visualization | pymol, chimerax, 火山图, docking, 对接, 渲染 |
| analysis | 分析, 统计, 实验设计, 差异表达, 方案 |

默认兜底: analysis

## 3. LangGraph 实现

```python
builder = StateGraph(AgentState)
builder.add_node("literature", LiteratureAgent().run)
builder.add_node("analysis", AnalysisAgent().run)
builder.add_node("data", DataAgent().run)
builder.add_node("visualization", VisualizationAgent().run)
builder.add_node("synthesize", coordinator.synthesize)

builder.set_conditional_entry_point(route, {...})
for name in specialists:
    builder.add_edge(name, "synthesize")
builder.add_edge("synthesize", END)
graph = builder.compile()
```

## 4. 状态定义

```python
class AgentState(TypedDict):
    user_message: str
    intent: str
    tools_used: List[str]
    skills_used: List[str]
    results: Dict[str, Any]      # {agent_name: result}
    final_response: str
    suggestions: List[Dict]
    error: Optional[str]
```

## 5. 智能体扩展

新增智能体:
```python
class MyAgent(BaseSpecialistAgent):
    name = "my_agent"
    description = "..."
    async def execute(self, state):
        return {"success": True, "..."}

# 注册
coordinator.specialists["my_agent"] = MyAgent(db)
# 添加路由关键词
CoordinatorAgent.ROUTING_KEYWORDS["my_agent"] = ["关键词"]
```

## 6. API 接口

```bash
# 多智能体对话
POST /api/v1/agents/multi-agent
{"content": "搜索关于CRISPR的文献"}

# 系统状态
GET /api/v1/agents/multi-agent/status
```

## 7. 汇总策略
- 配置 `use_llm=True` 时优先用 LLM 汇总智能体结果
- LLM 不可用时回退规则汇总（成功结果拼接 / 错误列举）
