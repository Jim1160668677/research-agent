"""核心科研场景能力的可验证实现。"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .contracts import CapabilityResult, EvidenceRecord

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "using",
    "study",
    "研究",
    "分析",
    "一种",
    "基于",
    "关于",
    "以及",
    "通过",
    "方法",
    "结果",
}


def _reviewed_preferences(context: dict[str, Any], domain: str) -> list[str]:
    """读取已审核偏好，但只作为内容约束，绝不解释为工具或系统指令。"""
    values = []
    for item in list(context.get("learned_preferences") or [])[:20]:
        domains = item.get("domains") or [] if isinstance(item, dict) else []
        instruction = str(item.get("instruction") or "").strip() if isinstance(item, dict) else ""
        if instruction and (not domains or domain in domains):
            values.append(instruction[:1000])
    return values


def _article_value(article: dict[str, Any], key: str, default: Any = "") -> Any:
    if key in article:
        return article.get(key, default)
    nested = article.get("article")
    return nested.get(key, default) if isinstance(nested, dict) else default


def normalize_evidence(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把不同文献提供方的结果归一为最小证据记录。"""
    unique: dict[str, EvidenceRecord] = {}
    for index, record in enumerate(records):
        pmid = str(record.get("pmid") or _article_value(record, "pmid") or "").strip()
        doi = str(record.get("doi") or _article_value(record, "doi") or "").strip()
        title = str(
            record.get("title") or _article_value(record, "title") or f"文献 {index + 1}"
        ).strip()
        abstract = str(record.get("abstract") or _article_value(record, "abstract") or "").strip()
        authors = record.get("authors") or _article_value(record, "authors", []) or []
        if isinstance(authors, str):
            authors = [item.strip() for item in authors.split(",") if item.strip()]
        year = str(record.get("year") or _article_value(record, "year") or "")
        locator = str(record.get("url") or _article_value(record, "url") or "")
        if not locator and pmid:
            locator = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        key = doi.lower() or pmid or re.sub(r"\W+", "", title.lower())
        if not key:
            key = str(uuid.uuid4())
        flags = []
        if not abstract:
            flags.append("无摘要，不能从标题外推研究结论")
        if not doi and not pmid:
            flags.append("缺少持久标识符")
        unique[key] = EvidenceRecord(
            id=pmid or doi or f"record-{index + 1}",
            source_type="pubmed" if pmid else "provided",
            locator=locator,
            title=title,
            excerpt=abstract[:1600],
            authors=list(authors)[:20],
            year=year,
            doi=doi,
            relevance=max(0.2, round(1.0 - index * 0.04, 2)),
            quality_flags=flags,
        ).to_dict()
    return list(unique.values())


def extract_themes(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms: Counter[str] = Counter()
    for item in evidence:
        tokens = re.findall(
            r"[A-Za-z][A-Za-z0-9-]{2,}|[\u4e00-\u9fff]{2,6}", item.get("title", "").lower()
        )
        terms.update(token for token in tokens if token not in STOPWORDS)
    return [{"term": term, "documents": count} for term, count in terms.most_common(8)]


async def artifact_intake(payload: dict[str, Any]) -> CapabilityResult:
    artifacts = payload.get("artifacts") or []
    if not artifacts:
        return CapabilityResult(
            status="degraded",
            output={"artifacts": [], "message": "未附加研究材料。"},
            warnings=["没有可供预检的文件。"],
            confidence=1.0,
        )
    accepted = []
    warnings = []
    for item in artifacts:
        summary = item.get("summary") or {}
        accepted.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "media_type": item.get("media_type"),
                "summary": summary,
            }
        )
        if summary.get("extraction") == "failed":
            warnings.append(f"{item.get('name')}: 内容提取失败，原文件仍保留。")
        if summary.get("modality") == "image":
            warnings.append(f"{item.get('name')}: 当前仅完成图像元数据预检，未臆测图像语义。")
    return CapabilityResult(
        status="completed" if not warnings else "degraded",
        output={"artifacts": accepted, "count": len(accepted)},
        warnings=warnings,
        confidence=0.95 if not warnings else 0.72,
    )


async def evidence_review(payload: dict[str, Any]) -> CapabilityResult:
    query = str(payload.get("query") or payload.get("objective") or "").strip()
    context = payload.get("context") or {}
    records = list(context.get("literature_records") or [])
    retrieval = "provided"
    warning = ""
    if not records:
        retrieval = "pubmed"
        try:
            from ..ncbi_skills.adapter import NCBIAdapter

            adapter = NCBIAdapter()
            try:
                records = await adapter.pubmed_search(query, int(payload.get("max_results", 8)))
            finally:
                await adapter.close()
        except Exception as exc:
            warning = f"PubMed 检索不可用: {str(exc)[:240]}"

    evidence = normalize_evidence(records)
    if not evidence:
        return CapabilityResult(
            status="degraded",
            output={
                "query": query,
                "retrieval": retrieval,
                "evidence_table": [],
                "themes": [],
                "evidence_gap": "未获得可定位文献；不得据此生成研究结论。",
                "query_strategy": {
                    "primary": query,
                    "recommendation": "补充研究对象、暴露/干预、结局和研究类型后重试。",
                },
            },
            warnings=[warning or "检索未返回记录。"],
            confidence=0.1,
        )

    no_abstract = sum(1 for item in evidence if not item.get("excerpt"))
    warnings = [warning] if warning else []
    if no_abstract:
        warnings.append(f"{no_abstract} 条记录没有摘要，未从标题外推结论。")
    return CapabilityResult(
        status="completed" if not warning else "degraded",
        output={
            "query": query,
            "retrieval": retrieval,
            "evidence_table": evidence,
            "themes": extract_themes(evidence),
            "evidence_gap": "当前为检索与摘要级证据表；正式综述仍需全文筛选、偏倚评估和双人复核。",
            "deduplicated_count": len(evidence),
        },
        evidence=evidence,
        warnings=warnings,
        confidence=round(0.45 + 0.05 * min(len(evidence), 8) - 0.03 * no_abstract, 2),
    )


