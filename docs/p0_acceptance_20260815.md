# P0 开发计划验收报告（T1–T6）

日期：2026-08-15  
版本：Research Agent 1.4.0（开发基线）  
结论：**P0 验收门槛达成——端到端「样本表 → PDF 简报」闭环、RA-Eval v1 冒烟评测、环境体检向导全部实现；Python 套件 291/291 通过；Vue 生产构建通过；仓库已推送 GitHub main（d751ddd、6048eab）。** 真实 `nf-core/rnaseq@3.26.0` 黄金数据执行属于外部依赖项（WSL2/Nextflow/容器），本机未具备条件，以 Fake 后端契约测试替代（见 §4）。

## 1. 任务状态

| # | 任务 | 状态 | 验收要点 |
|---|------|:---:|------|
| T1 | 许可证口径统一 | 完成 | 全仓 MIT（LICENSE 建立，pyproject/README/docs 一致） |
| T2 | 科研运行时 `pipeline_execution` 能力步骤 | 完成 | 契约注册 + planner 挂接 + 可配置轮询 handler + 制品回传 + 预检失败诚实 degraded |
| T3 | 研究简报（Markdown/HTML/PDF） | 完成 | `POST /research/runs/{id}/report` 下载；模板聚合目标/证据/统计/缺口；CJK 字体 Windows 注册 |
| T4 | RA-Eval v1 插件冒烟评测 | 完成 | 白名单冒烟定义（seed 3 工具）、受管执行、历史 API、命令注入拒绝 |
| T5 | 环境体检向导 | 完成 | `GET /system/health-check` 聚合 7 项 + 中文修复指引；HealthCheck.vue |
| T6 | 全量测试 + 文档 + 推送 | 完成 | 291/291 通过；README/RELEASE_NOTES/test_report/roadmap 更新；推送 main |

## 2. 测试基线

`python -m pytest -q`：**291 passed, 0 failed**（261.77s）。本次新增 31 个测试：

- T2：`tests/test_research_runtime.py` +4（planner 步骤键 `["intake","data","pipeline","writing","integrity"]`、无 pipeline_id 忽略、preflight 失败 → degraded、completed 导入制品、failed → degraded 低置信度）；
- T3：`tests/test_reporting.py` +6（Markdown 模板章节、HTML/PDF 字节头、CJK 字体注册、下载端点、本人归属）；
- T4：`tests/test_plugins_smoke.py` +18（spec 校验/命令注入拒绝/受管执行/历史/API 权限/版本探针回退）；
- T5：`tests/test_system_health.py` +3（平台探测结构、聚合契约、鉴权要求）。

`ruff check` 本次涉及的全部 16 个 Python 文件通过。前端 `vite build` 通过（含 HealthCheck.vue、简报下载按钮、冒烟按钮）。

## 3. 主要实现

### 3.1 T2 pipeline_execution 能力步骤

- `research/contracts.py`：`CAPABILITIES` 注册 `pipeline_execution`（risk=HIGH、network_access、writes_artifacts、requires_human_review、timeout_seconds=3600、max_retries=0、cost_units=20）。
- `research/services.py` handler：`PipelineRunManager.plan_run` + `submit`，轮询间隔 `poll_interval`（默认 5s）、总时限 `timeout_seconds`（deadline 用 `max(0, …)` 防御）；成功后 `generated_artifacts` 回传 ExecutionResult 制品清单、`evidence` 回传 pipeline_id/revision/task_summary、`confidence` 由任务成功率得出；`ExecutionResult` 失败 → `status="failed"`，运行聚合 `review_required=True`。
- `research/planner.py`：analysis 域挂接，预算纳入 cost_units。
- 测试以 `_FakePipelineManager`/`_FakePipelineBackend` + monkeypatch `get_pipeline_manager` 覆盖成功/失败/预检不可用/无 pipeline_id 全分支。

### 3.2 T3 研究简报

