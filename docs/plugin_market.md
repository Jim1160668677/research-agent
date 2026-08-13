# 生物分析工具插件市场

统一管理生物信息学能力目录、版本、依赖、隔离部署、验证与更新。系统明确区分“发现/选择”和“真实部署”，目录中存在工具绝不等于本机已经安装。

## 1. 功能总览

| 功能 | 说明 |
|------|------|
| **版本控制** | 每个工具维护版本历史 (plugin_versions)，支持版本切换/回滚/注册新版本 |
| **Capability Manifest v1** | 严格 JSON Schema、输入输出契约、固定版本运行时、权限/资源声明、来源与 SHA-256 摘要 |
| **真实生命周期** | `discovered → selected → deploying → deployed → verified → enabled`，失败、停用、移除均有独立状态 |
| **依赖管理** | 传递依赖闭包解析、循环检测、版本冲突检测、拓扑排序安装顺序 |
| **可信目录同步** | 管理员从固定 HTTPS Bioconda repodata 只读同步指定包；支持 ETag/时间缓存、来源摘要和原子回滚 |
| **隔离部署** | 按平台与安装方式生成执行计划；Conda/Python 每工具独立前缀，固定版本，argv-only 执行 |
| **平台探测** | 只读检测 Conda、Docker/Podman、Apptainer、WSL2、Nextflow、Snakemake，并明确 Windows 限制 |
| **更新机制** | 市场最新版 vs 已装版本对比，一键升级，changelog 展示 |
| **用户评价** | 1-5 星评分 + 评论，评分分布直方图，已装用户徽标 |
| **分类浏览** | 9 个分类 (docking/structure/alignment/...)，带计数 |
| **技术渠道** | 官网 / 文档 / 支持邮箱 / 许可证 / 平台兼容性展示 |
| **安全** | 平台兼容检查、安装命令白名单化、部署历史审计、模拟模式预览 |

## 2. 核心工具

### 分子对接 (docking)
| 工具 | 版本 | 安装方式 |
|------|------|----------|
| AutoDock Vina | 1.1.2 → 1.2.3 → **1.2.5** | conda (conda-forge) |
| Glide | 2023-3 → **2024-2** | 手动 (商业, 需 Maestro) |
| GOLD | 2023.1 → **2024.2** | 手动 (商业) |

### 蛋白质结构 (structure)
| 工具 | 版本 | 安装方式 |
|------|------|----------|
| PyMOL | 2.5.0 → **2.6.0** | conda (pymol-open-source) |
| UCSF ChimeraX | 1.7 → 1.8 → **1.9** | 手动 (官网下载) |
| Swiss-PdbViewer | **4.1.0** | 手动 (免费软件) |

### 生信分析套件
fastqc, trimmomatic, bwa, samtools, hisat2, featurecounts, kallisto, DESeq2, cutadapt, bowtie2, stringtie, fastp

### 运行时依赖 (runtime)
java, R, Bioconductor, htslib, subread, MGLTools, Maestro —— 作为依赖节点自动解析

## 3. API 使用

### 版本控制
```bash
# 版本历史
GET  /api/v1/plugins/{id}/versions

# 仅在 selected 状态切换版本；已部署环境必须重新部署
POST /api/v1/plugins/{id}/versions/1.2.3/switch

# 注册新版本发布
POST /api/v1/plugins/{id}/versions
{"version": "1.3.0", "changelog": "新增功能", "release_date": "2026-01-01"}

# 删除版本 (撤回)
DELETE /api/v1/plugins/{id}/versions/1.2.3

# 升级到最新
POST /api/v1/plugins/{id}/upgrade
```

### 依赖管理
```bash
GET /api/v1/plugins/{id}/dependencies
# → {order: [...], missing: [...], satisfied: [...], conflicts: [...], cycle: null}
```
安装 DESeq2 会解析出 `[r, bioconductor, deseq2]` 的安装顺序。

