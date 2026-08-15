# Research Agent P0 开发计划（2026-08 起）

依据 `docs/full_functional_evaluation_20260814.md` 的阶段性结论与「建议的下一步（立即行动）」制定。目标：在 4–7 周内交付 P0 验收门槛（端到端「样本表 → PDF 简报」闭环、RA-Eval 冒烟通过、259+ 测试全绿），全部功能与现有架构（科研运行时、ExecutionBackend、插件生命周期、前端视图）兼容，不引入新调度语义。

## 1. 任务清单与优先级

| # | 任务 | 优先级 | 状态 | 完成定义 |
|---|------|:---:|:---:|------|
| T1 | 许可证口径澄清与仓库元数据统一 | P0 | 已完成 | pyproject.toml / README / docs 三方一致（MIT） |
| T2 | 科研运行时 → nf-core 能力步骤 `pipeline_execution` | P0 | 已完成 | 注册新能力；handler 轮询可配置；下游 data_analysis/writing 可引用其制品；264 测试全绿 |
| T3 | 研究简报自动生成（Markdown/HTML/PDF） | P0 | 已完成 | POST /research/runs/{id}/report 生成并下载；模板聚合目标/证据/统计/缺口；270 测试全绿 |
| T4 | RA-Eval v1：插件任务级冒烟评测 | P0 | 已完成 | seed 冒烟定义；执行 API；历史记录；插件 62 测试全绿 |
| T5 | 环境体检向导（前端 + 聚合后端） | P0 | 已完成 | GET /system/health-check 聚合；HealthCheck.vue 向导视图；291 测试全绿 |
| T6 | 全量测试 + 文档更新 + GitHub 推送 | P0 | 进行中 | 259+ 测试全绿；README/docs 更新；推送 main |

## 2. T2 设计（核心：pipeline_execution 能力步骤）

### 2.1 注册点（完全复用现有扩展机制）
- `src/research_agent/research/contracts.py:99` `CAPABILITIES` 新增 `pipeline_execution`：
  ```python
  CapabilitySpec(
      name="pipeline_execution",
      title="生产流程执行",
      description="运行固定版本 nf-core 流程（rnaseq/sarek）…",
      category="analysis",
      modalities=("tabular", "text"),
      risk=RiskLevel.HIGH,            # 长时运行、外部计算
      network_access=True,            # Nextflow/容器拉取
      writes_artifacts=True,
      requires_human_review=True,     # 与科研人工门一致
      timeout_seconds=3600,
      max_retries=0,
      cost_units=20,
  )
  ```
- `src/research_agent/research/services.py:683` `HANDLERS` 注册 `pipeline_execution` 处理器。
- `src/research_agent/research/planner.py:35-43` `DOMAIN_CAPABILITY` 挂接（analysis 域可被规划器选择；规划器为白名单驱动，LLM 不能绕过）。
- 预算合并：`planner.py:196-222` 的预算计算纳入新能力 cost（cost_units=20）。

### 2.2 处理器行为
- 输入取自 `step.input_data`：`pipeline_id`（默认 rnaseq）、`revision`（必须等于 PIN，沿用 `nextflow.py:212` validate_request）、`profile`（默认 docker）、`parameters`、`artifact_bindings`（样本表来自前置 `artifact_intake` 步骤的输出）。
- 授权：pipelines 路由的 admin 门（`pipelines.py:193-194`）在科研语境下转为**策略层约定**——`pipeline_execution` 仅在 `requires_human_review` 门通过且用户具备执行前置（preflight 就绪）时执行；`ToolPolicy` 网络/审批过滤天然生效（`scheduler.py:27-34`）。API 层 `POST /research/runs` 创建运行不设 admin 门，但能力步骤执行前通过 `PipelineRunManager.preflight` 诚实报告不可用（与 `preflight 诚实报不可用` 现有模式一致）。
- 执行路径：handler 内 `await` `PipelineRunManager` 的 `plan_run`（`execution/manager.py:73-127`）+ `submit`。长时运行受 `timeout_seconds=3600` 与协调器 lease 保护（`scheduler.py:72-77`），避免与生产流程页并行超卖。
- 输出回传：
  - `CapabilityResult.generated_artifacts` ← `ExecutionResult.artifacts`（counts/MultiQC/报告，SHA-256 自带），由 `runtime.py:195-199` 自动落库为 `ResearchArtifact`；
  - `evidence` ← `ExecutionResult.provenance`/task_summary（pipeline_id/revision/commit_sha/任务统计）；
  - `warnings` ← Nextflow 失败任务/资源告警；`confidence` 由任务成功率得出。
