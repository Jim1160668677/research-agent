"""Safe API for allowlisted, revision-pinned production bioinformatics pipelines."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...audit_chain import append_audit
from ...execution.manager import RESUMABLE_STATUSES, TERMINAL_STATUSES, get_pipeline_manager
from ...execution.nextflow import PIPELINES, pipeline_catalog, validate_request
from ..auth import get_current_user, require_role
from ..db import get_db
from ..models.db import PipelineRun, ResearchArtifact, UserProfile

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PipelineRequest(BaseModel):
    pipeline_id: str = Field(..., min_length=3, max_length=150)
    revision: str = Field(..., min_length=1, max_length=80)
    profile: Literal["docker", "podman", "singularity", "apptainer", "conda"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    artifact_bindings: dict[str, str] = Field(default_factory=dict)
    network_allowed: bool = True
    timeout_seconds: int = Field(default=86400, ge=300, le=604800)


class PipelineCreate(PipelineRequest):
    execute: bool = False


def _bounded_mapping(value: dict[str, Any], label: str, limit: int = 64 * 1024) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{label} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > limit:
        raise HTTPException(status_code=413, detail=f"{label} exceeds the {limit // 1024} KiB limit")


async def _validate_artifacts(
    db: AsyncSession,
    user_id: int,
    pipeline_id: str,
    bindings: dict[str, str],
) -> None:
    if not bindings:
        return
    ids = list(dict.fromkeys(bindings.values()))
    result = await db.execute(
        select(ResearchArtifact).where(
            ResearchArtifact.user_id == user_id,
            ResearchArtifact.id.in_(ids),
            ResearchArtifact.status == "ready",
        )
    )
    artifacts = {item.id: item for item in result.scalars().all()}
    if len(artifacts) != len(ids):
        raise HTTPException(status_code=404, detail="A bound artifact is missing or inaccessible")
    spec = PIPELINES[pipeline_id]["artifact_parameters"]
    for parameter, artifact_id in bindings.items():
        suffix = Path(artifacts[artifact_id].name).suffix.lower()
        if suffix not in spec[parameter]["suffixes"]:
            allowed = ", ".join(spec[parameter]["suffixes"])
            raise HTTPException(
                status_code=422,
                detail=f"Artifact {parameter} must use one of these suffixes: {allowed}",
            )


def _run_dict(run: PipelineRun, detail: bool = True) -> dict[str, Any]:
    data = {
        "id": run.id,
        "backend": run.backend,
        "pipeline_id": run.pipeline_id,
        "revision": run.revision,
        "profile": run.profile,
        "status": run.status,
        "network_allowed": run.network_allowed,
        "timeout_seconds": run.timeout_seconds,
        "resume_count": run.resume_count,
        "exit_code": run.exit_code,
        "error": run.error,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }
    if detail:
        data.update({
            "parameters": run.parameters or {},
            "artifact_bindings": run.artifact_bindings or {},
            "plan": run.plan or {},
            "result": run.result or {},
            "provenance": run.provenance or {},
        })
    return data


async def _audit(
    db: AsyncSession,
    user_id: int,
    action: str,
    run: PipelineRun,
    detail: dict[str, Any],
) -> None:
    await append_audit(
        db,
        user_id=user_id,
        action=action,
        resource="pipeline_run",
        resource_id=run.id,
        detail={
            "backend": run.backend,
            "pipeline": run.pipeline_id,
            "revision": run.revision,
            "profile": run.profile,
            **detail,
        },
        success=True,
    )


@router.get("/catalog")
async def catalog(current_user: dict = Depends(get_current_user)):
    return {
        "policy": "allowlisted-and-revision-pinned",
        "pipelines": pipeline_catalog(),
        "execution_requires_role": "admin",
    }


@router.get("/capabilities")
async def capabilities(
    deep: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
):
    if deep and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Deep execution probing requires the admin role")
    return await get_pipeline_manager().backend.capabilities(deep=deep)


def _validate_request(request: PipelineRequest) -> dict[str, Any]:
    _bounded_mapping(request.parameters, "parameters")
    _bounded_mapping(request.artifact_bindings, "artifact_bindings")
    try:
        return validate_request(
            request.pipeline_id,
            request.revision,
            request.profile,
            request.parameters,
            request.artifact_bindings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/preflight")
async def preflight(
    request: PipelineRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    _validate_request(request)
    await _validate_artifacts(db, current_user["user_id"], request.pipeline_id, request.artifact_bindings)
    return await get_pipeline_manager().backend.preflight(
        pipeline_id=request.pipeline_id,
        revision=request.revision,
        profile=request.profile,
        network_allowed=request.network_allowed,
    )


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run(
    request: PipelineCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if request.execute and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Starting external computation requires the admin role")
    # Merge stored adaptive pipeline defaults into request parameters
    _up_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user["user_id"]))
    _up = _up_result.scalars().first()
    _defaults = (dict((_up.skill_preferences or {}).get("pipeline_defaults") or {})).get(request.pipeline_id, {}) if _up else {}
    if _defaults:
        merged = {**_defaults, **request.parameters}
        request.parameters = merged
    normalized = _validate_request(request)
    user_id = current_user["user_id"]
    await _validate_artifacts(db, user_id, request.pipeline_id, request.artifact_bindings)
    run = PipelineRun(
        id=str(uuid.uuid4()), user_id=user_id, backend="nextflow",
        pipeline_id=request.pipeline_id, revision=request.revision,
        profile=request.profile, status="planned", parameters=normalized,
        artifact_bindings=request.artifact_bindings,
        network_allowed=request.network_allowed,
        timeout_seconds=request.timeout_seconds,
        provenance={"policy": "allowlisted-and-revision-pinned"},
    )
    db.add(run)
    await _audit(db, user_id, "CREATE", run, {"execute": request.execute})
    try:
        await get_pipeline_manager().plan_run(run.id)
    except (ValueError, RuntimeError) as exc:
        run.status = "failed"
        run.error = str(exc)[:4000]
        run.completed_at = _utcnow()
        await db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.refresh(run)
    if request.execute:
        readiness = await get_pipeline_manager().backend.preflight(
            pipeline_id=run.pipeline_id, revision=run.revision,
            profile=run.profile, network_allowed=run.network_allowed,
        )
        if not readiness.get("ready"):
            return {**_run_dict(run), "preflight": readiness}
        run.status = "queued"
        await _audit(db, user_id, "START", run, {"source": "create"})
        await db.refresh(run)
        get_pipeline_manager().submit(run.id)
    return _run_dict(run)


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(PipelineRun).where(PipelineRun.user_id == current_user["user_id"])
        .order_by(PipelineRun.created_at.desc()).limit(limit)
    )
    return {"runs": [_run_dict(item, detail=False) for item in result.scalars().all()]}


async def _owned_run(db: AsyncSession, run_id: str, user_id: int) -> PipelineRun:
    result = await db.execute(
        select(PipelineRun).where(PipelineRun.id == run_id, PipelineRun.user_id == user_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run does not exist")
    return run


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return _run_dict(await _owned_run(db, run_id, current_user["user_id"]))


@router.get("/runs/{run_id}/artifacts/{artifact_index}")
async def download_artifact(
    run_id: str,
    artifact_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    run = await _owned_run(db, run_id, current_user["user_id"])
    artifacts = list((run.result or {}).get("artifacts") or [])
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="Pipeline artifact does not exist")
    item = artifacts[artifact_index]
    relative_path = str(item.get("relative_path") or "")
    backend = get_pipeline_manager().backend
    if not hasattr(backend, "resolve_artifact"):
        raise HTTPException(status_code=501, detail="The execution backend cannot serve artifacts")
    try:
        path = backend.resolve_artifact(run.user_id, run.id, relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=Path(str(item.get("name") or path.name)).name)


@router.post("/runs/{run_id}/start")
async def start_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    run = await _owned_run(db, run_id, current_user["user_id"])
    if run.status != "planned":
        raise HTTPException(status_code=409, detail=f"A {run.status} run cannot be started")
    readiness = await get_pipeline_manager().backend.preflight(
        pipeline_id=run.pipeline_id, revision=run.revision,
        profile=run.profile, network_allowed=run.network_allowed,
    )
    if not readiness.get("ready"):
        raise HTTPException(status_code=409, detail={"message": "Preflight failed", **readiness})
    run.status = "queued"
    run.cancel_requested = False
    await _audit(db, run.user_id, "START", run, {})
    await db.refresh(run)
    submitted = get_pipeline_manager().submit(run.id)
    return {"run_id": run.id, "status": "queued" if submitted else "already_queued"}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    run = await _owned_run(db, run_id, current_user["user_id"])
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Run is already terminal: {run.status}")
    run.cancel_requested = True
    if run.status in {"planned", "queued"}:
        run.status = "cancelled"
        run.completed_at = _utcnow()
        run.result = {"status": "cancelled", "error": "Cancelled before execution"}
    else:
        run.status = "cancelling"
    await _audit(db, run.user_id, "CANCEL", run, {})
    await db.refresh(run)
    cancelled = get_pipeline_manager().cancel(run.id)
    return {"run_id": run.id, "status": run.status, "task_signalled": cancelled}


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    run = await _owned_run(db, run_id, current_user["user_id"])
    if run.status not in RESUMABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"A {run.status} run cannot be resumed")
    readiness = await get_pipeline_manager().backend.preflight(
        pipeline_id=run.pipeline_id, revision=run.revision,
        profile=run.profile, network_allowed=run.network_allowed,
    )
    if not readiness.get("ready"):
        raise HTTPException(status_code=409, detail={"message": "Preflight failed", **readiness})
    history = list((run.provenance or {}).get("resume_history") or [])[-19:]
    history.append({"at": _utcnow().isoformat(), "previous_status": run.status,
                    "previous_exit_code": run.exit_code, "previous_error": run.error})
    run.provenance = {**dict(run.provenance or {}), "resume_history": history}
    run.status = "queued"
    run.resume_requested = True
    run.resume_count = int(run.resume_count or 0) + 1
    run.cancel_requested = False
    run.completed_at = None
    run.error = None
    await _audit(db, run.user_id, "RESUME", run, {"resume_count": run.resume_count})
    await db.refresh(run)
    get_pipeline_manager().submit(run.id)
    return {"run_id": run.id, "status": "queued", "resume_count": run.resume_count}


__all__ = ["router"]
