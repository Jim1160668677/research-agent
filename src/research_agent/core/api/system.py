"""Product-level status endpoints used by the desktop overview."""

from fastapi import APIRouter, Depends
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
