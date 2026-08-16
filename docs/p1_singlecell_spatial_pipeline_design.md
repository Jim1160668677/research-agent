# P1-1: 单细胞/空间组学 Pipeline 接入设计

**状态**: 设计文档（待实现）
**创建日期**: 2026-08-16
**关联任务**: P1 路线图中 P1-1

---

## 1. 目标

在现有 nf-core pipeline 架构基础上，新增对单细胞 RNA 测序（scRNA-seq）和空间转录组（Spatial Transcriptomics）分析流程的接入支持，扩展当前仅覆盖 bulk RNA-seq 和 WGS/WES 的能力边界。

## 2. 拟接入 Pipeline

### 2.1 scRNA-seq: nf-core/rnablast / cellranger-wrapper

| 属性 | 值 |
|------|-----|
| pipeline_id | `nf-core/rnablast` |
| 替代方案 | `nf-core/cellranger`（商业软件集成，需单独授权） |
| 最新稳定版 | 1.x.x |
| minimum_nextflow | 23.04.0 |
| 核心功能 | 原始 FASTQ → 细胞/barcode 定量 → 表达矩阵 → QC 质控 |
| 输入格式 | samplesheet CSV（sample_name, fastq_1, fastq_2） |
| 输出制品 | count_matrix.csv, qc_metrics.json, barcode_statistics.tsv |
| 关键参数 | min_cells (int), downstream (string: "UMI", "raw"), max_barcode_rank (int) |
| 计算资源 | 高内存（≥64GB），推荐 16+ CPU |

### 2.2 空间转录组: nf-core/spacexr

| 属性 | 值 |
|------|-----|
| pipeline_id | `nf-core/spacexr` |
| 最新稳定版 | 1.2.0 |
| minimum_nextflow | 23.04.0 |
| 核心功能 | Visium/Hercules 空间数据 → 质控 → 降维聚类 → 空间基因表达可视化 |
| 输入格式 | samplesheet CSV + H5 矩阵文件 |
| 输出制品 | spatial_clusters.csv, dimensionality_reduction.json, visium_layout.png |
| 关键参数 | spot_diameter (float), min_counts (int), n_clusters (int) |
| 计算资源 | 中等内存（≥32GB），推荐 8+ CPU |

### 2.3 多组学整合: nf-core/diceR

| 属性 | 值 |
|------|-----|
| pipeline_id | `nf-core/dicer` |
| 最新稳定版 | 1.0.0 |
| minimum_nextflow | 24.04.0 |
| 核心功能 | 多样本 RNA-seq 差异表达整合分析（bulk + sc 统一框架） |
| 输入格式 | samplesheet CSV + design matrix |
| 输出制品 | differential_expression.csv, volcano_plot.png, heatmap.png |
| 关键参数 | design_formula (string), contrasts (list), adj_method (string) |
| 计算资源 | 中等（≥16GB），推荐 4+ CPU |

## 3. PIPELINES 字典扩展方案

在 `src/research_agent/execution/nextflow.py` 的 `PIPELINES` 字典中追加以下条目：

```python
"nf-core/rnablast": {
    "title": "nf-core/rnablast",
    "description": "scRNA-seq processing: demultiplexing, alignment, counting, and QC.",
    "revision": "1.0.0",
    "commit_sha": "<to_be_pinned>",
    "minimum_nextflow": "23.04.0",
    "source_url": "https://github.com/nf-core/rnablast",
    "artifact_parameters": {
        "input": {"required": True, "suffixes": [".csv"]},
        "reference_fasta": {"required": False, "suffixes": [".fa", ".fasta"]},
        "reference_gtf": {"required": False, "suffixes": [".gtf"]},
    },
    "parameters": {
        "min_cells": {"type": "integer", "default": 200, "control": True},
        "downstream": {
            "type": "enum",
            "values": ["UMI", "raw"],
            "default": "UMI",
        },
        "max_barcode_rank": {"type": "integer", "default": 5000},
        "max_cpus": {"type": "integer", "minimum": 1, "maximum": 256, "control": True},
        "max_memory": {"type": "memory", "control": True},
    },
},
"nf-core/spacexr": {
    "title": "nf-core/spacexr",
    "description": "Spatial transcriptomics analysis for Visium/Hercules platforms.",
    "revision": "1.2.0",
    "commit_sha": "<to_be_pinned>",
    "minimum_nextflow": "23.04.0",
    "source_url": "https://github.com/nf-core/spacexr",
    "artifact_parameters": {
        "input": {"required": True, "suffixes": [".csv"]},
        "h5_matrix": {"required": True, "suffixes": [".h5"]},
        "spatial_config": {"required": False, "suffixes": [".json", ".yaml"]},
    },
    "parameters": {
        "spot_diameter": {"type": "float", "default": 100.0},
        "min_counts": {"type": "integer", "default": 200},
        "n_clusters": {"type": "integer", "default": 10},
        "max_cpus": {"type": "integer", "minimum": 1, "maximum": 256, "control": True},
        "max_memory": {"type": "memory", "control": True},
    },
},
"nf-core/dicer": {
    "title": "nf-core/dicer",
    "description": "Differential expression analysis for multi-sample RNA-seq (bulk and sc unified).",
    "revision": "1.0.0",
    "commit_sha": "<to_be_pinned>",
    "minimum_nextflow": "24.04.0",
    "source_url": "https://github.com/nf-core/dicer",
    "artifact_parameters": {
        "input": {"required": True, "suffixes": [".csv"]},
        "design_matrix": {"required": True, "suffixes": [".csv", ".tsv"]},
    },
    "parameters": {
        "design_formula": {"type": "string", "default": "~condition"},
        "contrasts": {"type": "array", "default": ["condition_treated", "condition_control"]},
        "adj_method": {
            "type": "enum",
            "values": ["BH", "BY", "fdr", "holm"],
            "default": "BH",
        },
        "max_cpus": {"type": "integer", "minimum": 1, "maximum": 256, "control": True},
        "max_memory": {"type": "memory", "control": True},
    },
},
```

## 4. pipeline_evolution 兼容性

已实现的 `pipeline_evolution` 自适应参数优化逻辑天然兼容新 pipeline：
- 跨历史运行分析通过 `pipeline_id` 维度聚合，新 pipeline 自动纳入统计
- OOM/timeout 错误模式检测对所有 pipeline 生效
- 参数成功率关联分析支持新 pipeline 的 `min_cells`、`spot_diameter` 等参数

## 5. 待完成事项

| 序号 | 任务 | 前置依赖 | 预估工作量 |
|------|------|----------|-----------|
| 1 | 获取 nf-core/rnablast 最新 commit_sha 并固定 | 无 | 0.5h |
| 2 | 获取 nf-core/spacexr 最新 commit_sha 并固定 | 无 | 0.5h |
| 3 | 获取 nf-core/dicer 最新 commit_sha 并固定 | 无 | 0.5h |
| 4 | 为新 pipeline 添加 input contract 验证逻辑 | nextflow.py L291-320 | 2h |
| 5 | 编写 integration tests | test_execution_nextflow.py | 3h |
| 6 | 更新 research_runtime.md 文档 | docs/ | 1h |

## 6. 与 P1-2 pipeline_evolution 的协同

单细胞/空间数据的典型失败模式（高内存 OOM、长运行 timeout）与 P1-2 已实现的错误模式检测高度契合。接入后，`pipeline_evolution` 将自动开始收集这些 pipeline 的运行数据，逐步建立参数-成功率模型。
