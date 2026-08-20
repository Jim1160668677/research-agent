"""科研工作台 API：计划、运行、材料、反馈与受控学习。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...audit_chain import append_audit
from ...reporting.brief import build_brief_markdown
from ...reporting.rocrate import generate_rocrate
from ...research.param_predictor import predict_for_new_run, estimate_sample_sufficiency
from ...research.artifacts import ArtifactError, public_artifact
from ...research.contracts import list_capabilities
from ...research.manager import get_run_manager
from ...research.planner import ResearchPlanner
from ..auth import get_current_user
from ..db import get_db
from ..models.db import (
    AgentFeedback,
    LearningProposal,
    PipelineRun,
    ResearchArtifact,
    ResearchRun,
    ResearchRunStep,
    UserProfile,
)

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlanRequest(BaseModel):
    objective: str = Field(..., min_length=6, max_length=4000)
    domains: list[str] | None = None
    artifact_ids: list[str] = Field(default_factory=list, max_length=20)
    context: dict[str, Any] = Field(default_factory=dict)
    network_allowed: bool = True
    max_concurrency: int = Field(default=2, ge=1, le=4)


class RunCreate(PlanRequest):
    execute: bool = True


class FeedbackRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    accepted: bool = False
    correction: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    propose_learning: bool = True


class ProposalDecision(BaseModel):
    decision: Literal["applied", "rejected", "quarantined"]


class ArtifactMigrationRequest(BaseModel):
    artifact_ids: list[str] = Field(default_factory=list, max_length=1000)


class ReportFormat(BaseModel):
    format: Literal["md", "html", "pdf"] = "pdf"


class ParamPredictRequest(BaseModel):
    pipeline_id: str = Field(..., min_length=1, max_length=200)
    revision: str = Field(default="", max_length=80)
    profile: str = Field(default="docker", max_length=40)
    system_memory_gb: float = Field(default=32.0, gt=0, le=1024)
    system_cpus: int = Field(default=8, ge=1, le=256)
    prior_parameters: dict[str, str] = Field(default_factory=dict)


def _bounded_context(context: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(context, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"context 必须可以序列化: {exc}") from exc
    if len(encoded.encode("utf-8")) > 512 * 1024:
        raise HTTPException(status_code=413, detail="context 超过 512 KiB 上限；请改用材料上传")
    return context


async def _learned_preferences(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalars().first()
    if not profile:
        return []
    return list((profile.skill_preferences or {}).get("research_planning_notes") or [])[:20]


async def _validate_artifacts(db: AsyncSession, user_id: int, artifact_ids: list[str]) -> None:
    ids = list(dict.fromkeys(artifact_ids))
    if not ids:
        return
    result = await db.execute(
        select(ResearchArtifact.id).where(
            ResearchArtifact.user_id == user_id,
            ResearchArtifact.id.in_(ids),
        )
    )
    found = set(result.scalars().all())
    missing = [item for item in ids if item not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"材料不存在或无权访问: {', '.join(missing[:5])}")


def _step_dict(step: ResearchRunStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "key": step.step_key,
        "order": step.order,
        "title": step.title,
        "capability": step.capability,
        "dependencies": step.dependencies or [],
        "status": step.status,
        "input": step.input_data or {},
        "output": step.output_data or {},
        "warnings": step.warnings or [],
        "error": step.error,
        "attempts": step.attempts,
        "confidence": step.confidence,
        "duration_ms": step.duration_ms,
        "started_at": step.started_at,
        "completed_at": step.completed_at,
    }


def _run_dict(run: ResearchRun, include_detail: bool = True) -> dict[str, Any]:
    value = {
        "id": run.id,
        "objective": run.objective,
        "status": run.status,
        "progress": run.progress,
        "current_step": run.current_step,
        "domains": (run.plan or {}).get("domains", []),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }
    if include_detail:
        value.update({
            "plan": run.plan or {},
            "result": run.result or {},
            "evidence": run.evidence or [],
            "policy": run.policy or {},
            "budget": run.budget or {},
            "steps": [_step_dict(step) for step in (run.steps or [])],
        })
    return value


@router.get("/capabilities")
async def capabilities(current_user: dict = Depends(get_current_user)):
    return {
        "runtime": "research-runtime-v1",
        "capabilities": list_capabilities(),
        "principles": ["evidence-first", "deny-unlisted", "bounded-execution", "human-review", "proposal-only-learning"],
    }


@router.post("/plan")
async def create_plan(
    request: PlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _validate_artifacts(db, current_user["user_id"], request.artifact_ids)
    context = _bounded_context(dict(request.context))
    context["learned_preferences"] = await _learned_preferences(db, current_user["user_id"])
    try:
        plan = ResearchPlanner().plan(
            request.objective,
            request.domains,
            request.artifact_ids,
            context,
            request.network_allowed,
            request.max_concurrency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"plan": plan.to_dict(), "validation_errors": ResearchPlanner.validate_plan(plan.to_dict())}


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run(
    request: RunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    await _validate_artifacts(db, user_id, request.artifact_ids)
    context = _bounded_context(dict(request.context))
    context["artifact_ids"] = list(dict.fromkeys(request.artifact_ids))
    context["learned_preferences"] = await _learned_preferences(db, user_id)
    try:
        plan = ResearchPlanner().plan(
            request.objective,
            request.domains,
            request.artifact_ids,
            context,
            request.network_allowed,
            request.max_concurrency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run = ResearchRun(
        id=str(uuid.uuid4()),
        user_id=user_id,
        objective=plan.objective,
        status="pending",
        plan=plan.to_dict(),
        context=context,
        evidence=[],
        result={},
        policy=plan.policy,
        budget=plan.budget,
        progress=0,
    )
    db.add(run)
    for order, step in enumerate(plan.steps):
        db.add(ResearchRunStep(
            run_id=run.id,
            step_key=step.key,
            order=order,
            title=step.title,
            capability=step.capability,
            dependencies=step.dependencies,
            status="pending",
            input_data=step.input_data,
        ))
    await db.commit()
    if request.execute:
        get_run_manager().submit(run.id)
    result = await db.execute(
        select(ResearchRun).options(selectinload(ResearchRun.steps)).where(ResearchRun.id == run.id)
    )
    return _run_dict(result.scalar_one())


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(ResearchRun)
        .where(ResearchRun.user_id == current_user["user_id"])
        .order_by(ResearchRun.created_at.desc())
        .limit(limit)
    )
    return {"runs": [_run_dict(run, include_detail=False) for run in result.scalars().all()]}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(ResearchRun).options(selectinload(ResearchRun.steps)).where(
            ResearchRun.id == run_id,
            ResearchRun.user_id == current_user["user_id"],
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="科研任务不存在")
    return _run_dict(run)


@router.post("/runs/{run_id}/start")
async def start_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.user_id == current_user["user_id"])
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="科研任务不存在")
    if run.status != "pending":
        raise HTTPException(status_code=409, detail=f"任务状态 {run.status} 不能启动")
    submitted = get_run_manager().submit(run.id)
    return {"status": "queued" if submitted else "already_queued", "run_id": run.id}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.user_id == current_user["user_id"])
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="科研任务不存在")
    if run.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"任务已处于终态: {run.status}")
    run.cancel_requested = True
    if run.status == "pending":
        run.status = "cancelled"
        run.completed_at = _utcnow()
        run.result = {"status": "cancelled", "message": "任务在启动前取消。", "has_gaps": True}
    await db.commit()
    get_run_manager().cancel(run_id)
    return {"status": "cancelling" if run.status == "running" else "cancelled", "run_id": run_id}


@router.post("/artifacts", status_code=status.HTTP_201_CREATED)
async def upload_artifact(
    request: Request,
    file: UploadFile = File(...),
    run_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    if run_id:
        result = await db.execute(
            select(ResearchRun.id).where(ResearchRun.id == run_id, ResearchRun.user_id == user_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="科研任务不存在")
    try:
        data = await get_run_manager().artifact_store.save_upload(file, user_id, run_id)
    except ArtifactError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    artifact = ResearchArtifact(user_id=user_id, run_id=run_id, **data)
    db.add(artifact)
    try:
        await append_audit(
            db,
            user_id=user_id,
            action="UPLOAD",
            resource="research_artifact",
            resource_id=artifact.id,
            detail={
                "name": artifact.name,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
                "encrypted_at_rest": True,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            request_id=request.headers.get("x-request-id"),
        )
    except Exception:
        await db.rollback()
        get_run_manager().artifact_store.resolve(data["relative_path"]).unlink(missing_ok=True)
        raise
    await db.refresh(artifact)
    return public_artifact(artifact)


@router.get("/artifacts")
async def list_artifacts(
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(ResearchArtifact)
        .where(ResearchArtifact.user_id == current_user["user_id"])
        .order_by(ResearchArtifact.created_at.desc())
        .limit(limit)
    )
    return {"artifacts": [public_artifact(item) for item in result.scalars().all()]}


async def _owned_artifact(db: AsyncSession, artifact_id: str, user_id: int) -> ResearchArtifact:
    result = await db.execute(
        select(ResearchArtifact).where(
            ResearchArtifact.id == artifact_id,
            ResearchArtifact.user_id == user_id,
        )
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact does not exist or is inaccessible")
    return artifact


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    artifact = await _owned_artifact(db, artifact_id, current_user["user_id"])
    store = get_run_manager().artifact_store
    try:
        raw = store.read_artifact(artifact)
    except ArtifactError as exc:
        await append_audit(
            db,
            user_id=artifact.user_id,
            action="DOWNLOAD",
            resource="research_artifact",
            resource_id=artifact.id,
            detail={"integrity_verified": False},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            request_id=request.headers.get("x-request-id"),
            success=False,
            error_message=str(exc)[:500],
        )
        raise HTTPException(status_code=409, detail="Artifact integrity verification failed") from exc
    await append_audit(
        db,
        user_id=artifact.user_id,
        action="DOWNLOAD",
        resource="research_artifact",
        resource_id=artifact.id,
        detail={"size_bytes": len(raw), "sha256": artifact.sha256, "integrity_verified": True},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
    )
    filename = get_run_manager().artifact_store.safe_name(artifact.name)
    disposition = f"attachment; filename=artifact{Path(filename).suffix}; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=raw,
        media_type=artifact.media_type or "application/octet-stream",
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(raw)),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/runs/{run_id}/report")
async def generate_report(
    run_id: str,
    payload: ReportFormat | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """生成研究简报（md/html/pdf），仅本人可访问。"""
    result = await db.execute(
        select(ResearchRun).options(selectinload(ResearchRun.steps)).where(
            ResearchRun.id == run_id,
            ResearchRun.user_id == current_user["user_id"],
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="科研任务不存在")
    report_format = payload.format if payload else "pdf"
    artifacts_result = await db.execute(
        select(ResearchArtifact).where(
            ResearchArtifact.run_id == run.id,
        ).order_by(ResearchArtifact.created_at.asc())
    )
    artifacts = [public_artifact(item) for item in artifacts_result.scalars().all()]
    pipeline_result = await db.execute(
        select(PipelineRun).where(PipelineRun.run_id == run.id).order_by(PipelineRun.created_at.asc())
    )
    pipeline_runs = [
        {
            "pipeline_id": item.pipeline_id,
            "revision": item.revision,
            "profile": item.profile,
            "status": item.status,
            "task_summary": (item.result or {}).get("task_summary", {}),
            "error": item.error,
        }
        for item in pipeline_result.scalars().all()
    ]
    markdown = build_brief_markdown(_run_dict(run), artifacts, pipeline_runs)
    media_map = {
        "md": ("text/markdown; charset=utf-8", "research-brief.md"),
        "html": ("text/html; charset=utf-8", "research-brief.html"),
        "pdf": ("application/pdf", "research-brief.pdf"),
    }
    media_type, filename = media_map[report_format]
    if report_format == "pdf":
        from ...reporting.pdf import render_pdf

        content = render_pdf(markdown, title=f"研究简报 {run.id}")
    elif report_format == "html":
        from ...reporting.pdf import render_html

        content = render_html(markdown).encode("utf-8")
    else:
        content = markdown.encode("utf-8")
    disposition = f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(content)),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )



@router.post("/runs/params/predict")
async def predict_run_parameters(
    request: ParamPredictRequest,
    current_user: dict = Depends(get_current_user),
):
    """Predict optimal parameters for a new pipeline run based on historical data."""
    result = await predict_for_new_run(
        user_id=current_user["user_id"],
        pipeline_id=request.pipeline_id,
        revision=request.revision,
        profile=request.profile,
        system_memory_gb=request.system_memory_gb,
        system_cpus=request.system_cpus,
        prior_parameters=request.prior_parameters,
    )
    sufficient, suff_msg = estimate_sample_sufficiency(result.historical_runs_analyzed)
    return {
        "pipeline_id": request.pipeline_id,
        "revision": request.revision or "latest",
        "recommendations": result.to_dict()["recommendations"],
        "confidence": result.confidence,
        "historical_runs_analyzed": result.historical_runs_analyzed,
        "data_sufficiency": {"sufficient": sufficient, "message": suff_msg},
        "warnings": result.warnings,
    }


@router.post("/runs/{run_id}/rocrate")
async def generate_rocrate_export(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """生成 RO-Crate 研究结果压缩包。"""
    result = await db.execute(
        select(ResearchRun).options(selectinload(ResearchRun.steps)).where(
            ResearchRun.id == run_id,
            ResearchRun.user_id == current_user["user_id"],
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="科研任务不存在")
    artifacts_result = await db.execute(
        select(ResearchArtifact).where(
            ResearchArtifact.run_id == run.id,
        ).order_by(ResearchArtifact.created_at.asc())
    )
    artifacts = [public_artifact(item) for item in artifacts_result.scalars().all()]
    pipeline_result = await db.execute(
        select(PipelineRun).where(PipelineRun.run_id == run.id).order_by(PipelineRun.created_at.asc())
    )
    pipeline_runs = [
        {
            "pipeline_id": item.pipeline_id,
            "revision": item.revision,
            "profile": item.profile,
            "status": item.status,
            "task_summary": (item.result or {}).get("task_summary", {}),
            "error": item.error,
        }
        for item in pipeline_result.scalars().all()
    ]
    store = get_run_manager().artifact_store
    crate_bytes, filename = await generate_rocrate(
        _run_dict(run), artifacts, pipeline_runs, store.root
    )
    disposition = f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=crate_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(crate_bytes)),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post("/artifacts/migrate-encryption")
async def migrate_artifact_encryption(
    payload: ArtifactMigrationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    query = select(ResearchArtifact).where(
        ResearchArtifact.user_id == user_id,
        ResearchArtifact.encryption_format.is_(None),
    )
    if payload.artifact_ids:
        query = query.where(ResearchArtifact.id.in_(list(dict.fromkeys(payload.artifact_ids))))
    result = await db.execute(query.order_by(ResearchArtifact.created_at.asc()).limit(1000))
    store = get_run_manager().artifact_store
    migrated: list[str] = []
    failed: list[dict[str, str]] = []
    cleanup_warnings: list[str] = []
    for artifact in result.scalars().all():
        target_path = None
        try:
            migration = store.migrate_plaintext(artifact)
            target_path = store.resolve(migration["relative_path"])
            legacy_path = store.resolve(migration.pop("legacy_relative_path"))
            artifact.relative_path = migration["relative_path"]
            artifact.encryption_format = migration["encryption_format"]
            artifact.encrypted_sha256 = migration["encrypted_sha256"]
            await append_audit(
                db,
                user_id=user_id,
                action="MIGRATE_ENCRYPTION",
                resource="research_artifact",
                resource_id=artifact.id,
                detail={"encryption_format": artifact.encryption_format},
            )
            migrated.append(artifact.id)
            try:
                legacy_path.unlink(missing_ok=True)
            except OSError:
                cleanup_warnings.append(artifact.id)
        except Exception as exc:
            await db.rollback()
            if target_path is not None:
                target_path.unlink(missing_ok=True)
            failed.append({"id": artifact.id, "error": str(exc)[:300]})
    return {
        "migrated": migrated,
        "failed": failed,
        "plaintext_cleanup_warnings": cleanup_warnings,
        "remaining_scope": "at most 1000 legacy artifacts per request",
    }


@router.post("/runs/{run_id}/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    run_id: str,
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    result = await db.execute(
        select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.user_id == user_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="科研任务不存在")
    feedback = AgentFeedback(
        user_id=user_id,
        run_id=run_id,
        rating=request.rating,
        accepted=request.accepted,
        correction=request.correction.strip() or None,
        tags=request.tags,
    )
    db.add(feedback)
    proposal = None
    correction = request.correction.strip()
    if request.propose_learning and len(correction) >= 12:
        proposal = LearningProposal(
            id=str(uuid.uuid4()),
            user_id=user_id,
            source_run_id=run_id,
            title=f"调整科研规划偏好：{correction[:60]}",
            rationale="来自用户对已完成科研任务的显式纠正；应用前必须人工审核。",
            proposed_change={
                "kind": "research_planning_preference",
                "instruction": correction,
                "domains": (run.plan or {}).get("domains", []),
            },
            evidence=[{"run_id": run_id, "rating": request.rating, "accepted": request.accepted}],
            status="pending",
        )
        db.add(proposal)
    await db.commit()
    return {
        "feedback_id": feedback.id,
        "learning_proposal": {
            "id": proposal.id, "status": proposal.status, "title": proposal.title
        } if proposal else None,
        "behavior_changed": False,
    }


@router.get("/learning-proposals")
async def list_learning_proposals(
    proposal_status: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    query = select(LearningProposal).where(LearningProposal.user_id == current_user["user_id"])
    if proposal_status:
        query = query.where(LearningProposal.status == proposal_status)
    result = await db.execute(query.order_by(LearningProposal.created_at.desc()).limit(100))
    return {"proposals": [
        {
            "id": item.id, "source_run_id": item.source_run_id, "title": item.title,
            "rationale": item.rationale, "proposed_change": item.proposed_change,
            "evidence": item.evidence or [], "status": item.status,
            "created_at": item.created_at, "reviewed_at": item.reviewed_at,
        }
        for item in result.scalars().all()
    ]}


@router.post("/learning-proposals/{proposal_id}/decision")
async def decide_learning_proposal(
    proposal_id: str,
    request: ProposalDecision,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    result = await db.execute(
        select(LearningProposal).where(
            LearningProposal.id == proposal_id,
            LearningProposal.user_id == user_id,
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="学习提案不存在")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"提案已经处理: {proposal.status}")
    proposal.status = request.decision
    proposal.reviewed_at = _utcnow()
    if request.decision == "applied":
        profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = profile_result.scalars().first()
        if not profile:
            profile = UserProfile(user_id=user_id, skill_preferences={})
            db.add(profile)
        preferences = dict(profile.skill_preferences or {})
        notes = list(preferences.get("research_planning_notes") or [])
        notes.append({
            "proposal_id": proposal.id,
            "instruction": (proposal.proposed_change or {}).get("instruction", "")[:1000],
            "domains": (proposal.proposed_change or {}).get("domains", []),
        })
        preferences["research_planning_notes"] = notes[-20:]
        # Wire up pipeline_param proposals: store adaptive defaults in profile
        pc = proposal.proposed_change or {}
        if pc.get("parameter") and pc.get("recommended_value") is not None:
            defaults = dict(preferences.get("pipeline_defaults") or {})
            pid = pc.get("pipeline_id", "")
            entry = defaults.get(pid) or {}
            entry[pc["parameter"]] = pc["recommended_value"]
            defaults[pid] = entry
            preferences["pipeline_defaults"] = defaults
        # Wire up pipeline_code_improvement proposals: store diff context for future reference
        if pc.get("proposal_type") == "pipeline_code_improvement":
            code_notes = list(preferences.get("pipeline_code_notes") or [])
            code_notes.append({
                "proposal_id": proposal.id,
                "pipeline_id": pc.get("pipeline_id", ""),
                "revision": pc.get("revision", ""),
                "target_file": pc.get("target_file", ""),
                "change_description": pc.get("change_description", "")[:500],
                "confidence": pc.get("confidence", 0.0),
            })
            preferences["pipeline_code_notes"] = code_notes[-10:]
        profile.skill_preferences = preferences
    await db.commit()
    return {"id": proposal.id, "status": proposal.status, "behavior_changed": request.decision == "applied"}


__all__ = ["router"]
