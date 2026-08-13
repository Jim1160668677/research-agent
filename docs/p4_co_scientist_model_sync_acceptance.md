# P4 Co-Scientist、多模型与同步运行验收报告

日期：2026-08-13  
版本：Research Agent 1.3.0  
结论：**源代码功能验收通过；Agnes 真实调用通过；DeepSeek 协议与故障测试通过但因当前环境未配置 `DEEPSEEK_API_KEY`，未声明真实 DeepSeek 网络调用通过。**

## 1. 范围与第一性原理结论

科研智能体的核心产物不是一段流畅文本，而是一条可追溯、可质疑、可复跑、可由研究者接管的证据—假设—实验链。因此本轮没有把论文架构机械复制为更多聊天角色，而是把以下不可约约束落实为持久化软件契约：

1. 每项科学主张必须能回到证据或明确标记证据缺口；
2. 候选假设必须经反思、相互比较、演化和总评审，不能一次生成即成为结论；
3. 实验、写作、工作流、外部流水线和模型调用共享同一个有界资源协调器；
4. 模型失败必须区分缺少凭据、鉴权、限流、超时、网络、上游和无效响应；
5. 用户凭据和模型偏好按用户隔离，多智能体不能读取其他用户的默认模型；
6. 应用重启后的孤儿任务必须进入可解释终态，不能永久显示“运行中”；
7. 自动化输出是决策支持，伦理、安全、学术规范和最终实验判断保留研究者审阅门。

## 2. Nature Co-Scientist 理念映射

