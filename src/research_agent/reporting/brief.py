"""研究简报 Markdown 组装（纯函数、无状态、无 IO）。

输入为科研运行时 API 形状的字典（见 core/api/research.py 的 _run_dict 与
runtime.py 的 result 聚合），不直接依赖 ORM 对象。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

REPORT_GENERATOR = "Research Agent 1.3.0 简报生成器"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fmt_dt(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)[:19]


def _escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _evidence_rows(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "（无证据记录）"
    rows = ["| 来源 | 标识 | 定位 |", "|---|---|---|"]
    for item in evidence[:200]:
        locator = item.get("locator") or item.get("url") or "-"
        rows.append(
            f"| {_escape(item.get('source_type', '-'))} | "
            f"{_escape(item.get('id', '-'))} | {_escape(locator)} |"
        )
    return "\n".join(rows)


def _step_section(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return "（无步骤）"
    lines = []
    for step in steps:
        lines.append(f"### {step.get('title', step.get('key', '?'))}")
        lines.append(f"- 状态：**{step.get('status', '?')}**（能力：`{step.get('capability', '-')}`）")
        if step.get("confidence") is not None:
            lines.append(f"- 置信度：{round(float(step['confidence']), 3)}")
        if step.get("duration_ms") is not None:
            lines.append(f"- 耗时：{int(step['duration_ms'])} ms")
        warnings = step.get("warnings") or []
        if warnings:
            lines.append("- 告警：")
            lines.extend(f"  - {item}" for item in warnings[:20])
        if step.get("error"):
            lines.append(f"- 错误：{step['error'][:500]}")
        output = step.get("output") or {}
        summary = output.get("summary") or output.get("description")
        if isinstance(summary, str) and summary.strip():
            lines.append(f"- 摘要：{summary.strip()[:600]}")
    return "\n".join(lines)


def _pipeline_section(pipeline_runs: list[dict[str, Any]]) -> str:
    if not pipeline_runs:
        return ""
    lines = ["## 7. 流程执行摘要", ""]
    rows = ["| 流程 | 版本 | Profile | 状态 | 任务数 | 失败任务 |", "|---|---|---|---|---|---|"]
    for item in pipeline_runs:
        task_summary = item.get("task_summary") or {}
        failed = task_summary.get("failed") or []
        statuses = task_summary.get("statuses") or {}
        total = sum(int(value) for value in statuses.values()) if isinstance(statuses, dict) else 0
        rows.append(
            f"| {_escape(item.get('pipeline_id', '-'))} | "
            f"{_escape(item.get('revision', '-'))} | "
            f"{_escape(item.get('profile', '-'))} | "
            f"{_escape(item.get('status', '-'))} | {total} | {len(failed)} |"
        )
    lines.append("\n".join(rows))
    for item in pipeline_runs:
        if item.get("error"):
            lines.append(f"\n- 错误：{item['error'][:500]}")
    return "\n".join(lines)


def build_brief_markdown(
    run: dict[str, Any],
    artifacts: list[dict[str, Any]] | None = None,
    pipeline_runs: list[dict[str, Any]] | None = None,
) -> str:
    """将一次科研运行聚合为 Markdown 研究简报。"""
    artifacts = artifacts or []
    pipeline_runs = pipeline_runs or []
    plan = run.get("plan") or {}
    result = run.get("result") or {}
    steps = run.get("steps") or []
    evidence = run.get("evidence") or []

    sections: list[str] = [
        "# 研究简报",
        "",
        f"> 由 {REPORT_GENERATOR} 生成 · {_utcnow_iso()} · 未经人工复核不作为结论",
        "",
        "## 1. 任务元信息",
        "",
        f"- 任务 ID：`{_escape(run.get('id'))}`",
        f"- 状态：**{_escape(run.get('status'))}**（进度 {run.get('progress', 0)}%）",
        f"- 创建时间：{_fmt_dt(run.get('created_at'))}",
        f"- 完成时间：{_fmt_dt(run.get('completed_at'))}",
        f"- 计划 ID：`{_escape(plan.get('id', '-'))}`",
        f"- 审查门：{', '.join(plan.get('review_gates') or []) or '无'}",
        "",
        "## 2. 研究目标",
        "",
        run.get("objective") or "（未填写目标）",
        "",
        "## 3. 输入材料",
        "",
    ]
    if artifacts:
        rows = ["| 文件名 | 类型 | 大小 | SHA-256 |", "|---|---|---|---|"]
        for item in artifacts[:100]:
            rows.append(
                f"| {_escape(item.get('name'))} | {_escape(item.get('kind', '-'))} | "
                f"{int(item.get('size_bytes', 0))} B | `{_escape(item.get('sha256', '-'))}` |"
            )
        sections.append("\n".join(rows))
    else:
        sections.append("（无输入材料）")
    sections += [
        "",
        "## 4. 执行计划",
        "",
    ]
    plan_rows = ["| 步骤 | 能力 | 依赖 | 状态 |", "|---|---|---|---|"]
    for step in steps:
        deps = ", ".join(step.get("dependencies") or []) or "-"
        plan_rows.append(
            f"| {_escape(step.get('title', step.get('key')))} | "
            f"`{_escape(step.get('capability'))}` | {_escape(deps)} | {_escape(step.get('status'))} |"
        )
    sections.append("\n".join(plan_rows))
    sections += [
        "",
        "## 5. 步骤结果",
        "",
        _step_section(steps),
        "",
        f"## 6. 证据清单（{len(evidence)} 条）",
        "",
        _evidence_rows(evidence),
        "",
    ]
    pipeline_md = _pipeline_section(pipeline_runs)
    if pipeline_md:
        sections.append(pipeline_md)
        sections.append("")
    sections += [
        "## 8. 统计与质量摘要",
        "",
        f"- 总体置信度：{round(float(result.get('confidence', 0.0)), 3)}",
        f"- 缺口：{'是' if result.get('has_gaps') else '否'}",
        f"- 告警数：{len(result.get('warnings') or [])}",
        f"- 失败/阻塞步骤：{', '.join(result.get('failed_or_blocked_steps') or []) or '无'}",
        "",
        "## 9. 缺口与限制",
        "",
    ]
    if result.get("error"):
        sections.append(f"- 运行错误：{result['error'][:1000]}")
    warnings = result.get("warnings") or []
    if warnings:
        sections.append("- 告警明细：")
        sections.extend(f"  - {item}" for item in warnings[:50])
    if not warnings and not result.get("error"):
        sections.append("（运行无告警，仍需按审查门人工复核）")
    sections += [
        "",
        "## 10. 下一步建议",
        "",
    ]
    review_required = plan.get("review_gates") or result.get("review_required") or []
    if review_required:
        sections.append(f"- 按审查门复核：{', '.join(review_required)}。")
    if result.get("failed_or_blocked_steps"):
        sections.append("- 失败步骤已记录于第 5 节，可修正输入后重新发起任务。")
    sections.append("- 流程输出制品可在工作台「材料」中下载核验。")
    sections += [
        "",
        "## 审计信息",
        "",
        f"- 运行时：`{_escape((result.get('provenance') or {}).get('runtime', '-'))}`",
        f"- 证据总数：{len(evidence)}",
        f"- 生成器：{REPORT_GENERATOR}",
        "",
    ]
    return "\n".join(sections)