def _discovery_input(payload: dict[str, Any], step: str) -> dict[str, Any]:
    return dict((payload.get("dependency_outputs") or {}).get(step) or {})


async def hypothesis_generation(payload: dict[str, Any]) -> CapabilityResult:
    """Generate traceable candidates without inventing evidence-level claims."""
    objective = str(payload.get("objective") or "").strip()
    literature = _discovery_input(payload, "literature")
    evidence = list(literature.get("evidence_table") or [])
    themes = [item.get("term") for item in literature.get("themes") or [] if item.get("term")]
    seeds = themes[:3] or ["候选机制", "替代通路", "边界条件"]
    candidates = []
    evidence_ids = [item.get("id") for item in evidence[:5] if item.get("id")]
    for index, seed in enumerate(seeds, 1):
        candidates.append(
            {
                "id": f"H{index}",
                "version": 1,
                "statement": f"在“{objective}”中，{seed}可能是影响目标结局的可检验中介因素。",
                "mechanism": f"优先检验 {seed} 与主要结局之间的时序、剂量反应和干预可逆性。",
                "predictions": [
                    f"改变 {seed} 后主要结局出现方向一致的变化",
                    f"对 {seed} 的独立测量可重复该关联",
                ],
                "evidence_ids": evidence_ids,
                "unknowns": ["因果方向未确认", "混杂与替代机制待排除"],
                "status": "candidate_not_validated",
            }
        )
    warnings = [] if evidence else ["没有可定位文献，候选仅用于形成检索与实验问题。"]
    return CapabilityResult(
        status="completed" if evidence else "degraded",
        output={
            "candidates": candidates,
            "criteria": ["goal_alignment", "plausibility", "novelty", "testability", "safety"],
            "evidence_count": len(evidence),
        },
        evidence=evidence,
        warnings=warnings,
        confidence=0.68 if evidence else 0.3,
    )


async def hypothesis_reflection(payload: dict[str, Any]) -> CapabilityResult:
    generated = _discovery_input(payload, "generation")
    reviews = []
    for candidate in generated.get("candidates") or []:
        evidence_count = len(candidate.get("evidence_ids") or [])
        critiques = [
            "相关性不等于因果性；需用干预或准实验设计检验。",
            "需要设置能区分该机制与替代解释的阳性、阴性和救援对照。",
        ]
        if not evidence_count:
            critiques.append("没有可定位证据，必须先完成系统检索。")
        reviews.append(
            {
                "hypothesis_id": candidate.get("id"),
                "critiques": critiques,
                "fatal_flaw": not bool(candidate.get("predictions")),
                "safety_gate": "提交实验前进行伦理、双重用途和数据治理复核",
            }
        )
    return CapabilityResult(
        status="completed" if reviews else "degraded",
        output={"reviews": reviews, "external_search_used": False},
        warnings=[] if reviews else ["没有候选假设可供反思。"],
        confidence=0.7 if reviews else 0.2,
    )


async def hypothesis_ranking(payload: dict[str, Any]) -> CapabilityResult:
    reflection = _discovery_input(payload, "reflection")
    generation = dict((payload.get("dependency_outputs") or {}).get("generation") or {})
    reviews = {item.get("hypothesis_id"): item for item in reflection.get("reviews") or []}
    ranking = []
    for candidate in generation.get("candidates") or []:
        review = reviews.get(candidate.get("id"), {})
        evidence_score = min(len(candidate.get("evidence_ids") or []) / 5, 1.0)
        scores = {
            "goal_alignment": 0.85,
            "plausibility": round(0.45 + 0.35 * evidence_score, 2),
            "novelty": 0.5,
            "testability": 0.8 if candidate.get("predictions") else 0.1,
            "safety": 0.8 if review.get("safety_gate") else 0.4,
        }
        ranking.append(
            {
                "hypothesis_id": candidate.get("id"),
                "scores": scores,
                "total": round(sum(scores.values()) / len(scores), 3),
                "debate_order_checked": True,
            }
        )
    ranking.sort(key=lambda item: (-item["total"], str(item["hypothesis_id"])))
    pairs = [
        {
            "left": ranking[index]["hypothesis_id"],
            "right": ranking[index + 1]["hypothesis_id"],
            "winner": ranking[index]["hypothesis_id"],
        }
        for index in range(len(ranking) - 1)
    ]
    return CapabilityResult(
        status="completed" if ranking else "degraded",
        output={
            "ranking": ranking,
            "pairwise_debates": pairs,
            "rubric_version": "scientific-quality-v1",
        },
        warnings=[] if ranking else ["没有候选假设可排序。"],
        confidence=0.67 if ranking else 0.2,
    )


