"""Workflow CRUD, execution, progress and cancellation routes."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...workflows.engine import WorkflowEngine
from ..auth import get_current_user
from ..db import get_db
from ..models.schemas import (
    WorkflowCreate,
    WorkflowResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowUpdate,
)

router = APIRouter()


@router.get("/", response_model=List[WorkflowResponse])
async def list_workflows(
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List workflows owned by the user plus explicitly public workflows."""
    return await WorkflowEngine(db).list_workflows(
        category=category,
        status=status,
        user_id=current_user["user_id"],
    )


@router.post("/", response_model=WorkflowResponse)
async def create_workflow(
    workflow: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    engine = WorkflowEngine(db)
    try:
        data = workflow.model_dump()
        data["author"] = current_user["user_id"]
        return await engine.create_workflow(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/run", response_model=WorkflowRunResponse)
async def run_workflow(
    request: WorkflowRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await WorkflowEngine(db).run_workflow(
            request.workflow_id,
            request.inputs,
            user_id=current_user["user_id"],
            variables=request.variables,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Workflow execution failed") from exc


# Static ``runs`` routes must be registered before ``/{workflow_id}`` so that
# ``/runs/123`` is not interpreted as a workflow id and rejected with a 422.
@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
async def get_workflow_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    run = await WorkflowEngine(db).get_run(run_id, user_id=current_user["user_id"])
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/runs/{run_id}/cancel")
async def cancel_workflow_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    success = await WorkflowEngine(db).cancel_run(
        run_id,
        user_id=current_user["user_id"],
    )
    if not success:
        raise HTTPException(status_code=404, detail="Run not found or already completed")
    return {"status": "cancelled", "run_id": run_id}


@router.get("/{workflow_id}/runs", response_model=List[WorkflowRunResponse])
async def list_workflow_runs(
    workflow_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await WorkflowEngine(db).list_runs(
        workflow_id,
        limit=limit,
        user_id=current_user["user_id"],
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    workflow = await WorkflowEngine(db).get_workflow(
        workflow_id,
        user_id=current_user["user_id"],
        allow_public=True,
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: int,
    update_data: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        workflow = await WorkflowEngine(db).update_workflow(
            workflow_id,
            {key: value for key, value in update_data.model_dump().items() if value is not None},
            user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    success = await WorkflowEngine(db).delete_workflow(
        workflow_id,
        user_id=current_user["user_id"],
    )
    if not success:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"status": "ok"}


__all__ = ["router"]
