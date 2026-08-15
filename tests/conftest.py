"""共享测试fixtures"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# 确保 src 在导入路径
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

# 测试环境配置 (在导入任何模块之前设置)
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("debug", "true")
os.environ.setdefault("RESEARCH_AGENT_DEBUG", "true")


@pytest.fixture
def mock_db_session():
    """创建模拟数据库会话"""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    session.close = MagicMock()

    # 默认查询返回空
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result
    return session


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    """为每个测试隔离数据库与 analytics 状态

    - 将数据库切换到临时 sqlite 文件
    - 重置全局 analytics tracker/simulator
    - 清理后恢复
    """
    # 使用临时数据库
    test_db = tmp_path / "test_research_agent.db"
    test_db_url = f"sqlite+aiosqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    monkeypatch.setattr("research_agent.core.app.settings.database_url", test_db_url)
    from research_agent.core.db import configure_database
    configure_database(test_db_url)

    # Provider tests must never inherit workstation credentials or make paid
    # network requests accidentally. Individual tests opt in with mock keys.
    for provider, env_name in {
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "agnes": "AGNES_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }.items():
        monkeypatch.delenv(env_name, raising=False)
        monkeypatch.setattr(f"research_agent.core.app.settings.{provider}_api_key", "")

    # 重置全局 analytics 实例
    try:
        from research_agent import analytics
        analytics._tracker_instance = None
        analytics._simulator_instance = None
    except Exception:
        pass

    yield

    # 关闭所有可能的 tracker
    try:
        from research_agent import analytics
        tracker = analytics.get_tracker()
        if tracker:
            tracker.shutdown()
        analytics._tracker_instance = None
        analytics._simulator_instance = None
    except Exception:
        pass