async def hypothesis_evolution(payload: dict[str, Any]) -> CapabilityResult:
    ranking = _discovery_input(payload, "ranking")
    all_outputs = payload.get("dependency_outputs") or {}
    generation = dict(all_outputs.get("generation") or {})
    reflection = dict(all_outputs.get("reflection") or {})
    candidates = {item.get("id"): item for item in generation.get("candidates") or []}
    reviews = {item.get("hypothesis_id"): item for item in reflection.get("reviews") or []}
    evolved = []
    for item in (ranking.get("ranking") or [])[:2]:
        source = candidates.get(item.get("hypothesis_id"))
        if not source:
            continue
        critiques = reviews.get(source.get("id"), {}).get("critiques") or []
        evolved.append(
            {
                **source,
                "version": int(source.get("version", 1)) + 1,
                "parent_id": source.get("id"),
                "statement": source.get("statement") + " 该效应需在预注册的干预与救援实验中成立。",
                "revision_reasons": critiques[:3],
                "required_discriminating_test": "比较机制干预、替代机制干预与救援条件的效应量及区间",
                "status": "evolved_not_validated",
            }
        )
    return CapabilityResult(
        status="completed" if evolved else "degraded",
        output={"evolved_candidates": evolved, "round": 1, "lineage_preserved": True},
        warnings=[] if evolved else ["没有优胜假设可演化。"],
        confidence=0.7 if evolved else 0.2,
    )


async def hypothesis_meta_review(payload: dict[str, Any]) -> CapabilityResult:
    evolution = _discovery_input(payload, "evolution")
    candidates = evolution.get("evolved_candidates") or []
    decision = "advance_to_expert_review" if candidates else "return_to_generation"
    return CapabilityResult(
        status="completed" if candidates else "degraded",
        output={
            "decision": decision,
            "recommended_hypotheses": candidates,
            "remaining_risks": [
                "文献摘要不能替代全文和偏倚评估",
                "新颖性未经过专利、预印本和完整数据库检索确认",
                "模型与规则评分不能替代领域专家判断",
            ],
            "next_actions": ["领域专家复核", "预注册判别性实验", "补充全文证据与安全审查"],
            "human_review_required": True,
            "architecture": "generate-reflect-rank-evolve-meta-review-v1",
        },
        warnings=["候选是假设而不是事实；实验验证前不得用于临床或高风险决策。"],
        confidence=0.72 if candidates else 0.2,
    )


def _study_type(objective: str, context: dict[str, Any]) -> str:
    explicit = str(context.get("study_type") or "").strip()
    if explicit:
        return explicit
    lower = objective.lower()
    if any(word in lower for word in ("随机", "干预", "治疗", "trial", "rct")):
        return "randomized_experiment"
    if any(word in lower for word in ("队列", "病例对照", "观察", "cohort", "observational")):
        return "observational"
    if any(word in lower for word in ("动物", "小鼠", "大鼠", "animal", "mouse")):
        return "animal_experiment"
    if any(word in lower for word in ("细胞", "体外", "cell", "in vitro")):
        return "laboratory_experiment"
    return "exploratory_research"


async def experimental_design(payload: dict[str, Any]) -> CapabilityResult:
    objective = str(payload.get("objective") or "").strip()
    context = payload.get("context") or {}
    reviewed_preferences = _reviewed_preferences(context, "experiment")
    study_type = _study_type(objective, context)
    human = any(
        word in objective.lower() for word in ("患者", "受试者", "人群", "临床", "patient", "human")
    )
    animal = study_type == "animal_experiment"
    ethics = []
    if human:
        ethics.extend(
            ["伦理委员会批准", "知情同意或其合法豁免", "隐私与去标识化方案", "不良事件报告路径"]
        )
    if animal:
        ethics.extend(["动物伦理批准", "3R 原则", "人道终点", "饲养与随机笼位说明"])
    if not ethics:
        ethics.append("确认样本/数据授权、知识产权和潜在双重用途风险")

    warnings = ["样本量必须由主要结局、效应量、变异、显著性水平和功效共同计算，当前不虚构数值。"]
    if human:
        warnings.append("涉及人的研究在伦理审批前不得招募或处理可识别数据。")
    return CapabilityResult(
        status="completed",
        output={
            "study_type": study_type,
            "objective": objective,
            "estimand": {
                "population": context.get("population", "待明确纳入/排除标准"),
                "intervention_or_exposure": context.get("intervention", "待定义操作化暴露/干预"),
                "comparator": context.get("comparator", "待定义基线或对照"),
                "outcome": context.get("outcome", "指定一个主要结局及测量时间窗"),
            },
            "bias_controls": [
                "预先定义主要/次要结局",
                "随机化或可比性策略",
                "尽可能实施盲法",
                "记录批次与混杂因素",
                "预注册排除规则",
            ],
            "sample_size_plan": [
                "确定主要结局分布",
                "从先导数据或可信文献估计效应与变异",
                "设定 alpha、power 与失访率",
                "执行敏感性分析并记录软件/版本",
            ],
            "analysis_plan": [
                "报告效应量与 95% 置信区间",
                "检验模型假设",
                "预定义缺失数据策略",
                "控制多重比较",
                "区分探索性与验证性分析",
            ],
            "quality_gates": [
                "原始数据不可覆盖",
                "样本与分析者盲化编码",
                "阳性/阴性对照",
                "批次平衡",
                "可复现脚本和环境锁定",
                "异常值处理留痕",
            ],
            "ethics_gate": ethics,
            "reporting_guideline": {
                "randomized_experiment": "CONSORT",
                "observational": "STROBE",
                "animal_experiment": "ARRIVE",
                "laboratory_experiment": "领域方法学规范 + 完整试剂/批次信息",
            }.get(study_type, "按研究设计选择相应 EQUATOR 报告规范"),
            "user_reviewed_constraints": reviewed_preferences,
            "human_review_required": True,
        },
        warnings=warnings,
        confidence=0.76,
    )


