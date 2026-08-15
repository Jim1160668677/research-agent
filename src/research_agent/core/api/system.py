"""Product-level status endpoints used by the desktop overview."""

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agents.skills import SkillRegistry
from ...audit_chain import verify_audit_chain
from ...llm.keys import get_key_manager
from ...plugins.lifecycle import INSTALLED_STATES, latest_installations_for_user
from ..auth import get_current_user, require_role
from ..db import get_db
from ..models.db import Conversation, ResearchArtifact, ResearchRun, Workflow, WorkflowRun

router = APIRouter()


@router.get("/runtime")
async def runtime_status(
    current_user: dict = Depends(get_current_user),
):
    """Return one synchronized view across research, workflow and pipeline work."""
    from ...execution import get_pipeline_manager
    from ...research import get_run_manager
    from ...runtime_coordinator import get_runtime_coordinator
    from ...workflows.engine import WorkflowEngine

    snapshot = await get_runtime_coordinator().snapshot()
    snapshot["research_run_ids"] = get_run_manager().active_ids()
    snapshot["pipeline_run_ids"] = get_pipeline_manager().active_ids()
    snapshot["workflow_run_ids"] = sorted(WorkflowEngine._active_tasks.keys())
    return snapshot


@router.get("/security-integrity")
async def security_integrity(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Verify the audit hash chain and report raw-data encryption coverage."""

    user_id = current_user["user_id"]
    total = (
        await db.scalar(
            select(func.count(ResearchArtifact.id)).where(ResearchArtifact.user_id == user_id)
        )
        or 0
    )
    encrypted = (
        await db.scalar(
            select(func.count(ResearchArtifact.id)).where(
                ResearchArtifact.user_id == user_id,
                ResearchArtifact.encryption_format == "ra-aes256-gcm-v1",
            )
        )
        or 0
    )
    global_total = await db.scalar(select(func.count(ResearchArtifact.id))) or 0
    global_encrypted = (
        await db.scalar(
            select(func.count(ResearchArtifact.id)).where(
                ResearchArtifact.encryption_format == "ra-aes256-gcm-v1"
            )
        )
        or 0
    )
    chain = await verify_audit_chain(db)
    return {
        "artifacts": {
            "scope": "current_user",
            "total": total,
            "encrypted": encrypted,
            "legacy_plaintext": max(0, total - encrypted),
            "encryption_format": "ra-aes256-gcm-v1",
        },
        "global_artifacts": {
            "total": global_total,
            "encrypted": global_encrypted,
            "legacy_plaintext": max(0, global_total - global_encrypted),
        },
        "audit_chain": chain,
    }


@router.get("/health-check")
async def health_check(
    deep: bool = Query(False, description="深度探测：验证版本输出与流程预检"),
    current_user: dict = Depends(get_current_user),
):
    """聚合环境体检：平台、工具链、WSL2、容器、Nextflow、流程预检、磁盘。"""
    from ...execution import get_pipeline_manager
    from ...execution.nextflow import PIPELINES
    from ...plugins.platform_probe import PlatformCapabilityProbe

    items: list[dict[str, Any]] = []
    probe = await PlatformCapabilityProbe().probe(deep=deep)
    host = probe["host"]
    tools = probe["tools"]
    wsl = probe["wsl"]

    items.append({
        "id": "host",
        "title": f"主机平台 · {host['system']} {host['release']}",
        "status": "ok",
        "detail": f"{host['architecture']} · Python {host['python']}",
        "fix_hint": "",
    })

    conda_names = ("micromamba", "mamba", "conda")
    conda_available = any(tools[name]["available"] for name in conda_names)
    conda_name = next((name for name in conda_names if tools[name]["available"]), "")
    items.append({
        "id": "conda",
        "title": "Conda 环境管理器",
        "status": "ok" if conda_available else "error",
        "detail": f"{conda_name} 可用（隔离环境部署的基础）" if conda_available else "未检测到 micromamba / mamba / conda",
        "fix_hint": "" if conda_available else "安装 Miniconda（https://docs.conda.io/en/latest/miniconda.html）或 Micromamba，然后重启应用。",
    })

    if host["system"] == "windows":
        items.append({
            "id": "wsl2",
            "title": "WSL2 子系统",
            "status": "ok" if wsl.get("operational") else ("warn" if wsl.get("available") else "missing"),
            "detail": (
                f"可用，发行版：{', '.join(wsl.get('distributions', [])[:3])}"
                if wsl.get("operational")
                else ("已安装但无可用发行版或未启动" if wsl.get("available") else "未安装")
            ),
            "fix_hint": (
                ""
                if wsl.get("operational")
                else "管理员 PowerShell 运行：wsl --install，随后安装 Ubuntu 发行版；Linux 版生物信息工具依赖它。"
            ),
        })
    else:
        items.append({
            "id": "wsl2",
            "title": "WSL2 子系统",
            "status": "ok",
            "detail": f"当前平台 {host['system']} 不需要 WSL2",
            "fix_hint": "",
        })

    containers = {name: tools[name]["available"] for name in ("docker", "podman", "apptainer", "singularity")}
    container_hit = next((name for name, ok in containers.items() if ok), "")
    items.append({
        "id": "containers",
        "title": "容器引擎",
        "status": "ok" if container_hit else "warn",
        "detail": f"{container_hit} 可用" if container_hit else "未检测到 Docker / Podman / Apptainer",
        "fix_hint": "" if container_hit else "安装并启动 Docker Desktop；nf-core 流程的 docker/singularity profile 需要容器引擎。",
    })

    nextflow_available = tools["nextflow"]["available"]
    items.append({
        "id": "nextflow",
        "title": "Nextflow",
        "status": "ok" if nextflow_available else "error",
        "detail": f"路径 {tools['nextflow']['path']}" if nextflow_available else "未检测到 nextflow",
        "fix_hint": "" if nextflow_available else "安装：conda install -c bioconda nextflow，或 curl -s https://get.nextflow.io | bash。",
    })

    pipeline_item: dict[str, Any] = {
        "id": "pipelines",
        "title": "nf-core 流程（固定版本）",
        "status": "ok",
        "detail": "、".join(f"{pid}@{spec['revision']}" for pid, spec in PIPELINES.items()),
        "fix_hint": "",
    }
    if deep:
        try:
            manager = get_pipeline_manager()
            capabilities = await manager.backend.capabilities(deep=True)
            if not capabilities.get("available"):
                pipeline_item.update({
                    "status": "error",
                    "detail": f"Nextflow 不可用：{capabilities.get('probe_error', '未通过版本探测')}",
                    "fix_hint": "按上方 Nextflow 项修复后重新检测。",
                })
            else:
                compatibility = capabilities.get("pipeline_compatibility") or {}
                incompatible = [pid for pid, ok in compatibility.items() if not ok]
                compat_text = "、".join(
                    f"{pid}@{PIPELINES[pid]['revision']}" for pid in compatibility
                )
                pipeline_item.update({
                    "status": "warn" if incompatible else "ok",
                    "detail": f"Nextflow {capabilities.get('version', '?')} · "
                              + (f"流程兼容：{compat_text}"
                                 if compat_text else "未声明流程兼容性"),
                    "fix_hint": "" if not incompatible else f"Nextflow 版本过低，需要 ≥ {PIPELINES[incompatible[0]]['minimum_nextflow']}。",
                })
            first_id, first_spec = next(iter(PIPELINES.items()))
            preflight = await manager.backend.preflight(
                pipeline_id=first_id,
                revision=first_spec["revision"],
                profile="docker",
                network_allowed=True,
            )
            if preflight.get("ready"):
                pipeline_item["detail"] += " · 预检通过"
            else:
                issues = preflight.get("issues") or preflight.get("warnings") or []
                pipeline_item.update({
                    "status": "warn",
                    "detail": pipeline_item["detail"] + " · 预检未通过：" + "; ".join(str(item) for item in issues[:3]),
                    "fix_hint": "检查 Nextflow 与容器引擎配置后重新检测。",
                })
        except Exception as exc:  # 探测失败不应拖垮整个体检
            pipeline_item.update({
                "status": "error",
                "detail": f"流程探测失败：{str(exc)[:300]}",
                "fix_hint": "重新检测；持续失败请查看应用日志。",
            })
    items.append(pipeline_item)

    disk_target = Path.cwd()
    try:
        usage = shutil.disk_usage(disk_target)
        free_gb = usage.free / (1024**3)
        items.append({
            "id": "disk",
            "title": "磁盘空间",
            "status": "ok" if free_gb >= 10 else ("warn" if free_gb >= 2 else "error"),
            "detail": f"{disk_target.drive or disk_target} · 可用 {free_gb:.1f} GiB / 总 {usage.total / (1024**3):.0f} GiB",
            "fix_hint": "" if free_gb >= 2 else "清理工作目录（pipeline-runs、dist-*）或迁移到更大磁盘。",
        })
    except OSError:
        items.append({
            "id": "disk",
            "title": "磁盘空间",
            "status": "warn",
            "detail": f"无法读取 {disk_target} 的磁盘信息",
            "fix_hint": "",
        })

    summary = {
        "ok": sum(1 for item in items if item["status"] == "ok"),
        "warn": sum(1 for item in items if item["status"] == "warn"),
        "error": sum(1 for item in items if item["status"] == "error"),
        "missing": sum(1 for item in items if item["status"] == "missing"),
    }
    overall = "ok" if summary["error"] == 0 and summary["missing"] == 0 else "attention"
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deep": deep,
        "overall": overall,
        "summary": summary,
        "items": items,
    }


@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return the small, user-scoped read model needed by the dashboard."""
    user_id = current_user["user_id"]
    conversation_count = await db.scalar(
        select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
    )
    workflow_count = await db.scalar(
        select(func.count(Workflow.id)).where(
            Workflow.author == user_id,
            Workflow.status != "archived",
        )
    )
    plugin_states = await latest_installations_for_user(db, user_id)
    installed_count = sum(1 for item in plugin_states.values() if item.status in INSTALLED_STATES)
    research_run_count = await db.scalar(
        select(func.count(ResearchRun.id)).where(ResearchRun.user_id == user_id)
    )

    recent_conversations_result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(4)
    )
    recent_runs_result = await db.execute(
        select(WorkflowRun, Workflow.name)
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .where(WorkflowRun.user_id == user_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(4)
    )
    recent_research_result = await db.execute(
        select(ResearchRun)
        .where(ResearchRun.user_id == user_id)
        .order_by(ResearchRun.created_at.desc())
        .limit(4)
    )

    activities = []
    for conversation in recent_conversations_result.scalars().all():
        messages = list(conversation.messages or [])
        title = next(
            (item.get("content", "") for item in messages if item.get("role") == "user"),
            "科研对话",
        )
        activities.append(
            {
                "type": "conversation",
                "title": title.strip().replace("\n", " ")[:72],
                "status": "completed",
                "time": conversation.updated_at or conversation.created_at,
                "target": f"/chat?session={conversation.session_id}",
            }
        )
    for run, workflow_name in recent_runs_result.all():
        activities.append(
            {
                "type": "workflow",
                "title": workflow_name,
                "status": run.status,
                "time": run.completed_at or run.started_at or run.created_at,
                "target": "/workflows",
            }
        )
    for run in recent_research_result.scalars().all():
        activities.append(
            {
                "type": "research",
                "title": run.objective[:72],
                "status": run.status,
                "time": run.completed_at or run.started_at or run.created_at,
                "target": "/research",
            }
        )
    activities.sort(key=lambda item: item["time"].isoformat() if item["time"] else "", reverse=True)

    keys = await get_key_manager(db, user_id=user_id).list_keys()
    configured_models = sum(1 for item in keys if item["configured"])
    return {
        "counts": {
            "conversations": conversation_count or 0,
            "installed_plugins": installed_count or 0,
            "workflows": workflow_count or 0,
            "skills": len(SkillRegistry.list_all()),
            "research_runs": research_run_count or 0,
        },
        "models": {
            "configured": configured_models,
            "total": len(keys),
        },
        "activities": activities[:6],
    }


__all__ = ["router"]