### 一键部署
```bash
# 加入当前用户的工具清单（不会安装软件）
POST /api/v1/plugins/install
{"plugin_id": 1, "version": "0.12.1"}

# 模拟 (生成计划，预览步骤)
POST /api/v1/plugins/{id}/deploy
{"simulate": true}

# 真实执行 (conda/pip 自动安装)
POST /api/v1/plugins/{id}/deploy
{"simulate": false}

# 部署历史 (审计)
GET /api/v1/plugins/{id}/deploy/history

# 验证真实安装
POST /api/v1/plugins/{id}/verify

# 验证通过后启用/停用
POST /api/v1/plugins/{id}/enable
POST /api/v1/plugins/{id}/disable

# 管理员删除受管隔离环境；只允许 plugin-envs 下的 plugin-* 目录
DELETE /api/v1/plugins/{id}/deployment

# 未部署时移出工具清单
DELETE /api/v1/plugins/{id}
```

### Manifest、可信目录与平台能力

```bash
GET  /api/v1/plugins/manifest/schema
POST /api/v1/plugins/manifest/validate
GET  /api/v1/plugins/{id}/manifest

# 管理员只读同步元数据；不会选择、下载或安装包
POST /api/v1/plugins/catalogs/bioconda/sync
{"packages": ["fastqc", "samtools"], "subdirs": ["linux-64", "noarch"]}
GET  /api/v1/plugins/catalogs/bioconda/history

# 普通检测不执行命令；deep=true 仅管理员可用并执行版本探针
GET /api/v1/plugins/platform/capabilities?deep=false
```

### 评价与更新
```bash
POST /api/v1/plugins/{id}/reviews   # {"rating": 5, "comment": "..."}
GET  /api/v1/plugins/{id}/reviews   # 评价列表 + 评分分布
GET  /api/v1/plugins/updates        # 可更新列表
GET  /api/v1/plugins/categories     # 分类计数
GET  /api/v1/plugins/?sort=rating   # 排序: rating/downloads/name/newest
```

## 4. 架构

```
前端 Plugins.vue (市场页面)
  ↓ REST
core/api/plugins.py        ← API 层
  ↓
plugins/manager.py         ← PluginManager: 市场/版本/评价/更新
plugins/dependency_resolver.py ← DependencyResolver: 依赖图/版本约束
plugins/deployer.py        ← Deployer: 平台检测/安装计划/执行/验证
plugins/manifest.py        ← CapabilityManifest v1 + canonical digest
plugins/lifecycle.py       ← 追加式用户生命周期
plugins/catalog_sync.py    ← Bioconda 固定源同步、缓存、来源记录
plugins/platform_probe.py  ← WSL/容器/工作流运行时探测
  ↓
core/models/db.py          ← Plugin / PluginVersion / PluginReview / PluginInstallation
plugins/seed.py            ← 25 个预置工具 + 版本历史 + 种子评价
```

## 5. 部署模式说明

| install_method | 行为 |
|----------------|------|
| `conda` | 检测 conda/mamba → 固定工具版本 → 在受管独立前缀执行并记录结果 |
| `pip` | 创建独立 venv → 固定版本 pip install，不写入桌面主环境 |
| `binary` | 按当前平台给出下载 URL + 手动配置引导 |
| `manual` | 商业/专属软件 (Glide/GOLD/ChimeraX)：官网指引 + 支持邮箱 |

任何模式下 `simulate=true` 都不会执行命令或推进生命周期。真实部署仅限管理员，并通过追加式 `PluginInstallation` 事件留痕；只有部署成功才进入 `deployed`，只有隔离环境探针成功才进入 `verified`。移除环境会先验证目标位于受管根目录内。

## 6. 测试

`tests/test_plugins_market.py` 与 `tests/test_plugin_integrations.py` 共覆盖 44 个场景，包括：
- 版本约束解析 (>=, <=, ==, 范围)
- 传递依赖闭包 / 安装顺序 / 循环检测 / 冲突检测
- 部署计划生成 (conda/abort/download/平台不兼容)
- 市场 API 集成 (核心工具存在、版本切换、注册、评价聚合、更新流程、部署模拟、排序)
- Manifest 严格校验、版本锁定、容器 digest 拒绝、选择/部署状态分离
- Bioconda 元数据导入、断网缓存、失败原子回滚、恶意包名拒绝
- WSL 输出解码、平台能力结构、受管环境安全删除与越界拒绝