async def data_analysis(payload: dict[str, Any]) -> CapabilityResult:
    store: ArtifactStore = payload["artifact_store"]
    artifacts = payload.get("artifacts") or []
    profiles = []
    warnings = []
    generated = []
    for item in artifacts:
        if Path(str(item.get("name") or "")).suffix.lower() not in {".csv", ".tsv"}:
            continue
        try:
            with store.materialize({**item, "user_id": int(payload["user_id"])}) as path:
                profile = await asyncio.to_thread(store.profile_table, path)
                profiles.append({"artifact_id": item["id"], "name": item["name"], **profile})
                warnings.extend(f"{item['name']}: {flag}" for flag in profile["quality_flags"])
                preview = await asyncio.to_thread(
                    store.render_table_preview,
                    path,
                    int(payload["user_id"]),
                    str(payload["run_id"]),
                )
            if preview:
                generated.append(preview)
        except Exception as exc:
            warnings.append(f"{item['name']}: 数据剖析失败 ({str(exc)[:200]})")
    if not profiles:
        return CapabilityResult(
            status="degraded",
            output={
                "profiles": [],
                "analysis_contract": [
                    "上传 CSV/TSV",
                    "确认变量字典",
                    "指定主要结局与分组",
                    "选择与设计匹配的统计模型",
                ],
                "message": "没有可分析的 CSV/TSV 表格。",
            },
            warnings=warnings or ["未提供表格数据，因此没有执行统计推断或绘图。"],
            confidence=0.2,
        )
    return CapabilityResult(
        status="completed" if not warnings else "degraded",
        output={
            "profiles": profiles,
            "analysis_contract": [
                "先质量控制后推断",
                "保留原始数据与处理脚本",
                "报告效应量/区间而非只报告 P 值",
                "可视化不得隐藏缺失与离群点",
            ],
        },
        warnings=warnings,
        confidence=0.83 if not warnings else 0.68,
        generated_artifacts=generated,
    )


