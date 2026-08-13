# 功能恢复与完整性验收报告

日期：2026-08-14（Asia/Shanghai）

## 1. 恢复原则与结论

本轮修复采用“保留优先、可验证、可回退”的原则。未清理用户数据库、模型配置、会话、界面源码、插件、技能、日志或运行证据；重新生成了可再现的前端依赖、前端生产资源、PyInstaller 构建目录和桌面发行目录。

当前可直接运行的桌面程序为：

```text
dist\ResearchAgent\ResearchAgent.exe
```

最终程序版本为 1.3.0，大小 38,468,588 字节，SHA-256：

```text
7F326E2C285681A47AF82EDAE6DA144CE235858E7E2E9EDE2B72BA51C25F9B30
```

最终同步构建之前的发行目录保存在 `dist-pre-sync-backup-20260814`，最初恢复的发行目录保存在 `dist-restored-backup-20260814`，较早的候选构建保存在 `dist-candidate`。这些目录未被删除。恢复前代码状态已创建本地标记 `local-restored-20260814`。

## 2. 已恢复并保留的资产

- Vue 3 桌面界面源码、`frontend/node_modules` 与 `frontend/dist`；生产构建共转换 105 个模块。
- Python 源码、测试、构建脚本、`build` 与完整的 PyInstaller onedir 发行目录。
- 项目内已有 SQLite 数据库；真实桌面数据继续使用 `%APPDATA%\ResearchAgent`，本轮未改写该目录中的用户数据库、密钥、会话或配置。
- 插件市场、统一 Skill 框架、NCBI、工作流、科研运行时、多模型、科研写作、统计/可视化、安全审计、分子对接及结构工具模块。
- WSL2 Ubuntu 24.04、Java 21、Nextflow 25.10.2 和 Docker 29.1.3 系统环境。这些系统组件并未被删除。
- 所有新的隔离验证数据保留在 `runtime-validation`，完整 RNA-seq 运行证据保留在 `runtime-validation/restored-desktop-full-e2e`。

## 3. 根因与修复

| 问题 | 根因 | 已实施修复 |
|---|---|---|
| 本地生成环境缺失 | 将可重建文件和本机可用运行资产混同处理 | 重装前端依赖、重建前端资源与桌面发行版；保留旧发行版作为回退点 |
| 新 Nextflow 缓存无法下载 | WSL NAT 无法使用 Windows 回环代理，WSL 内 Git 无法直连 GitHub | 由 Windows Git 在可信网络平面预取固定版本，再交给 WSL/Nextflow 执行 |
| Linux 脚本出现 `Rscript\r` | Windows Git 默认行尾转换破坏了容器中执行的脚本 | 仓库级固定 `core.autocrlf=false`、`core.eol=lf`、`core.safecrlf=true` |
| APPDATA 下长路径检出不完整 | Windows 路径长度与普通文件读取限制 | 固定 `core.longpaths=true`，并通过 Git 对象接口校验工作树，不依赖普通长路径读取 |
| 缓存是否可信无法证明 | 只检查标签或工作树状态不足以发现 CRLF 内容变化 | 固定 nf-core tag 和 commit SHA；逐文件比较索引对象与工作树原始 blob SHA |
| 下载/激活中断可能污染正式缓存 | 缺少准备阶段和原子切换契约 | 新增 `prepare_pipeline` 阶段；候选目录验证后才原子激活，旧目录保留为备份，失败候选保留供诊断 |
| 子进程异常处理不完整 | blob 批量校验可能无限等待 | 增加 120 秒超时、进程终止、等待回收及明确错误信息 |

固定来源如下：

- `nf-core/rnaseq@3.26.0` → `e7ca46272c8f9d5ceee3f71759f4ba551d3217a4`
- `nf-core/sarek@3.9.0` → `b97952e5bac68d5deb93d4a3349a45f146be9830`

## 4. 测试用例与执行结果