参考论文：[Accelerating scientific discovery with Co-Scientist](https://www.nature.com/articles/s41586-026-10644-y)。论文描述了 Supervisor、异步任务队列、持久上下文，以及 Generation、Reflection、Ranking、Evolution、Proximity、Meta-review 等专用智能体组成的生成—争辩—演化循环。

| 论文理念 | 本系统 1.3.0 实现 | 说明 |
|---|---|---|
| 自然语言研究目标 | Research Workspace 与持久化 ResearchRun | 目标、领域、约束、材料和网络策略均入库 |
| Supervisor / 异步资源分配 | ResearchPlanner + ResearchRuntime + RuntimeCoordinator | DAG 依赖、最大并发、超时、重试、取消和资源快照 |
| Generation | `hypothesis_generation` | 从规范化证据生成多个候选和可证伪预测 |
| Reflection | `hypothesis_reflection` | 按合理性、新颖性、可检验性、安全和证据缺口批判 |
| Ranking / debate | `hypothesis_ranking` | 候选排序并保存 pairwise debate 记录 |
| Evolution | `hypothesis_evolution` | 依据反思/排名修订候选并保存 lineage |
| Meta-review | `hypothesis_meta_review` | 汇总推荐、限制、下一步和研究者审阅要求 |
| Proximity | 证据术语、证据定位器和重复消解 | 当前为确定性相关性代理；没有虚构为论文的专用神经相似度模型 |
| 持久上下文 | ResearchRun、Step、Evidence、Artifact、Conversation | 支持长任务状态、来源和人工反馈持久化 |
| Scientist-in-the-loop | 审批策略、伦理检查、完整性检查、学习提案 | 反馈不会静默修改在线技能 |

完整默认发现链为：

```text
literature → generation → reflection ┐
                    generation ───────┼→ ranking → evolution → meta_review
                                     └───────────────────────────────┬───────┐
                                                                     experiment → writing → integrity
```

## 3. 大模型接口实现

### 3.1 统一契约

五个 Provider 均通过 `LLMMessage` / `LLMResponse` 暴露相同异步接口，响应包含 provider、model、usage、attempts 和 latency。前后端共享 Provider 描述、可用模型、运行方式和健康检查结果。

| Provider | 接入方式 | 当前模型 | 可靠性措施 | 实测状态 |
|---|---|---|---|---|
| DeepSeek | 官方 OpenAI-compatible API | `deepseek-v4-pro`, `deepseek-v4-flash` | 显式 base URL、超时、指数抖动重试、reasoning 参数、错误归一化 | 契约/重试测试通过；无真实 Key，未做网络成功声明 |
| Agnes | 官方 CLI-first | `agnes-2.0-flash` | argv-only 子进程、无 shell、CLI 版本门、超时终止、JSON Schema 检查、重试 | 真实调用通过 |
| OpenAI | 官方 Python SDK | 注册表模型 | 同一错误/超时/重试契约 | 回归通过 |
| Anthropic | 官方 SDK | 注册表模型 | 用户隔离、超时、统一响应 | 回归通过 |
| Google | 官方 SDK | 注册表模型 | 用户隔离、超时、统一响应 | 回归通过 |

DeepSeek 实现依据其当前官方说明：OpenAI 格式基址为 `https://api.deepseek.com`，当前稳定别名是 `deepseek-v4-pro` 与 `deepseek-v4-flash`。参见 [DeepSeek API documentation](https://api-docs.deepseek.com/)。

Agnes 遵循本项目 Agnes skill 的 CLI-first 约束，运行 `agnes-ai-cli@^0.1.0`，接受范围 `>=0.1.0,<0.2.0`。Windows 明确使用 `npx.cmd`，避免 PowerShell execution policy 阻断 `npx.ps1`。

### 3.2 凭据、偏好和健康检查

- API Key 经 Fernet 加密后按用户保存；列表和状态接口只显示掩码；
- 查找顺序为用户数据库、进程内缓存、环境变量；
- 未配置 Key 的 Provider 不能被设为共享默认模型，返回 HTTP 409；
- ChatEngine、ResearchAgent 和 LangGraph Coordinator 使用同一用户偏好；
- `live=false` 只检查本地配置/运行时，不误报远程连通；`live=true` 才产生最小模型请求；
- 日志和错误响应不回显 API Key、请求头或上游原始敏感正文。

## 4. 同步运行、恢复和完整业务流

`RuntimeCoordinator` 是进程级公平信号量和活动租约登记表，当前上限为 6。LLM、科研能力、通用工作流节点和外部执行后端均在执行前申请租约，`/api/v1/system/runtime` 同时公开活动数、等待数和各运行管理器的活动 ID。

科研运行仍保留每个计划的较小并发上限；两级限制的目的分别是保护单个计划和保护整个桌面进程。取消经 `asyncio.CancelledError` 传播；模型/外部进程有显式超时；应用启动时将遗留的 research/workflow/pipeline `pending/running` 状态转换为 `interrupted` 并写入原因及完成时间。

冻结桌面业务验收执行九个阶段，要求全部为 `completed/degraded`、总进度 100%、至少一个候选假设、Meta-review 有推荐、运行结束后协调器 active/waiting 均为 0。

## 5. 测试记录

### 5.1 用例与结果

| ID | 类型 | 用例 | 预期 | 结果 |
|---|---|---|---|---|
| UT-MODEL-01 | 单元 | Provider 模型注册与旧模型拒绝 | V4/Agnes 可用，无效模型明确失败 | 通过 |
| UT-MODEL-02 | 单元 | DeepSeek 请求/响应归一化 | 官方参数、usage、延迟正确 | 通过 |
| UT-MODEL-03 | 单元 | 上游瞬时失败 | 按上限重试并记录 attempts | 通过 |
| UT-AGNES-01 | 单元 | Agnes argv 与 JSON | 无 shell、角色提示单行、usage 正确 | 通过 |
| UT-AGNES-02 | 单元 | CLI 版本不兼容 | 在调用前以结构化错误拒绝 | 通过 |
| UT-SYNC-01 | 单元/性能 | 8 个任务争用 2 个槽位 | 峰值为 2、最终 active=0 | 通过 |
| UT-PLAN-01 | 单元 | 科研发现 DAG | 依赖无环且九阶段顺序正确 | 通过 |
| IT-API-01 | 集成 | 状态、Key、偏好、健康与 runtime API | 用户隔离；未配置偏好被阻止 | 通过 |
| IT-RECOVERY-01 | 集成 | 模拟重启遗留任务 | 运行/步骤转为 interrupted | 通过 |
| FT-CS-01 | 功能 | 两条本地证据跑完整发现链 | 九阶段完成、进度 100% | 通过 |
| LT-AGNES-01 | 真实集成 | Agnes 最小 `pong` 调用 | 一次成功、模型与 usage 可解析 | 通过：4716 ms，308 tokens |
| LT-DEEPSEEK-01 | 真实集成 | DeepSeek 最小调用 | 需要真实凭据 | 未执行：环境未配置 Key |
| REG-ALL-01 | 回归 | 完整 Python 套件 | 无失败 | **256 passed / 0 failed / 244.57s** |
| BUILD-UI-01 | 构建 | Vue production build | 无构建错误 | 通过：105 modules / 2.25s |
| BUILD-EXE-01 | 构建 | PyInstaller onedir | 生成可启动 EXE | 通过；585.4s；见第 8 节 |
| FROZEN-P4-01 | 冻结功能 | EXE 内模型诊断和九阶段闭环 | 版本/注册/策略/DAG/runtime 全通过 | 通过：冻结 Agnes live 4508ms；见第 8 节 |

全量测试有 3 条已知非失败警告：Starlette TestClient 的上游弃用提示、故意损坏 GenBank LOCUS fixture 的 Biopython 解析警告、工作区 ACL 阻止 pytest 写 `.pytest_cache`。三者均不改变断言结果。

### 5.2 问题—根因—修复台账

| 问题 | 根因 | 修复 | 回归证据 |
|---|---|---|---|
| DeepSeek 模型名陈旧 | 上游模型别名随时间变化 | 对照 2026-08-13 官方文档更新到 V4，并严格校验模型 | UT-MODEL-01/02 |
| Provider “已配置”被误认为在线 | 旧检查只判断字符串是否存在 | 拆分本地与 live 健康检查 | IT-API-01 |
| Windows Agnes 无法运行 | PowerShell 禁止 `npx.ps1` | Windows 显式解析 `npx.cmd` | LT-AGNES-01 |
| Agnes 真实返回无法解析 | `npx.cmd` 将提示词 CR/LF 当批处理边界，导致 `--json` 被丢弃 | CLI 传输提示改为单行角色分隔，保留语义而不含换行 | UT-AGNES-01 + LT-AGNES-01 |
| 研究/工作流/外部进程各自限流 | 没有进程级共享资源事实源 | 引入 RuntimeCoordinator 并接入四类执行入口 | UT-SYNC-01、runtime API |
| 重启后永久运行态 | 内存任务丢失但数据库状态未恢复 | 启动恢复为 interrupted，写入原因与时间 | IT-RECOVERY-01 |
| 多智能体可能读取非当前用户 Key | Coordinator 创建 ChatEngine 时没有 user_id | user_id 从鉴权 API 贯穿到汇总模型 | 完整用户隔离回归 |
| 测试环境读取真实 Agnes 环境变量 | 测试 fixture 只清理旧三家 Provider | autouse fixture 清理五家 Provider 配置 | 256 项全量回归 |

## 6. 性能数据

环境：Windows、Python 3.13.9；这些是本机回归基线，不是跨机器 SLA。

| 工作负载 | 次数 | 结果 |
|---|---:|---:|
| DeepSeek 请求契约构造 | 10,000 | mean 0.0012 ms；p95 0.0013 ms；max 0.0301 ms |
| Agnes JSON 解析/归一化 | 5,000 | mean 0.1320 ms；p95 0.1788 ms；max 32.4454 ms |
| RuntimeCoordinator | 10,000 | 397.336 ms；0.0397 ms/操作 |
| 完整科研计划构造 | 1,000 | 0.0271 s；0.027 ms/次 |
| 200 条证据规范化 | 200 | 0.6112 s；3.056 ms/次 |
| 50,000 行表格画像 | 3 | 4.5078 s；1502.610 ms/次 |
| Agnes 真实网络调用 | 1 | 4716 ms；一次成功；308 tokens |

协议层开销相对网络/模型推理可忽略。表格画像较 P3 基线变慢，主要受本次运行时磁盘/杀毒/缓存状态影响；它仍为有界本地任务，但建议后续将大表画像迁到线程池并建立冷/热缓存分离基线。

## 7. GitHub 开源组件评估与集成决策

| 项目 | 活跃度/兼容性判断 | 本轮决定 | 风险与控制 |
|---|---|---|---|
| [deepseek-ai/DeepSeek-V3](https://github.com/deepseek-ai/DeepSeek-V3) | 官方、活跃；API 可用 OpenAI SDK | 采用官方协议/模型文档，不在桌面包内嵌大权重 | 上游别名变化；契约测试和显式注册表 |
| [jomeswang/agnes-ai-cli](https://github.com/jomeswang/agnes-ai-cli) | 与 Agnes skill 一致，Node CLI 可在桌面外部运行；社区规模较小 | 已集成 CLI-first adapter | 固定 `^0.1.0` 且运行时门 `<0.2.0`；无 shell；版本/JSON 检查 |
| [jd/tenacity](https://github.com/jd/tenacity) | 成熟 Python 重试库，支持 async | 已用于 Provider 有界重试 | 仅重试可恢复错误；设置次数和退避上限 |
| [openai/openai-python](https://github.com/openai/openai-python) | 官方 SDK；与 DeepSeek 官方兼容说明一致 | 复用现有依赖实现 DeepSeek | 禁用 SDK 内部重试，避免双重放大；本系统统一控制 |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 活跃；适合有状态智能体图 | 保留现有 Coordinator；科学质量环用持久化 DAG | 不让内存图成为科研记录的唯一事实源 |
| [nextflow-io/nextflow](https://github.com/nextflow-io/nextflow) | 生信流水线成熟、跨执行后端 | 保留已验证的外部执行适配器 | 固定 revision、允许列表、WSL2 隔离、结果清单 |
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | Provider 面广、网关功能强、开发活跃 | 本轮评估但不嵌入桌面包 | 会复制当前网关职责并显著扩大依赖/攻击面；适合未来机构服务器模式 |

集成步骤统一为：核对许可证和官方文档 → 固定兼容范围 → 建立最小适配器 → 禁止 shell 字符串 → 加契约/错误/超时测试 → 再做真实 smoke → 冻结包复验。第三方项目的 star/fork 数不作为科学适用性或供应链安全证明。

## 8. 桌面发布物

- 可执行文件：`dist/ResearchAgent/ResearchAgent.exe`
- EXE 字节数：38,460,859
- EXE SHA-256：`9157021846D58ADD5F853C55DCE2166A1069111BCBD89A09013EA2CA5495F8A4`
- onedir 文件数/总字节数：1,388 / 593,352,246
- 冻结 P4 原始运行目录：验收完成后作为可再生成的隔离测试数据清理；关键结果、时间和校验和保留在本报告中。

冻结黑盒验证从全新 `%APPDATA%` 启动实际 EXE，确认应用版本 1.3.0、单实例 PID 匹配、五个 Provider 完整、Agnes CLI 0.1.0 真实调用成功（4508 ms）、DeepSeek 无凭据诊断为 `missing_api_key`、未配置 Provider 偏好返回 HTTP 409、九阶段科研运行完成到 100%，并在结束时观测 `active=0`、`waiting=0`。

Agnes 运行时不会被悄悄打进 PyInstaller：目标机若要使用 Agnes，需要 Node.js 20+ 和可用的 `npx.cmd`/Agnes CLI 下载缓存。健康检查会如实报告 runtime 缺失。DeepSeek 使用已打包的 Python SDK，不需要 Node.js。

## 9. 剩余边界与下一步

1. 本轮没有 DeepSeek 真实 Key，因此不能把协议测试等同于生产账户可用性；配置凭据后应执行 live health smoke。
2. 当前 Proximity 是可解释的证据相关性代理，不等于论文中的专用相似度/邻近智能体；后续可加入向量索引，但必须保存模型版本和距离证据。
3. “自主学习”仍是提案式学习：人工批准前不改变在线行为，这是科研安全设计而非功能缺失。
4. 没有把论文结果当作本系统科学有效性的证明；本系统生成的假设仍须领域专家和独立实验验证。
5. 大规模机构部署建议把 LiteLLM 类网关放在独立服务边界，并增加预算、审计、区域路由和数据驻留策略，而不是塞入本地桌面进程。