- 新包 `reporting/`：`brief.py`（`build_brief_markdown(run, artifacts, pipeline_runs)` 纯函数，10 节模板：目标/计划/输入哈希/步骤结果/证据表/统计摘要/MultiQC 摘要/缺口/下一步/审计信息）、`pdf.py`（reportlab 渲染，`_CJK_CANDIDATES` 含 MSYH/SimSun/SimHei/DengXian/Noto，Windows 注册 `msyh.ttc` 实测成功；极简 md → flowables/HTML 转换器）。
- 数据链路：`PipelineRun.run_id` 列（FK research_runs.id）+ services 创建时写入 + `_light_migrations` 加列并回填 `provenance.research_run_id`。
- API：`POST /api/v1/research/runs/{run_id}/report`（Body `ReportFormat{format}`，仅本人 run）。
- 前端：ResearchWorkspace.vue completed 状态「生成简报 PDF」按钮，blob 下载。

### 3.3 T4 RA-Eval v1 冒烟评测

- `plugins/smoke_runner.py`：`validate_smoke_spec`（命令白名单 `^[A-Za-z0-9][A-Za-z0-9._-]*$`，拒绝 `&|;<>$`(){}` 与空参数，expect_exit 0–255、timeout_s 1–300）；`SmokeRunner.run` 复用 `Deployer._run_command` 受管执行（conda run -p / Scripts|bin argv 解析）；无 `smoke_tests` 回退 `install_method.probe`；结果写 `PluginSmokeRun`，`history()` 可查。
- `Plugin.smoke_tests` JSON 字段 + `PluginSmokeRun` 表；seed 为 fastqc/samtools/kallisto 提供 version 冒烟用例。
- API：`POST /plugins/{id}/smoke`（admin 门、ValueError→409）、`GET /plugins/{id}/smoke-history`。
- 前端：Plugins.vue「🔥 运行冒烟评测」（is_verified && isAdmin）。

### 3.4 T5 环境体检向导

- `core/api/system.py`：`GET /api/v1/system/health-check?deep=`。浅探针：`PlatformCapabilityProbe().probe(deep=False)` + Nextflow `capabilities(deep=False)` + 磁盘；深探针：`capabilities(deep=True)`（JVM 版本/流程兼容探测）+ 首个流程的 `preflight(rnaseq, docker, network_allowed=True)`。返回 `{checked_at, deep, overall, summary, items:[{id,title,status,detail,fix_hint}]}`，7 项：host/conda/wsl2/containers/nextflow/pipelines/disk，fix_hint 为中文修复指引；任何单项探测异常不影响整体（try/except 包裹）。
- 前端：HealthCheck.vue（卡片式状态视图 + 重新检测/深度检测按钮），路由 `/health`，侧边栏「资源与工具 → 环境体检」。

## 4. 边界与未验收项

- **真实黄金数据执行**：`nf-core/rnaseq@3.26.0` `test,docker` 的端到端运行需要 WSL2 发行版 + 兼容 Nextflow + Docker Desktop（外部依赖），本机未具备；T2 以 Fake 后端契约测试替代，handler 与制品/证据回传路径已测。真实执行仍可走既有「生产流程」页（2026-08-14 曾完成 234-task 全零失败运行）。
- 冒烟评测仅 seed 三个工具的 `--version` 用例；扩展断言型用例（如 `expect_stdout` 正则、真实样本输入）留待 RA-Eval v2。
- 存量 lint：全仓历史遗留 1169 个 ruff 错误（import 排序等），与本次改动无关，未纳入本 P0 范围。

## 5. 后续建议

1. 接入真实 WSL2/Nextflow 后执行 P0 黄金数据端到端验收并补录本文档。
2. 全仓 ruff 清理（1081 项可自动修复，需一次性提交）。
3. git 全局 `http.proxy` 仍指向已失效的 127.0.0.1:7890，后续推送需 `-c http.proxy=""`（或清理全局配置）。