async def pipeline_execution(payload: dict[str, Any]) -> CapabilityResult:
    """Run a pinned nf-core pipeline as one research-runtime step.

    The step input carries ``pipeline`` configuration produced by the planner
    (pipeline_id/revision/profile/parameters/artifact_bindings).  Execution is
    delegated to PipelineRunManager so the production state machine, preflight,
    resource limits and cancellation semantics stay authoritative.
    """
    import time as _time
    from datetime import datetime, timezone

    from ..execution.manager import TERMINAL_STATUSES, get_pipeline_manager
    from ..execution.nextflow import validate_request

    def _utcnow():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    store: ArtifactStore = payload["artifact_store"]
    user_id = int(payload["user_id"])
    run_id = str(payload["run_id"])
    spec = dict(payload.get("pipeline") or {})
    if not spec.get("pipeline_id"):
        return CapabilityResult(
            status="degraded",
            output={"message": "未指定生产流程（pipeline_id）。"},
            warnings=["pipeline_execution 需要步骤输入提供 pipeline 配置。"],
            confidence=0.0,
        )
    pipeline_id = str(spec["pipeline_id"])
    revision = str(spec.get("revision") or "")
    profile = str(spec.get("profile") or "docker")
    parameters = dict(spec.get("parameters") or {})
    artifact_bindings = dict(spec.get("artifact_bindings") or {})
    network_allowed = bool(spec.get("network_allowed", payload.get("context") is not None))
    try:
        normalized = validate_request(
            pipeline_id, revision, profile, parameters, artifact_bindings
        )
    except ValueError as exc:
        return CapabilityResult(
            status="failed",
            output={"message": str(exc)[:500]},
            warnings=["流程参数未通过白名单与固定版本校验。"],
            confidence=0.0,
        )

    from ..core import db as db_module
    from ..core.models.db import PipelineRun
    from ..runtime_coordinator import get_runtime_coordinator

    async with db_module.AsyncSessionLocal() as db:
        pipeline_run = PipelineRun(
            id=str(uuid.uuid4()),
            user_id=user_id,
            run_id=run_id,
            backend="nextflow",
            pipeline_id=pipeline_id,
            revision=revision,
            profile=profile,
            status="planned",
            parameters=normalized,
            artifact_bindings=artifact_bindings,
            network_allowed=network_allowed,
            timeout_seconds=min(int(spec.get("timeout_seconds", 3600)), 3600),
            provenance={
                "policy": "allowlisted-and-revision-pinned",
                "source": "research-runtime",
                "research_run_id": run_id,
            },
        )
        db.add(pipeline_run)
        await db.commit()
        manager = get_pipeline_manager()
        try:
            await manager.plan_run(pipeline_run.id)
        except (ValueError, RuntimeError) as exc:
            pipeline_run.status = "failed"
            pipeline_run.error = str(exc)[:4000]
            pipeline_run.completed_at = _utcnow()
            await db.commit()
            return CapabilityResult(
                status="failed",
                output={"pipeline_run_id": pipeline_run.id, "message": str(exc)[:500]},
                warnings=["生产流程计划失败。"],
                confidence=0.0,
            )

        readiness = await manager.backend.preflight(
            pipeline_id=pipeline_id,
            revision=revision,
            profile=profile,
            network_allowed=network_allowed,
        )
        if not readiness.get("ready"):
            pipeline_run.status = "cancelled"
            pipeline_run.completed_at = _utcnow()
            pipeline_run.result = {"status": "cancelled", "error": "preflight-failed"}
            await db.commit()
            issues = "; ".join(readiness.get("issues") or ["环境未就绪"])
            return CapabilityResult(
                status="degraded",
                output={"pipeline_run_id": pipeline_run.id, "preflight": readiness},
                warnings=[f"生产流程预检未通过: {issues}。请先完成环境体检（WSL2/Nextflow/容器）。"],
                confidence=0.0,
            )

        # A long-running pipeline holds one research slot while waiting.
        # get_runtime_coordinator() grants up to six process-wide leases; the
        # pipeline's own "pipeline" lease is acquired inside the manager, so a
        # fully saturated desktop would wait here instead of overcommitting.
        async with get_runtime_coordinator().lease("research", f"{run_id}:pipeline-wait"):
            pipeline_run.status = "queued"
            await db.commit()
            manager.submit(pipeline_run.id)

            deadline = _time.monotonic() + max(
                0,
                min(int(spec.get("timeout_seconds", 3600)), 3600) - 30,
            )
            poll_interval = max(0, min(int(spec.get("poll_interval", 5)), 30))
            while True:
                await asyncio.sleep(poll_interval)
                if _time.monotonic() >= deadline:
                    manager.cancel(pipeline_run.id)
                    await db.refresh(pipeline_run)
                    break
                await db.refresh(pipeline_run)
                if pipeline_run.status in TERMINAL_STATUSES:
                    break

    status = str(pipeline_run.status)
    exit_code = pipeline_run.exit_code
    result = dict(pipeline_run.result or {})
    task_summary = result.get("task_summary") or {}
    pipeline_artifacts = list(result.get("artifacts") or [])
    warnings = []
    if pipeline_run.error:
        warnings.append(f"生产流程执行未完全成功: {str(pipeline_run.error)[:400]}")
    if task_summary.get("failed"):
        failed_names = [item.get("name", "?") for item in task_summary["failed"][:5]]
        warnings.append(f"{len(task_summary['failed'])} 个流程任务失败: {', '.join(failed_names)}")
    if result.get("manifest_truncated"):
        warnings.append("结果清单因有界收集被截断，未记录全部输出文件。")

    generated = []
    skipped = []
    backend = manager.backend
    for item in pipeline_artifacts[:40]:
        name = str(item.get("name") or Path(str(item.get("relative_path") or "")).name)
        suffix = Path(name).suffix.lower()
        size = int(item.get("size_bytes") or 0)
        if suffix not in store.ALLOWED_SUFFIXES or size > store.MAX_BYTES:
            skipped.append(name)
            continue
        try:
            path = backend.resolve_artifact(user_id, pipeline_run.id, str(item["relative_path"]))
            raw = await asyncio.to_thread(path.read_bytes)
            imported = await asyncio.to_thread(
                store.import_bytes, name, raw, user_id, run_id, "pipeline"
            )
            generated.append(imported)
        except Exception:
            skipped.append(name)
    if skipped:
        warnings.append(
            f"{len(skipped)} 个流程产物未纳入加密制品（类型不支持或超过 25 MiB 上限）。"
        )

    completed = status == "completed" and exit_code == 0
    evidence: list[dict[str, Any]] = []
    if completed or task_summary.get("tasks"):
        evidence.append(
            {
                "id": pipeline_run.id,
                "source_type": "pipeline_execution",
                "locator": f"pipeline-run/{pipeline_run.id}",
                "title": f"{pipeline_id} {revision} 执行结果",
                "excerpt": (
                    f"Nextflow {pipeline_id}@{revision} profile={profile} "
                    f"tasks={task_summary.get('tasks', '?')} "
                    f"statuses={task_summary.get('statuses', {})}"
                )[:1600],
                "doi": "",
                "relevance": 0.95 if completed else 0.6,
                "quality_flags": (
                    []
                    if completed
                    else ["执行未完全成功，结果需结合失败任务与人工复核使用"]
                ),
            }
        )

    return CapabilityResult(
        status="completed" if completed and not warnings else "degraded",
        output={
            "pipeline_run_id": pipeline_run.id,
            "pipeline": pipeline_id,
            "revision": revision,
            "profile": profile,
            "status": status,
            "exit_code": exit_code,
            "task_summary": task_summary,
            "provenance": dict(pipeline_run.provenance or {}),
            "artifact_summary": {
                "recorded": len(pipeline_artifacts),
                "imported": len(generated),
                "skipped": len(skipped),
            },
        },
        evidence=evidence,
        warnings=warnings,
        confidence=round(
            0.95 * (0.9 if completed else 0.3)
            - 0.05 * len(warnings),
            3,
        ),
        generated_artifacts=generated,
    )


