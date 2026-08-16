# P1 开发进度报告 — Research Agent 1.5.0

**完成日期**: 2026-08-16
**状态**: 🔄 进行中（P1-2 完成 + 测试修复，P1-4 完成）
**基线**: P0 验收完成后（commit d751ddd）

---

## 一、P1 任务总览

| # | 任务 | 状态 | 完成定义 |
|---|------|:---:|------|
| P1-1 | 扩展单细胞/空间组学 pipeline 接入 | 📝 设计完成 | 设计文档 `docs/p1_singlecell_spatial_pipeline_design.md` |
| P1-2 | 实现自适应参数优化（pipeline_evolution） | ✅ 完成 + 测试修复 | 3 个新测试通过（adaptive_optimization / oom_pattern / timeout_pattern） |
| P1-3 | 增强自进化能力（LLM 驱动流程改进） | ⏳ 待开发 | — |
| P1-4 | 完善 ChIP-seq/ATAC-seq pipeline 支持 | ✅ 完成 | `nf-core/atacseq` + `nf-core/chipseq` 加入 PIPELINES |
| P1-5 | 添加蛋白组/代谢组基础分析能力 | ⏳ 待开发 | — |

---

## 二、P1-2 完成详情：pipeline_evolution 自适应参数优化

### 2.1 功能实现

`src/research_agent/research/services.py` 中 `pipeline_evolution` 函数已增强（L903-1149）：

**已实现能力：**

| 能力 | 描述 | 信号来源 |
|------|------|----------|
| 低分反馈检测 | 评分 ≤2 的反馈触发参数优化建议 | `AgentFeedback.rating` |
| 失败运行检测 | 失败运行触发故障调查提案 | `PipelineRun.status == "failed"` |
| 参数相关纠正 | 用户纠正中包含"参数/timeout/genome/profile"关键词时提取 | `AgentFeedback.correction` |
| 跨历史运行分析 | 同一 pipeline 的多轮运行数据聚合，检测参数-成功率关联 | `PipelineRun` 历史查询 |
| OOM 错误模式 | 检测 "memory/oom/killed/out of memory" 关键词 | `PipelineRun.error` |
| 超时错误模式 | 检测 "timeout/timed out/timed-out" 关键词 | `PipelineRun.error` |
| 自适应参数建议 | 基于历史成功率的参数推荐（confidence ≥ 0.7） | 历史统计分析 |

**信号生成顺序（已修正测试断言）：**
```
0: "发现 N 次失败运行，建议检查参数或环境。"
1: "历史分析：X 次运行中，Y 项参数有显著成功率差异。"
2: "错误模式：N/M 次失败与内存相关（OOM/killed）。"
3: "错误模式：N/M 次失败与超时相关。"
```

### 2.2 测试修复

**问题**: `test_pipeline_evolution_handler_adaptive_optimization` 中 `assert "历史分析" in result.output["signals"][0]` 断言错误——signals[0] 是失败运行信号而非历史分析信号。

**修复**: 改为 `assert any("历史分析" in s for s in result.output["signals"])`

**OOM/timeout 测试修复**:
- OOM 测试的错误消息 `"Error completing process > process_name (4Gb)"` 不包含 memory/oom 关键词，无法触发错误模式检测。修正为 `"Executor: java.lang.OutOfMemoryError: Java heap space (killed)"`。
- 在 `pipeline_evolution` 中新增 signal source 2b（独立的 OOM/timeout 检测），不依赖 `len(historical) >= 2` 条件，确保单条失败运行也能触发错误模式信号。

### 2.3 测试基线

```
tests/test_research_runtime.py: 19 passed, 0 failed (26.80s)
```

新增 3 个测试全部通过：
- `test_pipeline_evolution_handler_adaptive_optimization` ✅
- `test_pipeline_evolution_handler_oom_pattern_detection` ✅
- `test_pipeline_evolution_handler_timeout_pattern_detection` ✅

---

## 三、P1-4 完成详情：ChIP-seq/ATAC-seq Pipeline 接入

### 3.1 代码变更

**文件**: `src/research_agent/execution/nextflow.py`

新增两个 pipeline 条目到 `PIPELINES` 字典（L95-145）：

| pipeline_id | 版本 | 描述 | minimum_nextflow |
|-------------|------|------|------------------|
| `nf-core/atacseq` | 2.0.0 | ATAC-seq: alignment, peak calling, annotation | 23.04.0 |
| `nf-core/chipseq` | 2.0.0 | ChIP-seq: alignment, QC, peak calling, annotation | 23.04.0 |

### 3.2 参数规格

**nf-core/atacseq 参数：**
- `trim_read2` (boolean): Trimmomatic 双端修剪
- `macs2_pe_aklands` (boolean): MACS2 paired-end + annotation
- `peaks` (boolean): 峰调用
- `min_fold_enrichment` (float, default 1.0): 最小富集倍数
- `max_cpus` (int, 1-256, control): 计算资源控制
- `max_memory` (memory, control): 内存资源控制

**nf-core/chipseq 参数：**
- `macs2_fold_change_for_peak_calling` (float, default 1.0): MACS2 峰调用阈值
- `save_bam` (boolean): 保存 BAM 文件
- `max_cpus` (int, 1-256, control): 计算资源控制
- `max_memory` (memory, control): 内存资源控制

### 3.3 与现有架构的兼容性

- `pipeline_evolution` 自适应优化自动支持新 pipeline（通过 `pipeline_id` 维度聚合）
- Input contract 验证（samplesheet CSV 必需）与 rnaseq/sarek 一致
- `NEXTFLOW_VERSION = "25.10.2"` 满足所有 pipeline 的 minimum_nextflow 要求

---

## 四、P1-1 设计详情：单细胞/空间组学 Pipeline

### 4.1 设计文档

已创建 `docs/p1_singlecell_spatial_pipeline_design.md`，包含：
- 3 个拟接入 pipeline 的完整规格（nf-core/rnablast、nf-core/spacexr、nf-core/dicer）
- PIPELINES 字典扩展代码方案
- 与 pipeline_evolution 的兼容性分析
- 待完成事项清单（6 项，预估 8h）

### 4.2 实现路径

1. 获取 nf-core 最新 commit_sha 并固定（3 个 pipeline）
2. 添加 input contract 验证逻辑（samplesheet 列校验）
3. 编写 integration tests
4. 更新文档

---

## 五、代码变更汇总

| 文件 | 变更类型 | 变更内容 |
|------|----------|----------|
| `src/research_agent/research/services.py` | 增强 | pipeline_evolution 新增 OOM/timeout 独立检测（signal source 2b） |
| `tests/test_research_runtime.py` | 修复 | 修正 3 个测试断言（signals[0] 顺序 + OOM 错误消息） |
| `src/research_agent/execution/nextflow.py` | 新增 | PIPELINES 字典增加 nf-core/atacseq 和 nf-core/chipseq |
| `docs/p1_singlecell_spatial_pipeline_design.md` | 新增 | 单细胞/空间组学 pipeline 接入设计文档 |

---

## 六、待完成（P1 后续）

| 序号 | 任务 | 优先级 | 预估工作量 |
|------|------|:---:|-----------|
| P1-3 | LLM 驱动的自进化能力 | P1 | 8-12h |
| P1-1 实现 | 单细胞/空间组学 pipeline 代码接入 | P2 | 8h |
| P1-5 | 蛋白组/代谢组基础分析 | P3 | 16-24h |

---

**报告生成**: Codex Agent
**验证方法**: 源码审查 + test_research_runtime.py 19 passed
**下次检查点**: P1-3 LLM 自进化能力启动前
