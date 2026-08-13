"""Validated DAG workflow engine with provenance, retries and cancellation."""

from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import networkx as nx
from loguru import logger
from sqlalchemy import or_, select, update

from ..core.db import AsyncSession
from ..core.models.db import Workflow, WorkflowRun, WorkflowStep


class WorkflowStatus(Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowExecutionContext:
    run_id: int
    inputs: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    current_node: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancel_event: asyncio.Event | None = None

    def check_cancelled(self) -> None:
        if self.cancel_event and self.cancel_event.is_set():
            raise asyncio.CancelledError(f"Workflow run {self.run_id} cancelled")


class WorkflowEngine:
    """Execute workflow definitions without treating metadata as successful work."""

    _SUPPORTED_NODE_TYPES = {"skill", "plugin", "input", "output", "condition"}
    _REFERENCE = re.compile(r"^\$\{([^{}]+)\}$")
    _EMBEDDED_REFERENCE = re.compile(r"\$\{([^{}]+)\}")

    # API requests construct separate engine objects. Keeping active signals at
    # process scope makes cancellation work across those request instances.
    _active_cancel_events: dict[int, asyncio.Event] = {}
    _active_tasks: dict[int, asyncio.Task] = {}

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        # Backwards-compatible attributes used by existing tests and callers.
        self._cancel_events = self.__class__._active_cancel_events
        self._running_workflows = self.__class__._active_tasks

    @classmethod
    def initialize(cls) -> None:
        logger.info("Workflow engine initialized")

    @classmethod
    async def recover_interrupted_runs(cls) -> int:
        """Repair persisted workflow rows owned by a terminated process."""
        from ..core import db as db_module

        now = datetime.now()
        async with db_module.AsyncSessionLocal() as db:
            result = await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.status.in_({"pending", "running"}))
                .values(
                    status="interrupted",
                    completed_at=now,
                    errors=[
                        {
                            "type": "interrupted",
                            "message": "The previous application process ended before completion",
                        }
                    ],
                )
            )
            await db.execute(
                update(WorkflowStep)
                .where(WorkflowStep.status == "running")
                .values(
                    status="failed",
                    completed_at=now,
                    errors=["Application restart interrupted this step"],
                )
            )
            await db.commit()
            return int(result.rowcount or 0)

    @classmethod
    def _validate_definition(cls, definition: dict[str, Any]) -> None:
        if not isinstance(definition, dict):
            raise ValueError("Workflow definition must be an object")
        nodes = definition.get("nodes", [])
        edges = definition.get("edges", [])
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("Workflow must have at least one node")
        if not isinstance(edges, list):
            raise ValueError("Workflow edges must be a list")

        node_names = [node.get("name") for node in nodes if isinstance(node, dict)]
        if len(node_names) != len(nodes) or any(not name for name in node_names):
            raise ValueError("Every workflow node must be an object with a name")
        if len(set(node_names)) != len(node_names):
            raise ValueError("Workflow node names must be unique")

        known_nodes = set(node_names)
        dag = nx.DiGraph()
        dag.add_nodes_from(node_names)
        for node in nodes:
            config = node.get("config") or {}
            node_type = config.get("node_type") or node.get("node_type", "skill")
            if node_type not in cls._SUPPORTED_NODE_TYPES:
                raise ValueError(f"Unknown workflow node type: {node_type}")
        for edge in edges:
            if not isinstance(edge, dict):
                raise ValueError("Every workflow edge must be an object")
            source, target = edge.get("source"), edge.get("target")
            if source not in known_nodes or target not in known_nodes:
                raise ValueError("Workflow edge references an unknown node")
            if source == target:
                raise ValueError("Workflow nodes cannot depend on themselves")
            dag.add_edge(source, target)
        if not nx.is_directed_acyclic_graph(dag):
            raise ValueError("Workflow contains circular dependencies")

    async def list_workflows(
        self,
        category: str | None = None,
        status: str | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        query = select(Workflow)
        if user_id is not None:
            query = query.where(or_(Workflow.author == user_id, Workflow.is_public.is_(True)))
        if category:
            query = query.where(Workflow.category == category)
        if status:
            query = query.where(Workflow.status == status)
        result = await self.db.execute(query.order_by(Workflow.updated_at.desc()))
        return [self._workflow_to_dict(item) for item in result.scalars().all()]

    async def get_workflow(
        self,
        workflow_id: int,
        user_id: int | None = None,
        *,
        allow_public: bool = True,
    ) -> dict[str, Any] | None:
        query = select(Workflow).where(Workflow.id == workflow_id)
        if user_id is not None:
            access = Workflow.author == user_id
            if allow_public:
                access = or_(access, Workflow.is_public.is_(True))
            query = query.where(access)
        result = await self.db.execute(query)
        workflow = result.scalar_one_or_none()
        return self._workflow_to_dict(workflow) if workflow else None

    async def create_workflow(self, workflow_data: dict[str, Any]) -> dict[str, Any]:
        definition = workflow_data.get("definition", {})
        self._validate_definition(definition)
        workflow = Workflow(
            name=workflow_data["name"],
            description=workflow_data.get("description"),
            category=workflow_data.get("category", "general"),
            definition=definition,
            variables=workflow_data.get("variables", {}),
            is_public=workflow_data.get("is_public", False),
            author=workflow_data.get("author"),
            status=workflow_data.get("status", "active"),
        )
        self.db.add(workflow)
        await self.db.commit()
        await self.db.refresh(workflow)
        logger.info("Workflow created: {} (ID: {})", workflow.name, workflow.id)
        return self._workflow_to_dict(workflow)

    async def update_workflow(
        self,
        workflow_id: int,
        update_data: dict[str, Any],
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        query = select(Workflow).where(Workflow.id == workflow_id)
        if user_id is not None:
            query = query.where(Workflow.author == user_id)
        result = await self.db.execute(query)
        workflow = result.scalar_one_or_none()
        if not workflow:
            return None
        if "definition" in update_data:
            self._validate_definition(update_data["definition"])
        allowed = {
            "name",
            "description",
            "category",
            "definition",
            "variables",
            "is_public",
            "status",
            "version",
            "tags",
        }
        for key, value in update_data.items():
            if key in allowed:
                setattr(workflow, key, value)
        workflow.updated_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(workflow)
        return self._workflow_to_dict(workflow)

    async def delete_workflow(self, workflow_id: int, user_id: int | None = None) -> bool:
        query = select(Workflow).where(Workflow.id == workflow_id)
        if user_id is not None:
            query = query.where(Workflow.author == user_id)
        result = await self.db.execute(query)
        workflow = result.scalar_one_or_none()
        if not workflow:
            return False
        await self.db.delete(workflow)
        await self.db.commit()
        return True

    async def run_workflow(
        self,
        workflow_id: int,
        inputs: dict[str, Any],
        user_id: int | None = None,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query = select(Workflow).where(Workflow.id == workflow_id)
        if user_id is not None:
            query = query.where(or_(Workflow.author == user_id, Workflow.is_public.is_(True)))
        result = await self.db.execute(query)
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow not found: {workflow_id}")
        if workflow.status != "active":
            raise ValueError(f"Workflow is not active: {workflow.status}")

        run = WorkflowRun(
            workflow_id=workflow_id,
            user_id=user_id,
            status="running",
            inputs=inputs or {},
            progress=0,
            started_at=datetime.now(),
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)

        cancel_event = asyncio.Event()
        self._cancel_events[run.id] = cancel_event
        current_task = asyncio.current_task()
        if current_task is not None:
            self._running_workflows[run.id] = current_task
        merged_variables = {**(workflow.variables or {}), **(variables or {})}
        context = WorkflowExecutionContext(
            run_id=run.id,
            inputs=inputs or {},
            variables=merged_variables,
            cancel_event=cancel_event,
            started_at=datetime.now(),
        )

        try:
            execution = await self._execute_dag(workflow.definition, context)
            final_status = "completed" if execution["success"] else "failed"
            await self._update_run_status(
                run.id,
                final_status,
                execution.get("outputs", {}),
                execution.get("errors", []),
            )
            completed = await self.get_run(run.id)
            assert completed is not None
            completed.update(
                status=final_status,
                outputs=execution.get("outputs", {}),
                errors=execution.get("errors", []),
            )
            return completed
        except asyncio.CancelledError:
            logger.info("Workflow run {} was cancelled", run.id)
            errors = [{"type": "cancelled", "message": "用户取消执行"}]
            await self._update_run_status(run.id, "cancelled", errors=errors)
            completed = await self.get_run(run.id)
            assert completed is not None
            completed.update(status="cancelled", errors=errors)
            return completed
        except Exception as exc:
            logger.exception("Workflow execution error: {}", exc)
            await self._update_run_status(
                run.id,
                "failed",
                errors=[{"type": "engine_error", "message": str(exc)}],
            )
            raise
        finally:
            self._cancel_events.pop(run.id, None)
            self._running_workflows.pop(run.id, None)

    async def _execute_dag(
        self,
        definition: dict[str, Any],
        context: WorkflowExecutionContext,
    ) -> dict[str, Any]:
        context.check_cancelled()
        nodes = definition.get("nodes", [])
        if not nodes:
            return {"success": True, "outputs": {}, "errors": []}

        dag = nx.DiGraph()
        for node in nodes:
            dag.add_node(
                node["name"],
                config=node.get("config", {}),
                node_data=node,
            )
        for edge in definition.get("edges", []):
            dag.add_edge(edge["source"], edge["target"])
        if not nx.is_directed_acyclic_graph(dag):
            raise ValueError("Workflow contains circular dependencies")

        outputs: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        fatal_nodes: set[str] = set()
        processed = 0
        max_concurrency = max(1, min(int(context.variables.get("max_concurrency", 2)), 8))
        semaphore = asyncio.Semaphore(max_concurrency)

        async def execute_one(node_name: str) -> Any:
            async with semaphore:
                from ..runtime_coordinator import get_runtime_coordinator

                async with get_runtime_coordinator().lease(
                    "workflow", f"{context.run_id}:{node_name}"
                ):
                    node_info = dag.nodes[node_name]
                    return await self._execute_node_with_policy(
                        node_name,
                        node_info.get("config", {}),
                        node_info.get("node_data", {}),
                        outputs,
                        context,
                    )

        for generation in nx.topological_generations(dag):
            await self._check_cancelled(context)
            runnable: list[str] = []
            for node_name in generation:
                blocking = nx.ancestors(dag, node_name) & fatal_nodes
                if blocking:
                    self.db.add(
                        WorkflowStep(
                            run_id=context.run_id,
                            node_name=node_name,
                            order=processed,
                            status="skipped",
                            errors=[f"Blocked by failed dependency: {', '.join(sorted(blocking))}"],
                            started_at=datetime.now(),
                            completed_at=datetime.now(),
                        )
                    )
                    processed += 1
                else:
                    runnable.append(node_name)

            tasks = {name: asyncio.create_task(execute_one(name)) for name in runnable}
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for node_name, result in zip(tasks.keys(), results, strict=False):
                node_config = dag.nodes[node_name].get("config", {})
                started = datetime.now()
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, BaseException):
                    allowed = bool(node_config.get("allow_failure", False))
                    error = {
                        "node": node_name,
                        "error": str(result),
                        "allowed": allowed,
                    }
                    errors.append(error)
                    if not allowed:
                        fatal_nodes.add(node_name)
                    self.db.add(
                        WorkflowStep(
                            run_id=context.run_id,
                            node_name=node_name,
                            order=processed,
                            status="failed",
                            errors=[str(result)],
                            started_at=started,
                            completed_at=datetime.now(),
                        )
                    )
                else:
                    outputs[node_name] = result
                    context.outputs[node_name] = result
                    self.db.add(
                        WorkflowStep(
                            run_id=context.run_id,
                            node_name=node_name,
                            order=processed,
                            status="completed",
                            output_data=result,
                            started_at=started,
                            completed_at=datetime.now(),
                        )
                    )
                processed += 1

            progress = int(processed / len(nodes) * 100)
            current = ", ".join(generation)
            await self._update_run_progress(context.run_id, progress, current)
            await self.db.commit()

        return {
            "success": not fatal_nodes,
            "outputs": outputs,
            "errors": errors,
        }

    async def _check_cancelled(self, context: WorkflowExecutionContext) -> None:
        context.check_cancelled()
        result = await self.db.execute(
            select(WorkflowRun.status).where(WorkflowRun.id == context.run_id)
        )
        status = result.scalar_one_or_none()
        if status == "cancelled":
            raise asyncio.CancelledError(f"Workflow run {context.run_id} cancelled")

    async def _execute_node_with_policy(
        self,
        node_name: str,
        config: dict[str, Any],
        node_data: dict[str, Any],
        outputs: dict[str, Any],
        context: WorkflowExecutionContext,
    ) -> Any:
        retries = max(0, min(int(config.get("retries", 0)), 5))
        timeout = max(1.0, min(float(config.get("timeout_seconds", 300)), 3600.0))
        retry_delay = max(0.0, min(float(config.get("retry_delay_seconds", 0.5)), 30.0))

        for attempt in range(retries + 1):
            context.check_cancelled()
            execution = asyncio.create_task(
                asyncio.wait_for(
                    self._execute_node(node_name, config, node_data, outputs, context),
                    timeout=timeout,
                )
            )
            cancel_waiter = (
                asyncio.create_task(context.cancel_event.wait())
                if context.cancel_event is not None
                else None
            )
            try:
                if cancel_waiter is not None:
                    done, _ = await asyncio.wait(
                        {execution, cancel_waiter},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancel_waiter in done and context.cancel_event.is_set():
                        execution.cancel()
                        with suppress(asyncio.CancelledError):
                            await execution
                        raise asyncio.CancelledError(f"Workflow run {context.run_id} cancelled")
                return await execution
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt >= retries:
                    raise
                await asyncio.sleep(retry_delay * (2**attempt))
            finally:
                if cancel_waiter is not None:
                    cancel_waiter.cancel()
                    with suppress(asyncio.CancelledError):
                        await cancel_waiter
        raise RuntimeError(f"Node {node_name} exhausted retries")

    async def _execute_node(
        self,
        node_name: str,
        config: dict[str, Any],
        node_data: dict[str, Any],
        previous_outputs: dict[str, Any],
        context: WorkflowExecutionContext,
    ) -> Any:
        node_type = config.get("node_type") or node_data.get("node_type", "skill")
        if node_type == "skill":
            return await self._execute_skill_node(
                node_name, config, node_data, previous_outputs, context
            )
        if node_type == "plugin":
            return await self._execute_plugin_node(node_name, config, previous_outputs)
        if node_type == "input":
            input_name = config.get("input_name") or node_data.get("input_name") or node_name
            if input_name in context.inputs:
                return context.inputs[input_name]
            if config.get("required", False) and "default" not in config:
                raise ValueError(f"Required workflow input is missing: {input_name}")
            return self._resolve_value(config.get("default"), context, previous_outputs)
        if node_type == "output":
            mapping = config.get("outputs") or config.get("parameters")
            if mapping is None:
                return dict(previous_outputs)
            return self._resolve_value(mapping, context, previous_outputs)
        if node_type == "condition":
            left = self._resolve_value(
                config.get("left", config.get("value")), context, previous_outputs
            )
            operator = config.get("operator", "truthy")
            right = self._resolve_value(config.get("right"), context, previous_outputs)
            operations = {
                "truthy": lambda: bool(left),
                "equals": lambda: left == right,
                "not_equals": lambda: left != right,
                "in": lambda: left in right,
                "exists": lambda: left is not None,
            }
            if operator not in operations:
                raise ValueError(f"Unsupported condition operator: {operator}")
            return {"result": operations[operator]()}
        raise ValueError(f"Unknown workflow node type: {node_type}")

    async def _execute_skill_node(
        self,
        node_name: str,
        config: dict[str, Any],
        node_data: dict[str, Any],
        outputs: dict[str, Any],
        context: WorkflowExecutionContext,
    ) -> dict[str, Any]:
        skill_name = config.get("skill_name") or node_data.get("skill_name")
        if not skill_name:
            raise ValueError(f"Skill node missing skill_name: {node_name}")
        params = self._resolve_value(config.get("parameters", {}), context, outputs)
        from ..agents.skills import get_executor

        result = await get_executor().execute(skill_name, **params)
        if not result.success:
            raise ValueError(f"Skill execution failed: {result.error}")
        return result.output

    async def _execute_plugin_node(
        self,
        node_name: str,
        config: dict[str, Any],
        outputs: dict[str, Any],
    ) -> dict[str, Any]:
        plugin_name = config.get("plugin_name")
        if not plugin_name:
            raise ValueError(f"Plugin node missing plugin_name: {node_name}")
        raise RuntimeError(
            f"Plugin node '{plugin_name}' has no executable adapter. "
            "Use a registered skill node or add a validated plugin executor."
        )

    @classmethod
    def _resolve_value(
        cls,
        value: Any,
        context: WorkflowExecutionContext,
        outputs: dict[str, Any],
    ) -> Any:
        if isinstance(value, dict):
            return {key: cls._resolve_value(item, context, outputs) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._resolve_value(item, context, outputs) for item in value]
        if not isinstance(value, str):
            return value

        exact = cls._REFERENCE.match(value)
        if exact:
            return cls._resolve_reference(exact.group(1), context, outputs)

        def replace(match: re.Match[str]) -> str:
            return str(cls._resolve_reference(match.group(1), context, outputs))

        return cls._EMBEDDED_REFERENCE.sub(replace, value)

    @staticmethod
    def _resolve_reference(
        reference: str,
        context: WorkflowExecutionContext,
        outputs: dict[str, Any],
    ) -> Any:
        parts = [part for part in reference.split(".") if part]
        if not parts:
            raise ValueError("Workflow reference must not be empty")
        root = parts.pop(0)
        if root == "inputs":
            value: Any = context.inputs
        elif root == "variables":
            value = context.variables
        elif root in outputs:
            value = outputs[root]
        else:
            raise KeyError(f"Unknown workflow reference root: {root}")
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif isinstance(value, list | tuple) and part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                raise KeyError(f"Workflow reference path not found: {reference}")
        return value

    async def list_runs(
        self,
        workflow_id: int,
        limit: int = 20,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        query = select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id)
        if user_id is not None:
            query = query.where(WorkflowRun.user_id == user_id)
        result = await self.db.execute(query.order_by(WorkflowRun.created_at.desc()).limit(limit))
        return [self._run_to_dict(item) for item in result.scalars().all()]

    async def get_run(
        self,
        run_id: int,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        query = select(WorkflowRun).where(WorkflowRun.id == run_id)
        if user_id is not None:
            query = query.where(WorkflowRun.user_id == user_id)
        result = await self.db.execute(query)
        run = result.scalar_one_or_none()
        return self._run_to_dict(run) if run else None

    async def cancel_run(self, run_id: int, user_id: int | None = None) -> bool:
        query = select(WorkflowRun).where(WorkflowRun.id == run_id)
        if user_id is not None:
            query = query.where(WorkflowRun.user_id == user_id)
        result = await self.db.execute(query)
        run = result.scalar_one_or_none()
        # Preserve same-process cancellation for the tiny interval before the
        # transaction becomes visible to another request/session.
        cancel_event = self._cancel_events.get(run_id)
        if run is None and cancel_event is None:
            return False
        if run is not None and run.status not in {"running", "pending"}:
            return False
        if cancel_event is not None:
            cancel_event.set()
        if run is not None:
            await self._update_run_status(
                run_id,
                "cancelled",
                errors=[{"type": "cancelled", "message": "用户取消执行"}],
            )
        logger.info("Cancel signal sent for run {}", run_id)
        return True

    async def _update_run_status(
        self,
        run_id: int,
        status: str,
        outputs: dict[str, Any] | None = None,
        errors: list[Any] | None = None,
    ) -> None:
        now = datetime.now()
        update_data: dict[str, Any] = {"status": status, "completed_at": now}
        if outputs is not None:
            update_data["outputs"] = outputs
        if errors is not None:
            update_data["errors"] = errors
        result = await self.db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        run = result.scalar_one_or_none()
        if run and run.started_at:
            update_data["duration_seconds"] = (now - run.started_at).total_seconds()
        await self.db.execute(
            update(WorkflowRun).where(WorkflowRun.id == run_id).values(**update_data)
        )
        await self.db.commit()

    async def _update_run_progress(
        self,
        run_id: int,
        progress: int,
        current_node: str,
    ) -> None:
        await self.db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(progress=progress, current_node=current_node)
        )

    @staticmethod
    def _workflow_to_dict(workflow: Workflow) -> dict[str, Any]:
        return {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "category": workflow.category,
            "definition": workflow.definition,
            "variables": workflow.variables,
            "is_public": workflow.is_public,
            "status": workflow.status,
            "version": workflow.version,
            "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
            "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
        }

    @staticmethod
    def _run_to_dict(run: WorkflowRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "workflow_id": run.workflow_id,
            "status": run.status,
            "inputs": run.inputs or {},
            "outputs": run.outputs or {},
            "errors": run.errors or [],
            "progress": run.progress,
            "current_node": run.current_node,
            "duration_seconds": run.duration_seconds,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        }


__all__ = [
    "WorkflowEngine",
    "WorkflowExecutionContext",
    "WorkflowStatus",
    "StepStatus",
]