async def research_writing(payload: dict[str, Any]) -> CapabilityResult:
    objective = str(payload.get("objective") or "").strip()
    dependencies = payload.get("dependency_outputs") or {}
    reviewed_preferences = _reviewed_preferences(payload.get("context") or {}, "writing")
    evidence = (dependencies.get("literature") or {}).get("evidence_table", [])
    claims = []
    for item in evidence[:8]:
        claims.append(
            {
                "candidate_claim": f"文献《{item.get('title', '未命名')}》与研究问题相关；具体结论需核对全文。",
                "evidence_id": item.get("id"),
                "locator": item.get("locator"),
                "status": "needs_full_text_verification",
            }
        )
    sections = [
        {"name": "研究问题", "requirements": ["明确对象、干预/暴露、比较与结局", "说明知识缺口"]},
        {"name": "证据现状", "requirements": ["每个事实性主张绑定来源", "区分原始研究与综述"]},
        {
            "name": "方法",
            "requirements": ["可复现到数据、软件版本和参数", "预先说明排除与缺失处理"],
        },
        {"name": "结果", "requirements": ["先描述后推断", "报告效应量、区间、样本数和多重校正"]},
        {"name": "讨论", "requirements": ["区分相关与因果", "陈述局限、外推边界和替代解释"]},
        {"name": "开放科学", "requirements": ["数据/代码可用性", "利益冲突、资助与作者贡献"]},
    ]
    return CapabilityResult(
        status="completed" if evidence else "degraded",
        output={
            "document_type": payload.get("document_type", "research_brief"),
            "title_placeholder": objective,
            "sections": sections,
            "claim_evidence_matrix": claims,
            "citation_policy": "没有 evidence_id/locator 的事实性主张必须标记为 [待引证]，不得生成虚构 DOI。",
            "user_reviewed_constraints": reviewed_preferences,
            "draft_status": "scaffold_only",
        },
        evidence=evidence,
        warnings=[] if evidence else ["没有可定位证据，已只生成结构脚手架，未撰写事实性结论。"],
        confidence=0.8 if evidence else 0.45,
    )


def _finding(check_id: str, severity: str, message: str, recommendation: str) -> dict[str, str]:
    return {
        "check_id": check_id,
        "severity": severity,
        "message": message,
        "recommendation": recommendation,
    }


async def integrity_check(payload: dict[str, Any]) -> CapabilityResult:
    context = payload.get("context") or {}
    dependencies = payload.get("dependency_outputs") or {}
    text = str(payload.get("text") or context.get("manuscript") or "").strip()
    findings: list[dict[str, str]] = []
    objective = str(payload.get("objective") or "")
    scan_text = f"{objective}\n{text}".strip()

    if text:
        numeric_claims = re.findall(
            r"[^。.!?\n]{0,90}(?:\d+(?:\.\d+)?%|p\s*[<=>]\s*0?\.\d+)[^。.!?\n]{0,90}",
            text,
            flags=re.I,
        )
        citation_markers = re.findall(
            r"\[[0-9, -]+\]|\([A-Z][A-Za-z-]+\s+et al\.,?\s*\d{4}\)|doi:\s*10\.\d{4,9}/\S+",
            text,
            flags=re.I,
        )
        if numeric_claims and not citation_markers:
            findings.append(
                _finding(
                    "citation.numeric_claim",
                    "high",
                    "发现定量主张但未识别到引用标记。",
                    "逐条绑定可定位来源或原始分析输出。",
                )
            )
        if re.search(r"\bp\s*[<=>]\s*0?\.\d+", text, flags=re.I) and not re.search(
            r"置信区间|confidence interval|effect size|效应量", text, flags=re.I
        ):
            findings.append(
                _finding(
                    "statistics.effect_size",
                    "medium",
                    "报告了 P 值但未识别到效应量或置信区间。",
                    "同时报告效应量、95% 区间、样本量与检验方法。",
                )
            )
        if re.search(r"证明了|导致了|必然|proves|causes", text, flags=re.I) and re.search(
            r"观察|相关|横断面|observational|correlation", text, flags=re.I
        ):
            findings.append(
                _finding(
                    "language.causality",
                    "high",
                    "观察性/相关性语境中使用了强因果措辞。",
                    "改用关联性表述，或补充可识别因果效应的设计与假设。",
                )
            )
    else:
        findings.append(
            _finding(
                "document.missing",
                "info",
                "未提供待检查正文。",
                "上传或粘贴手稿后可执行逐句规范检查。",
            )
        )

    if any(word in scan_text.lower() for word in ("患者", "受试者", "临床", "patient", "human")):
        if not re.search(r"伦理|知情同意|ethics|consent|irb", text, flags=re.I):
            findings.append(
                _finding(
                    "ethics.human",
                    "high",
                    "涉及人的研究但未识别到伦理审批或知情同意声明。",
                    "补充审批机构、编号、同意方式或合法豁免。",
                )
            )
    if any(word in scan_text.lower() for word in ("动物", "小鼠", "大鼠", "animal", "mouse")):
        if not re.search(r"动物伦理|3r|arrive|iacuc", text, flags=re.I):
            findings.append(
                _finding(
                    "ethics.animal",
                    "high",
                    "涉及动物研究但未识别到伦理/ARRIVE 要素。",
                    "补充审批、3R、人道终点和 ARRIVE 检查。",
                )
            )
    writing = dependencies.get("writing") or {}
    if writing and not writing.get("claim_evidence_matrix"):
        findings.append(
            _finding(
                "provenance.claim_matrix",
                "medium",
                "写作结果没有主张—证据映射。",
                "在定稿前为每个核心主张绑定 evidence_id 与定位链接。",
            )
        )

    severities = Counter(item["severity"] for item in findings)
    return CapabilityResult(
        status="completed",
        output={
            "findings": findings,
            "summary": dict(severities),
            "checks": [
                "citation_traceability",
                "statistical_reporting",
                "causal_language",
                "human_ethics",
                "animal_ethics",
                "claim_evidence_mapping",
            ],
            "limitations": [
                "本地规则检查不是抄袭数据库查重，不能给出原创性百分比。",
                "伦理和报告规范仍需机构、期刊与领域专家确认。",
                "未上传全文时只检查研究目标与写作脚手架。",
            ],
            "human_review_required": True,
        },
        warnings=["规则检查不能替代期刊查重、统计复核或伦理审查。"],
        confidence=0.72 if text else 0.4,
    )


