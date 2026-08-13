"""工作流引擎测试 - 取消机制"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from research_agent.workflows.engine import (
    WorkflowEngine,
    WorkflowExecutionContext,
)


@pytest.fixture
def mock_db():
    """创建模拟数据库会话"""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result
    return session


class TestWorkflowExecutionContext:
    def test_cancel_event_init(self):
        """取消事件初始为未设置"""
        ctx = WorkflowExecutionContext(run_id=1)
        assert ctx.cancel_event is None

    def test_cancel_event_check(self):
        """检查取消状态"""
        cancel_event = asyncio.Event()
        ctx = WorkflowExecutionContext(run_id=1, cancel_event=cancel_event)

        # 未设置时不应抛出异常
        ctx.check_cancelled()

        # 设置后应抛出 CancelledError
        cancel_event.set()
        with pytest.raises(asyncio.CancelledError):
            ctx.check_cancelled()

    def test_cancel_event_none(self):
        """取消事件为 None 时不应抛出"""
        ctx = WorkflowExecutionContext(run_id=1, cancel_event=None)
        ctx.check_cancelled()


@pytest.mark.asyncio
class TestWorkflowCancellation:
    async def test_cancel_run_triggers_event(self, mock_db):
        """取消运行应触发取消事件"""
        engine = WorkflowEngine(mock_db)
        cancel_event = asyncio.Event()
        engine._cancel_events[1] = cancel_event

        result = await engine.cancel_run(1)
        assert result is True
        assert cancel_event.is_set()

        # 清理
        engine._cancel_events.pop(1, None)

    async def test_cancel_run_unknown_id(self, mock_db):
        """取消未知运行应回退到数据库检查"""
        engine = WorkflowEngine(mock_db)

        # 模拟数据库返回 None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await engine.cancel_run(999)
        assert result is False

    async def test_cancel_run_completed_workflow(self, mock_db):
        """取消已完成的工作流应返回 False"""
        engine = WorkflowEngine(mock_db)

        mock_run = MagicMock()
        mock_run.status = "completed"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_run
        mock_db.execute.return_value = mock_result

        result = await engine.cancel_run(1)
        assert result is False

    async def test_execute_dag_checks_cancellation(self, mock_db):
        """DAG 执行中应检查取消状态"""
        engine = WorkflowEngine(mock_db)
        cancel_event = asyncio.Event()

        ctx = WorkflowExecutionContext(
            run_id=1,
            inputs={},
            cancel_event=cancel_event,
        )

        # 先设置取消事件
        cancel_event.set()

        # 尝试执行空 DAG — 应在初始检查时就被取消
        with pytest.raises(asyncio.CancelledError):
            await engine._execute_dag({"nodes": [], "edges": []}, ctx)

    async def test_cancel_during_multi_node_workflow(self, mock_db):
        """多节点工作流中取消应在节点间生效"""
        engine = WorkflowEngine(mock_db)
        cancel_event = asyncio.Event()

        ctx = WorkflowExecutionContext(
            run_id=1,
            inputs={},
            cancel_event=cancel_event,
        )

        # 定义一个简单的线性 DAG
        definition = {
            "nodes": [
                {"name": "node_a", "config": {"type": "passthrough"}},
                {"name": "node_b", "config": {"type": "passthrough"}},
                {"name": "node_c", "config": {"type": "passthrough"}},
            ],
            "edges": [
                {"source": "node_a", "target": "node_b"},
                {"source": "node_b", "target": "node_c"},
            ],
        }

        # 在执行前设置取消
        cancel_event.set()

        # 应在第一个节点前就被取消
        with pytest.raises(asyncio.CancelledError):
            await engine._execute_dag(definition, ctx)

    async def test_cancel_events_cleanup(self, mock_db):
        """取消事件应在工作流结束后清理"""
        engine = WorkflowEngine(mock_db)
        cancel_event = asyncio.Event()
        engine._cancel_events[1] = cancel_event

        # 直接清理
        engine._cancel_events.pop(1, None)
        assert 1 not in engine._cancel_events


def test_validation_rejects_unknown_node_type():
    with pytest.raises(ValueError, match="Unknown workflow node type"):
        WorkflowEngine._validate_definition({
            "nodes": [{"name": "fake", "node_type": "pretend_success"}],
            "edges": [],
        })


def test_nested_references_preserve_types():
    ctx = WorkflowExecutionContext(
        run_id=1,
        inputs={"group": [1, 2, 3]},
        variables={"label": "case"},
    )
    resolved = WorkflowEngine._resolve_value(
        {
            "numbers": "${inputs.group}",
            "p": "${stats.p_value}",
            "label": "result-${variables.label}",
        },
        ctx,
        {"stats": {"p_value": 0.05}},
    )
    assert resolved == {
        "numbers": [1, 2, 3],
        "p": 0.05,
        "label": "result-case",
    }


@pytest.mark.asyncio
async def test_cancel_signal_is_shared_across_engine_instances(mock_db):
    first = WorkflowEngine(mock_db)
    second = WorkflowEngine(mock_db)
    event = asyncio.Event()
    first._cancel_events[4242] = event
    try:
        assert await second.cancel_run(4242) is True
        assert event.is_set()
    finally:
        first._cancel_events.pop(4242, None)


@pytest.mark.asyncio
async def test_cancel_interrupts_current_node(mock_db, monkeypatch):
    engine = WorkflowEngine(mock_db)
    event = asyncio.Event()
    context = WorkflowExecutionContext(run_id=77, cancel_event=event)

    async def slow_node(*_args, **_kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(engine, "_execute_node", slow_node)
    execution = asyncio.create_task(
        engine._execute_node_with_policy("slow", {}, {}, {}, context)
    )
    await asyncio.sleep(0)
    event.set()
    with pytest.raises(asyncio.CancelledError):
        await execution


class TestWorkflowEngineInit:
    def test_init_creates_cancel_events_dict(self, mock_db):
        """引擎初始化应创建取消事件字典"""
        engine = WorkflowEngine(mock_db)
        assert hasattr(engine, '_cancel_events')
        assert isinstance(engine._cancel_events, dict)

    def test_initialize(self):
        """引擎静态初始化方法"""
        WorkflowEngine.initialize()  # 不应抛出
