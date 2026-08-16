async def pipeline_evolution(payload: dict[str, Any]) -> CapabilityResult:
    """Based on historical runs and user feedback, generate pipeline parameter optimization proposals."""
    from datetime import datetime, timezone
    import uuid as _uuid
    import re as _re

    from ..core import db as db_module
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
            signals.append(
                f"Low rating feedback: rating={fb.rating}, tags=[{tag_str}]"
                + (f", correction={fb.correction[:80]}" if fb.correction else "")
            )

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

        # OOM detection
        if "OutOfMemory" in error_str or "out of memory" in error_str.lower() or "killed" in error_str.lower():
            signals.append(f"OOM pattern: {error_str[:200]}")
            actions.append("investigate_failure")
            suggested_mem = "16.Gb"
            m = _re.search(r"""max_memory[:\s]+['"]?([\d.]+)\.?([A-Za-z]*)['"]?""", params_str)
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

        # Timeout detection
        if ("timeout" in error_str.lower() or "timed out" in error_str.lower()
                or "exceeded" in error_str.lower()):
            signals.append(f"Timeout pattern: {error_str[:200]}")
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
            signals.append(f"Historical analysis: {len(completed_runs)} success, {len(failed_runs)} failed")

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
            signals.append(f"Historical analysis: {len(completed_runs)} successful runs")
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
                fb_text = (
                    low_feedbacks[0].correction if low_feedbacks else "none"
                )
                prompt = (
                    f"Analyze this bioinformatics pipeline failure. "
                    f"Pipeline: {current_run.pipeline_id}@{current_run.revision}. "
                    f"Params: {current_run.parameters}. "
                    f"Error: {current_run.error}. "
                    f"Feedback: {fb_text}. "
                    f"Format: [priority]: root_cause -> suggestion"
                )
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
    if signals:
        confidence = min(confidence + 0.02 * len(signals), 0.95)

    return CapabilityResult(
        status="completed",
        output=output,
        confidence=round(confidence, 2),
    )
