"""
科研智能体系统 - 项目结构说明

├── src/
│   └── research_agent/
│       ├── __init__.py          # 包入口
│       ├── main.py              # 应用入口
│       ├── cli.py               # 命令行接口
│       ├── core/                # 核心模块
│       │   ├── __init__.py
│       │   ├── app.py           # FastAPI应用配置
│       │   ├── db.py            # 数据库配置
│       │   ├── models/
│       │   │   ├── __init__.py
│       │   │   ├── db.py        # SQLAlchemy模型
│       │   │   └── schemas.py   # Pydantic Schema
│       │   └── api/
│       │       ├── __init__.py
│       │       ├── agents.py    # 智能体API
│       │       ├── plugins.py   # 插件API
│       │       ├── ncbi.py      # NCBI API
│       │       ├── workflows.py # 工作流API
│       │       └── recommendations.py # 推荐API
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── agent.py         # Agent框架
│       │   └── skills/
│       │       ├── __init__.py
│       │       └── base.py      # 技能基类
│       ├── plugins/
│       │   ├── __init__.py
│       │   └── manager.py       # 插件管理器
│       ├── ncbi_skills/
│       │   ├── __init__.py
│       │   └── adapter.py       # NCBI适配器
│       ├── workflows/
│       │   ├── __init__.py
│       │   └── engine.py        # 工作流引擎
│       └── recommendations/
│           ├── __init__.py
│           └── engine.py        # 推荐引擎
├── frontend/                    # Vue前端
│   ├── src/
│   │   ├── main.js
│   │   ├── App.vue
│   │   ├── style.css
│   │   └── views/
│   │       ├── Dashboard.vue
│   │       ├── Chat.vue
│   │       ├── Plugins.vue
│   │       ├── Skills.vue
│   │       ├── Workflows.vue
│   │       └── NCBI.vue
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── tests/                       # 测试
│   ├── __init__.py
│   ├── test_api.py
│   └── test_ncbi.py
├── pyproject.toml               # Python依赖配置
├── .env.example                 # 环境变量模板
├── .gitignore
├── README.md
├── task_plan.md
├── findings.md
└── progress.md
"""
