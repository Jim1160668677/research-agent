# 生物信息学第三方集成评估与路线图

评估日期：2026-08-13

## P4 模型与 Co-Scientist 补充评估

本轮新增评估 DeepSeek-V3 官方仓库、Agnes CLI、Tenacity、OpenAI Python SDK、LangGraph、Nextflow 和 LiteLLM。结论是：直接集成 Agnes CLI 与 Tenacity；复用 OpenAI SDK 对接 DeepSeek 官方兼容协议；保留 LangGraph 和 Nextflow 的既有边界；LiteLLM 适合未来机构网关，但不嵌入当前本地桌面包，以免重复网关职责并扩大依赖与供应链面。兼容范围、接入步骤、风险及当前活跃度证据见 [P4 验收报告](p4_co_scientist_model_sync_acceptance.md#7-github-开源组件评估与集成决策)。

## 1. 结论先行

当前系统已经具备可运行的桌面壳、科研任务运行时、技能注册表、插件目录、NCBI 适配器、推荐器和工作流引擎，但不应把“目录中存在一个工具”解释为“该工具已在本机可信执行”。第三方集成应被拆成四层：发现、解析、部署、执行。每层都必须有独立状态、权限、失败语义和审计记录。

推荐决策：

1. **优先接入元数据，不直接执行陌生代码**：以 Bioconda/BioContainers/Galaxy Tool Shed 作为发现源，先提供只读目录同步、版本和依赖预览。
2. **生产生物流程采用外部执行后端**：优先做 Nextflow/nf-core 适配器；Snakemake 作为第二适配器；CWL 用于交换和校验，不在第一阶段同时维护三套调度语义。
3. **Windows 桌面不直接承诺运行全部 Linux 生信工具**：本机纯 Python/Windows 工具使用独立前缀；Linux-only 工具进入 WSL2、容器、HPC 或远程 Galaxy/Nextflow 执行面。
4. **文献与可重复研究采用成熟标准**：Zotero/Pyzotero 做个人文献库连接，RO-Crate 做结果与溯源导出。
5. **复杂权限成熟后再引入策略引擎**：当前桌面两角色模型继续使用内建 RBAC；只有出现项目/课题组/数据集多租户授权时才引入 PyCasbin，避免提前增加双重授权源。

## 2. 十项核心模块核对

状态定义：`已验证` 表示当前代码与自动化测试闭环；`部分满足` 表示主路径存在但仍缺生产级能力或量化验收；`边界明确` 表示系统会诚实拒绝尚未支持的行为。

| # | 模块 | 当前状态 | 已验证能力 | 仍需补齐的生产能力 |
|---:|---|---|---|---|
| 1 | 统一插件市场 | 已验证核心路径 | 目录、搜索、评分、版本、依赖；Manifest v1；Bioconda 指定包只读同步/缓存；选择/部署/验证/启用分态；隔离部署与安全卸载 | Tool Shed/BioContainers 同步；SBOM/漏洞扫描；签名发布与自动更新 |
| 2 | 自动化 Skill 框架 | 已验证 | 注册、发现、参数契约、执行日志、组合、超时、科研运行时能力策略；插件侧稳定 Manifest v1 | 扩展 SDK、Skill/Workflow Manifest 映射、兼容性测试套件和签名包 |
| 3 | NCBI 适配层 | 已验证 | PubMed、SRA、GenBank、BLAST、限流、重试、批量获取、结构化解析、FASTA/GenBank 转换 | 大规模断点下载、磁盘配额、校验和、持久缓存与可配置代理 |
| 4 | 科研辅助技能集 | 已验证核心路径 | 文献证据、实验设计契约、表格分析/可视化、写作脚手架、规范与伦理预检 | RoB 2/ROBINS-I/GRADE 双人复核；扫描 PDF OCR；正式样本量计算器；商业查重连接器 |
| 5 | 自然语言交互 | 部分满足 | 会话持久化、多模型适配、任务规划、能力选择、结果解释和明确失败 | 领域基准集；意图识别准确率、延迟和拒答率持续评测；离线模型回退 |
| 6 | 智能推荐 | 已验证基础版 | 只推荐真实技能/插件/可见工作流；按用户、领域、上下文和反馈排序 | 冷启动实验、NDCG/接受率指标、时间衰减、可解释权重管理和 A/B 评估 |
| 7 | 工作流引擎 | 已验证本地 DAG | 图定义、保存/复用、严格节点校验、类型化引用、并发波次、重试/超时、跨实例取消、运行历史 | Nextflow/Snakemake 外部后端；检查点恢复；HPC 队列；版本化导入/导出 |
| 8 | 可扩展性 | 部分满足 | 模块边界、技能注册、插件目录、Manifest JSON Schema/验证 API、来源适配器、工作流节点契约 | 公共扩展 SDK、兼容性矩阵、迁移策略、开发者沙箱 |
| 9 | 安全与隐私 | 已验证桌面核心路径 | 回环绑定、JWT、用户隔离、密钥加密、AES-256-GCM 原始材料静态加密、双重完整性校验、受控旧数据迁移、读取审计、HMAC 哈希链验证、管理员安全页、部署 RBAC、argv 执行、路径边界、安全头 | 项目级 ABAC、保留/销毁策略、机构 SSO、备份密钥轮换与恢复演练、外部 WORM/签名链头锚定、独立安全与合规评审 |
| 10 | 用户界面 | 已验证核心桌面路径 | 插件生命周期操作、Manifest/来源展示、平台能力与限制面板、管理员 Bioconda 同步、科研工作台、工作流管理、结果面板、认证和桌面 WebView | 真正的节点拖拽编辑器、大图虚拟化、无障碍审计、长任务通知和数据血缘浏览 |

因此仍不能把 10 项全部标为“生产完备”。第 1 项的可信目录与本地隔离部署核心路径现已闭环，但 Tool Shed、BioContainers、SBOM 和签名供应链仍待完成；5、6、8、9、10 仍有明确的机构级验收项。第 9 项的桌面核心路径已经补齐静态加密、验证下载、明文迁移和哈希链防篡改检测，但本地哈希链不能证明末尾未被整体截断，也不等同于临床/人类基因组数据合规认证。

## 3. 成熟项目兼容性与采用建议

活跃度判断以官方仓库/官方发布页在评估日可见的近期提交、发布、问题和社区活动为依据，不以星标数量作为唯一判断标准。

| 项目 | 对应模块 | 活跃度/社区 | 与当前栈兼容性 | 建议 |
|---|---|---|---|---|
| [Galaxy](https://github.com/galaxyproject/galaxy) + [Tool Shed](https://toolshed.g2.bx.psu.edu/) | 1、7、10 | 高；Galaxy 26.0 发布线持续维护，Tool Shed 有持续新增工具 | Galaxy 是大型服务平台，不适合嵌入单机 EXE；REST API 与工具 XML 元数据可适配 | **适配，不嵌入**：同步工具元数据并提供远程 Galaxy 连接器；不要复制其服务端 |
| [Bioconda recipes](https://github.com/bioconda/bioconda-recipes) | 1、8 | 高；大型持续维护配方库和夜间构建 | 与 conda/micromamba 前缀天然兼容；官方主要面向 Linux/macOS，不覆盖普通 Windows 原生工具链 | **优先采用元数据**：解析 repodata/配方；Windows 上把 Linux 包路由到 WSL2/远程执行 |
| [BioContainers](https://github.com/BioContainers) | 1、7、9 | 高；与 Bioconda/Galaxy 生态联动 | 需要 Docker/Podman/Apptainer；不应把容器守护进程打进桌面 EXE | **执行后端采用**：只接受固定 digest、允许列表和漏洞扫描通过的镜像 |
| [Nextflow](https://github.com/nextflow-io/nextflow) + [nf-core](https://nf-co.re/) | 2、7、8 | 很高；Nextflow 有频繁稳定/edge 发布，nf-core 有成熟评审流水线生态 | Java 外部进程，适合本地 Linux、WSL2、HPC、云和 Kubernetes；可通过 trace/report 输出接入 | **第一生产工作流适配器**：先支持固定 revision 的 nf-core 流程，不把 DSL 解释器写进主进程 |
| [Snakemake](https://github.com/snakemake/snakemake) | 2、7、8 | 高；长期活跃并已转向执行/存储插件架构 | Python 生态友好，但依赖和 executor 插件应放在独立环境；Windows 生信命令仍常依赖 WSL/Linux | **第二适配器**：面向现有 Snakefile 用户；不与 Nextflow 同时承担默认语义 |
| [CWL/cwltool](https://github.com/common-workflow-language/cwltool) | 2、7、8 | 稳定标准社区 | Python 可接入；标准交换价值高，但不同执行器扩展和 GPU/HPC 行为可能不一致 | **用于导入/导出与校验**：第一阶段不作为默认调度器 |
| [Biopython](https://github.com/biopython/biopython) | 3、4 | 高；官方仓库近期持续更新，跨平台 wheel 成熟 | 已在 Python 后端使用，最符合当前 GenBank/序列解析需求 | **继续内嵌**：固定兼容版本并保留 NCBI HTTP 层自己的限流/重试策略 |
| [Zotero](https://github.com/zotero/zotero) + [Pyzotero](https://github.com/urschrei/pyzotero) | 4、5、6 | 高；Zotero 社区大，Pyzotero 2026 年仍有发布并提供本地/API/MCP 路径 | Pyzotero 是同步客户端；需在线程池中运行并加分页/限流；API key 必须进入现有密钥仓 | **优先文献连接器**：先只读同步，去重键采用 DOI→PMID→标题 |
| [RO-Crate 1.2](https://github.com/ResearchObject/ro-crate) | 4、7、8、9 | 标准活跃；1.2 为 Recommendation | 核心是 JSON-LD，可先直接生成而不引入大型运行时 | **优先导出标准**：把输入哈希、工具版本、参数、环境、证据和产物装入 crate |
| [Plotly.py/Plotly.js](https://github.com/plotly/plotly.py) | 4、10 | 很高；科学图形和浏览器生态成熟 | Vue 前端优先直接使用 Plotly.js，避免把完整 Plotly Python 科学栈冻结进 EXE | **采用前端懒加载**：支持交互图与静态导出，超大数据先下采样 |
| [Cytoscape.js](https://github.com/cytoscape/cytoscape.js) | 4、10 | 高；生物网络领域成熟 | 纯前端库，适合 Vue 包装；需限制节点/边数量 | **用于生物网络**：PPI、调控网络、通路图，不替代工作流编辑器 |
| [Vue Flow](https://github.com/bcakmakoglu/vue-flow) | 7、10 | 高；Vue 3/Vite 原生，发布频繁 | 与当前 Vue 3/Vite 技术栈直接兼容 | **用于图形工作流编辑器**：后端仍是定义和校验唯一事实源 |
| [PyCasbin](https://github.com/casbin/pycasbin) | 8、9 | 高；支持 async、RBAC、ABAC、多租户域 | 与 Python/FastAPI 兼容，但会增加第二套策略存储和迁移成本 | **条件采用**：项目级共享/多租户出现后再接入；当前两角色桌面版暂缓 |

## 4. 目标集成架构

```text
Vue Desktop
  ├─ Plugin/Skill/Workflow UI
  ├─ Vue Flow editor
  ├─ Plotly/Cytoscape result views
  └─ approval + provenance views
          │ authenticated typed API
          ▼
Research Agent control plane
  ├─ Capability Registry + Manifest v1
  ├─ Policy/RBAC + audit events
  ├─ Workflow compiler + local DAG runtime
  ├─ Catalog adapters: curated / Bioconda / Tool Shed / BioContainers
  ├─ Literature adapters: NCBI / Zotero
  └─ Provenance exporter: RO-Crate
          │ versioned ExecutionBackend contract
          ▼
Execution plane
  ├─ isolated Python venv / conda prefix
  ├─ WSL2 or digest-pinned container
  ├─ Nextflow/nf-core or Snakemake
  └─ remote Galaxy / HPC scheduler
```

关键约束：控制面只规划、授权、调度和记录；陌生生物工具代码不进入 FastAPI/桌面主进程。所有执行后端必须返回统一的 `run_id/status/exit_code/stdout_tail/stderr_tail/artifacts/provenance`，并实现超时和取消。

## 5. 分阶段集成步骤

### 阶段 A：扩展契约和可信目录

当前进度（2026-08-12）：步骤 1–3 已实现；步骤 5 已实现管理员准入和追加式同步记录，但差异审批仍待补齐；步骤 4 尚未开始。

1. 定义 `CapabilityManifest v1` JSON Schema：身份、语义版本、输入/输出、平台、资源、网络、许可证、风险、部署方法和探针。
2. 把插件状态拆成 `discovered → selected → deployed → verified → enabled`，任何失败不可跳级。
3. 实现 Bioconda repodata 只读同步；保存源 URL、同步时间、版本、构建号、子目录和许可证元数据。
4. 实现 Tool Shed 只读搜索适配；Galaxy XML wrapper 先转换为候选 Manifest，不自动执行。
5. 为每次目录同步记录摘要、差异和管理员审批；禁用任意 Git URL 自动安装。

验收：重复同步幂等；恶意名称/参数被拒绝；非管理员不能发布或真实部署；断网使用带时间戳缓存且明确标识过期。

### 阶段 B：Linux/容器执行后端

1. 实现 `ExecutionBackend` 接口和本地隔离前缀后端；延用当前 argv-only、超时、进程树终止和回滚机制。
2. 新增 WSL2/远程 Linux 能力检测，不自动开启 Windows 功能；由管理员显式配置发行版、工作目录和配额。
3. 新增容器后端：镜像必须固定 digest，根文件系统只读，非 root，限制 CPU/内存/PID，按需挂载输入和只写输出目录，默认断网。
4. 生成并保存命令参数、镜像 digest、工具版本、输入/输出 SHA-256、环境和开始/结束时间。

验收：容器逃逸/越界路径测试；取消后无遗留子进程；失败不污染主环境；同一输入/版本可复跑。

### 阶段 C：Nextflow/nf-core 主适配器

1. 只允许仓库允许列表、固定 tag/commit 和参数 Schema；第一批选择 fastqc/rnaseq/sarek 等有限流程做黄金样例。
2. 在工作区生成参数文件和 profile；Nextflow 作为外部进程运行，采集 trace、timeline、report 和 DAG。
3. 将 Nextflow task 映射为只读子步骤；主运行状态由后端进程与 trace 共同决定，不能依据日志关键字猜测成功。
4. 实现 `terminate → grace period → kill tree`，并将可恢复工作目录与 cleanup 策略区分。
5. 再实现 Snakemake adapter；CWL 先提供 validate/import/export。

验收：固定 nf-core 小数据集通过；失败 task、重试、缓存 resume、取消、磁盘不足和无网络测试通过。

### 阶段 D：文献、溯源和界面

1. Pyzotero 只读连接器接入现有加密密钥仓；本地 Zotero API 优先，云 API 明确网络提示。
2. 规范化 Zotero/NCBI 记录并按 DOI→PMID→标题去重，保留来源和原始键，不覆盖人工笔记。
3. 每次科研运行导出 RO-Crate；包含声明、输入、工具、参数、环境、证据、产物、作者/机构和许可证。
4. Vue Flow 只编辑本地草稿；保存前后端再次校验。Plotly/Cytoscape 采用路由级懒加载、数据抽样和节点上限。

验收：往返导入不丢 ID；离线不泄露文献内容；RO-Crate validator 通过；10k 节点压力测试不冻结窗口。

### 阶段 E：安全和机构化部署

1. 已实现安装级派生密钥、AES-256-GCM 原始科研数据静态加密和旧材料显式迁移；下一步完成备份密钥轮换、恢复演练，并为 PHI/人类基因组数据增加分类和导出审批。
2. 已实现上传、读取、迁移及流水线控制的追加式 HMAC 哈希链和管理员验证页；下一步把链头定期锚定到外部签名/WORM 存储，并扩展到所有敏感管理动作。
3. 出现项目/课题组共享后引入 PyCasbin 的 tenant-domain RBAC/ABAC；策略迁移前做 shadow decision 对比。
4. 发布物在干净、锁定依赖的 CI 环境构建，生成 SBOM、漏洞报告、签名和可验证更新清单。

## 6. 主要风险

| 风险 | 概率/影响 | 控制措施 |
|---|---|---|
| Windows 与 Linux 生信工具不兼容 | 高/高 | 明确平台矩阵；WSL2/容器/远程执行；不伪装为原生支持 |
| 第三方包供应链投毒 | 中/严重 | 允许列表、固定版本和 digest、SBOM、签名/校验和、漏洞扫描、人工发布门 |
| 工作流等同任意代码执行 | 高/严重 | 控制面与执行面隔离、非 root、只读根、最小挂载、默认断网、配额和审批 |
| 敏感基因组/临床数据外泄 | 中/严重 | 数据分类、静态/传输加密、出口允许列表、脱敏日志、审计和保留策略 |
| 多引擎语义漂移 | 高/高 | 一个默认生产引擎；版本化适配器；黄金数据集；统一状态/产物契约 |
| 上游 API 限流和变化 | 高/中 | 官方协议、限流/重试、缓存、契约测试、明确上游错误和降级 |
| 许可证冲突 | 中/高 | Manifest 保存 SPDX/使用限制；商业工具不得自动下载；导出时携带许可证 |
| 大规模图形冻结桌面 | 中/中 | 懒加载、抽样、虚拟化、节点/边上限、后台布局 |
| 权限源不一致 | 中/高 | 单一事实源；引入 Casbin 时 shadow 模式和决策差异审计 |
| 产物不可复现 | 中/高 | 输入/输出哈希、版本/digest、参数、随机种子、环境、RO-Crate 和黄金复跑 |

## 7. 建议优先级与工作量级别

| 优先级 | 交付 | 量级 | 放行门槛 |
|---|---|---:|---|
| P0（已实现） | Manifest v1、插件真实状态机、Bioconda 只读同步/缓存、容器/WSL 平台探测 | 已交付 | 契约、离线缓存、原子回滚、恶意输入、RBAC、路径越界测试已加入套件；仍需独立安全评审 |
| P1（控制面已实现） | Nextflow/nf-core adapter、固定 revision、WSL2、trace/取消/resume/溯源、结果清单和桌面 UI | 已交付控制面 | 16 项定向测试与 237 项全量套件通过；真实 nf-core 黄金小数据和科学结果契约仍需具备 WSL2/容器/参考数据的集成环境 |
| P1 | Zotero/Pyzotero、RO-Crate 导出 | 2–4 周 | 去重、密钥、隐私和 validator 测试 |
| P1 | Vue Flow + Plotly/Cytoscape | 3–5 周 | 无障碍、10k 节点、保存往返测试 |
| P2 | Snakemake adapter、CWL 导入/导出 | 4–7 周 | 与默认引擎状态契约一致 |
| P2（桌面核心已实现） | 原始数据加密、验证下载、旧数据迁移、HMAC 审计链与桌面安全页 | 已交付桌面核心 | 安全专项自动化测试、全量回归和桌面构建；机构放行仍需威胁建模、外部锚定、恢复演练与合规评审 |

工作量是假设 2–3 名熟悉 Python/Vue/生物工作流的工程师，并不包含机构采购、HPC 运维、商业许可证或临床合规认证时间。

## 8. 不建议的做法

- 不把 Galaxy、Nextflow 或容器守护进程塞入桌面主进程。
- 不从自然语言直接拼接 shell 命令，也不让插件目录记录绕过 Manifest 校验。
- 不把“conda 解析成功”当成“科学流程验证通过”。工具探针、小数据集和结果契约缺一不可。
- 不同时承诺 Nextflow、Snakemake、CWL 三套执行语义完全等价。
- 不把本地静态加密和哈希链检测等同于临床或人类基因组数据合规；机构部署仍需外部锚定、密钥恢复、保留策略与独立评审。
- 不允许推荐器自行安装、启用或升级工具；推荐、批准、部署、验证是四个独立事件。