async def pipeline_evolution(payload: dict[str, Any]) -> CapabilityResult:
    """Based on historical runs and user feedback, generate pipeline parameter optimization proposals."""
    from datetime import datetime, timezone
    import uuid as _uuid
    import re as _re

    from ..core import db as db_module
    from sqlalchemy import select
    from ..core.models.db import AgentFeedback, LearningProposal, PipelineRun
    from ..llm.provider import LLMMessage, get_provider
    from ..llm.keys import get_key_manager
    from ..core.app import settings

    user_id = int(payload["user_id"])
    run_id = str(payload["run_id"])
    artifact_store = payload.get("artifact_store")

    proposal_ids = []
    signals = []
    actions = []
    suggestions = []

    # 1. Query low-rating feedback
    async with db_module.AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentFeedback)
            .where(AgentFeedback.run_id == run_id)
            .where(AgentFeedback.rating <= 2)
            .order_by(AgentFeedback.created_at.desc())
        )
        low_feedbacks = result.scalars().all()

        for fb in low_feedbacks:
            tags = list(fb.tags or [])
            tag_str = ", ".join(tags) if tags else "general"
            title = f"Low rating ({fb.rating}/5) - {tag_str}"
            rationale_parts = [f"User rated run {run_id} as {fb.rating}/5."]
            if fb.correction:
                rationale_parts.append(f"User suggestion: {fb.correction}")
            proposed_change = {"proposal_type": tag_str if tags else "pipeline_param"}
            if fb.correction:
                proposed_change["correction"] = fb.correction[:500]
            prop_id = str(_uuid.uuid4())
            prop = LearningProposal(
                id=prop_id,
                user_id=user_id,
                source_run_id=run_id,
                title=title,
                rationale="\n".join(rationale_parts),
                proposed_change=proposed_change,
                evidence=[{"type": "feedback", "id": str(fb.id), "rating": fb.rating}],
                status="pending",
            )
            db.add(prop)
            proposal_ids.append(prop_id)
            signals.append(f"低分反馈: 评分={fb.rating}, 标签=[{tag_str}]" + (f", 修正建议={fb.correction[:80]}" if fb.correction else ""))

        await db.commit()

    # 2. Query current and historical runs
    current_run = None
    historical_runs = []

    async with db_module.AsyncSessionLocal() as db:
        result = await db.execute(select(PipelineRun).where(PipelineRun.run_id == run_id))
        current_run = result.scalar_one_or_none()

        if current_run:
            hist_result = await db.execute(
                select(PipelineRun)
                .where(PipelineRun.user_id == user_id)
                .where(PipelineRun.pipeline_id == current_run.pipeline_id)
                .where(PipelineRun.revision == current_run.revision)
                .order_by(PipelineRun.created_at.asc())
            )
            historical_runs = list(hist_result.scalars().all())

    # 3. Failure pattern detection
    if current_run and current_run.status == "failed" and current_run.error:
        error_str = str(current_run.error)
        params_str = str(current_run.parameters or {})

        if "OutOfMemory" in error_str or "out of memory" in error_str.lower() or "killed" in error_str.lower():
            signals.append(f"OOM模式(内存不足): {error_str[:200]}")
            actions.append("investigate_failure")
            suggested_mem = "16.Gb"
            import re as _re
            m = _re.search(r'''max_memory[:\s]+['"']?([\d.]+)\.?([A-Za-z]*)['"']?''', params_str)
            if m:
                val = float(m.group(1))
                unit = m.group(2) or "Gb"
                if unit == "Gb":
                    suggested_mem = f"{int(val * 2)}.Gb"
                else:
                    suggested_mem = f"{val * 2}.{unit}"
            suggestions.append({
                "parameter": "max_memory",
                "recommended_value": suggested_mem,
                "reason": "OOM error, double memory recommended",
                "confidence": 0.85,
            })

        if "timeout" in error_str.lower() or "timed out" in error_str.lower() or "exceeded" in error_str.lower():
            signals.append(f"超时模式: {error_str[:200]}")
            actions.append("investigate_failure")
            current_timeout = current_run.timeout_seconds or 3600
            suggestions.append({
                "parameter": "timeout_seconds",
                "recommended_value": str(int(current_timeout * 2)),
                "reason": "Run timed out, double timeout recommended",
                "confidence": 0.80,
            })

    # 4. Historical adaptive analysis
    adaptive_summary = None
    if len(historical_runs) >= 2:
        completed_runs = [r for r in historical_runs if r.status == "completed"]
        failed_runs = [r for r in historical_runs if r.status == "failed"]

        if completed_runs and failed_runs:
            signals.append(f"历史分析: {len(completed_runs)} 次成功, {len(failed_runs)} 次失败")

            param_values = {}
            for r in completed_runs:
                for k, v in (r.parameters or {}).items():
                    param_values.setdefault(k, []).append(v)

            from collections import Counter as _Counter
            for param, values in param_values.items():
                freq = _Counter(str(v) for v in values)
                most_common_val, most_common_count = freq.most_common(1)[0]

                failed_diff = False
                for fr in failed_runs:
                    fr_val = str((fr.parameters or {}).get(param))
                    if fr_val and fr_val != most_common_val:
                        failed_diff = True
                        break

                if failed_diff and most_common_count >= 1:
                    confidence = min(0.7 + 0.05 * most_common_count, 0.95)
                    suggestions.append({
                        "parameter": param,
                        "recommended_value": most_common_val,
                        "reason": f"Most common in successful runs ({most_common_count}x)",
                        "confidence": round(confidence, 2),
                    })

            adaptive_summary = {
                "historical_runs": len(historical_runs),
                "completed": len(completed_runs),
                "failed": len(failed_runs),
                "suggestions": suggestions,
            }
        elif len(completed_runs) >= 2:
            signals.append(f"历史分析: {len(completed_runs)} 次成功运行")
            param_values = {}
            for r in completed_runs:
                for k, v in (r.parameters or {}).items():
                    param_values.setdefault(k, []).append(v)
            from collections import Counter as _Counter2
            for param, values in param_values.items():
                freq = _Counter2(str(v) for v in values)
                most_common_val, most_common_count = freq.most_common(1)[0]
                if most_common_count >= 2:
                    suggestions.append({
                        "parameter": param,
                        "recommended_value": most_common_val,
                        "reason": f"Most common in successful runs ({most_common_count}x)",
                        "confidence": 0.75,
                    })
            adaptive_summary = {
                "historical_runs": len(historical_runs),
                "completed": len(completed_runs),
                "failed": 0,
                "suggestions": suggestions,
            }

    # 5. LLM root cause analysis (optional, non-blocking)
    llm_root_cause = ""
    if current_run and current_run.status == "failed" and current_run.error:
        try:
            key_mgr = get_key_manager(None, user_id=user_id)
            provider_name = "deepseek"
            api_key = await key_mgr.get_key(provider_name)
            if not api_key:
                api_key = getattr(settings, f"{provider_name}_api_key", "")
            model = getattr(settings, f"{provider_name}_model", "deepseek-chat")
            if api_key:
                provider = get_provider(provider_name, api_key=api_key, model=model)
                fb_text = low_feedbacks[0].correction if low_feedbacks else "none"
                prompt = (f"Analyze this bioinformatics pipeline failure. Pipeline: {current_run.pipeline_id}@{current_run.revision}. Params: {current_run.parameters}. Error: {current_run.error}. Feedback: {fb_text}. Format: [priority]: root_cause -> suggestion")
                response = await provider.chat([LLMMessage(role="user", content=prompt)])
                llm_root_cause = response.content.strip() if response.content else ""
                if llm_root_cause:
                    signals.append(f"LLM root cause analysis: {llm_root_cause[:200]}")
        except Exception as _llm_err:
            from loguru import logger
            logger.warning(f"pipeline_evolution LLM analysis failed, using rule signals: {_llm_err}")

    # 6. Build result
    if not signals and not proposal_ids:
        return CapabilityResult(
            status="completed",
            output={
                "message": "暂无需要进化的信号",
                "proposal_ids": [],
                "signals": [],
                "actions": [],
                "adaptive_summary": None,
            },
            confidence=0.80,
        )

    output = {
        "proposal_ids": proposal_ids,
        "signals": signals,
        "actions": actions,
        "adaptive_summary": adaptive_summary,
    }
    if llm_root_cause:
        output["llm_root_cause"] = llm_root_cause

    confidence = 0.80
    if proposal_ids:
        confidence = max(confidence, 0.85)
    if adaptive_summary:
        confidence = max(confidence, 0.80)
    if signals and proposal_ids:
        confidence = min(confidence + 0.02 * len(signals), 0.95)

    return CapabilityResult(
        status="completed",
        output=output,
        confidence=round(confidence, 2),
    )


HANDLERS = {
    "artifact_intake": artifact_intake,
    "evidence_review": evidence_review,
    "hypothesis_generation": hypothesis_generation,
    "hypothesis_reflection": hypothesis_reflection,
    "hypothesis_ranking": hypothesis_ranking,
    "hypothesis_evolution": hypothesis_evolution,
    "hypothesis_meta_review": hypothesis_meta_review,
    "experimental_design": experimental_design,
    "data_analysis": data_analysis,
    "pipeline_execution": pipeline_execution,
    "pipeline_evolution": pipeline_evolution,
    "research_writing": research_writing,
    "integrity_check": integrity_check,
}