| 层级 | 关键用例 | 结果 |
|---|---|---|
| 静态检查 | 本轮修改的执行后端、管理器与测试文件 | Ruff 通过 |
| 单元/集成 | 认证、API、插件、Skill、NCBI、工作流、安全、模型、科研运行时、Nextflow | 259 passed，0 failed |
| 新增回归 | CRLF/内容篡改必须使缓存失效 | 通过 |
| 新增回归 | 固定提交预取、LF/longpaths 配置、原子激活 | 通过 |
| 新增回归 | `preflight → prepare → plan → execute` 顺序及缓存来源持久化 | 通过 |
| 前端 | Vue 3 生产构建 | 通过，105 modules |
| 桌面安全黑盒 | AES-256-GCM 信封、重启解密、密文篡改阻断、审计链 | 通过；篡改返回 HTTP 409，审计链有效 |
| 模型/科研流程黑盒 | 五类 provider、DeepSeek 缺钥匙错误、九阶段科研流程、全局运行时回收 | 通过；九阶段 100% 完成，active=0、waiting=0 |
| 系统深度预检 | WSL2、Nextflow、Docker、Linux 存储、FIFO | 通过；无问题项 |
| 真实业务 E2E | 官方 `nf-core/rnaseq@3.26.0` 的 `test,docker` | 通过；退出码 0 |

真实 RNA-seq 端到端运行 ID 为 `72145c82-ab25-4c49-a4a0-133631f6004a`：234 个任务（25 cached、209 completed、0 failed），生成 967 个结果文件；结果清单完整且未截断。执行资源限制为 4 CPU、7 GB、并发容量 1，实测提交峰值为 1。Nextflow report、timeline、trace、DAG、日志和 MultiQC 报告均存在并通过 SHA-256 记录。

标准 `dist` 路径上的最终程序再次完成独立深度预检：应用健康、认证成功、Nextflow 25.10.2 可用、Docker ready、ext2/ext3 工作存储 ready、FIFO ready、问题列表为空。

最终安全验收的第一次重启探测遇到隔离锁记录仍为 `port: null` 的启动时序状态，验证脚本在超时后明确失败并保留现场；全新隔离配置重跑后全部安全断言通过。该现象没有发生在真实用户目录，不涉及加密数据损坏，也未被隐去或当作成功处理。

## 5. 功能完整性核对

- 桌面生命周期：单实例、嵌入式 API、WebView2、托盘、窗口状态和浏览器回退均保留。
- 科研 Agent：证据检索、假设生成、反思、排序/辩论、演化、元审查、实验设计、写作、规范检查九阶段可完整执行。
- 模型：DeepSeek、Agnes、OpenAI、Anthropic、Google provider 保留；密钥按用户加密存储，失败、超时和重试语义统一。
- 生物信息学：插件市场、Skill、NCBI、DAG 工作流、推荐、结果可视化和 nf-core 生产执行链保留。
- 安全：本地回环绑定、JWT、RBAC、用户隔离、AES-256-GCM、完整性校验和 HMAC 审计链通过黑盒测试。

## 6. 已知外部边界

- DeepSeek 实时请求需要用户自行配置 `DEEPSEEK_API_KEY`；无密钥行为已验证为明确的 `missing_api_key`，不会伪报成功。
- Agnes 的接口、CLI 模式及历史实时 smoke 已有记录；本轮最终包验收未再次消耗 Agnes 在线服务额度。
- NCBI 协议与 mock/集成测试通过；实时检索仍受 NCBI 网络和限流策略影响。
- Glide、GOLD 等授权软件以及部分结构工具必须由用户另行安装并满足其许可证。

## 7. 版本控制与发布策略

`dist`、`build`、`frontend/node_modules`、`frontend/dist`、`runtime-validation` 和 `pipeline-runs` 都在 `.gitignore` 中；它们保留在本机供直接运行和审计，不会被误提交为源码。GitHub 上传当前暂停，防止在用户确认前覆盖远端或发布不完整状态。