- 失败语义：执行失败 → `status="failed"`（步骤级），运行聚合 `review_required=True`，与现有研究运行时一致；`-resume` 语义保留在 pipelines 页，能力步骤内不自动重试（max_retries=0）。

### 2.3 端到端验收场景
样本表上传（`artifact_intake`）→ `pipeline_execution`（rnaseq test 黄金数据或用户小样本）→ `data_analysis` 读 count 矩阵 → `research_writing` 引用证据 → 研究简报 PDF。低门槛替代验收：黄金 `test,docker` 数据走通并生成简报。

## 3. T3 研究简报设计
- 新模块 `src/research_agent/reporting/brief.py`（纯函数，无状态）：
  - 输入：`ResearchRun`（plan/steps/evidence/result）、关联 `ResearchArtifact`、`PipelineRun`（若有）；
  - 输出：Markdown（模板聚合：目标、计划、输入哈希、步骤结果、证据表、统计摘要、MultiQC 摘要、缺口、下一步、审计信息）。
- `reporting/pdf.py`：reportlab 纯 Python 渲染（PageSimple + 表格 + 长文本换行）；`reporting` 加入 pyproject/requirements（`reportlab>=4.0`）。
- API：`POST /api/v1/research/runs/{run_id}/report?format=md|html|pdf`（登录用户，仅本人 run）→ 返回制品（复用 artifact 存储）或直接文件响应；`GET /api/v1/research/runs/{run_id}/report`。
- 前端：ResearchWorkspace.vue 运行详情增加「生成简报 PDF」按钮。
- 测试：黄金报告内容断言（目标/证据数/缺口存在）、PDF 字节头校验、非本人 403。

## 4. T4 RA-Eval v1 设计
- 新概念「冒烟用例 SmokeTest」：`{id, command(白名单), args, expect_exit, expect_stdout(子串/正则), timeout_s}` 写入 `Plugin` 模型新 JSON 字段 `smoke_tests`；seed 为 fastqc/samtools/kallisto 等提供 1–2 个断言型冒烟用例（探针升级版）。
- 执行：`plugins/smoke_runner.py` 复用 `Deployer._run_command` 的受管执行（独立前缀、超时、argv-only、输出有界）；结果写入插件安装 provenance 或新表 `PluginSmokeRun(id, plugin_id, user_id, smoke_id, status, detail, duration_ms, run_at)`。
- API：`POST /api/v1/plugins/{id}/smoke`（admin，仅 verified/enabled 状态）与 `GET /api/v1/plugins/{id}/smoke-history`。
- 前端：Plugins.vue 详情弹窗增加「运行冒烟测试」。
- 测试：冒烟成功/失败迁移、非 verified 拒绝、命令注入拒绝。

## 5. T5 环境体检向导设计
- 后端聚合：`core/api/system.py` 新增 `GET /api/v1/system/health-check`，聚合 `PlatformCapabilityProbe.probe(deep)` + Nextflow `capabilities(deep)` + `PipelineRunManager.preflight` + 磁盘空间，返回 `{checked_at, items: [{id, title, status(ok|warn|error|missing), detail, fix_hint(中文指引)}], summary}`。复用现有各探测，新增一个聚合读模型即可。
- 前端：`views/HealthCheck.vue`（向导式卡片：工具清单、WSL2、Nextflow、容器、磁盘；每项可「重新检测」、失败项给修复指引），`main.js:17-35` 注册路由 `/health`，`App.vue:98-114` 侧边栏「资源与工具」加「环境体检」。
- 测试：win32 探测结构断言（host/tools/limitations 字段），API 200 断言。

## 6. 工程质量约束
- 遵循现有约定：ruff（E/F/W/I/N/UP/B/C4，行宽 100）、mypy、无新增全局状态；类 Faker/monkeypatch 测试模式与 conftest fixtures 保持一致。
- 新增测试全部纳入 `tests/`，跑 `python -m pytest -q` 至全绿后再提交。
- 文档同步：README 功能清单、docs/p0_*.md 验收记录、RELEASE_NOTES.md。

## 7. 资源与节奏
- 单开发线（当前环境），按 T1→T2→T3→T4→T5→T6 顺序串行；T2 最大（约占总工作量 40%），分解为：契约与处理器 → planner 挂接 → 测试 → 端到端验证。
- 每任务完成即跑 `pytest -q` 防回归；T6 统一推送 GitHub（origin main，经 127.0.0.1:7890 代理）。