"""LLM模块与多智能体系统测试"""

import sys
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, "src")


# ========== LLM Provider ==========

def test_provider_registry():
    """测试Provider注册表"""
    from research_agent.llm.provider import PROVIDER_REGISTRY, get_provider

    assert "openai" in PROVIDER_REGISTRY
    assert "anthropic" in PROVIDER_REGISTRY
    assert "google" in PROVIDER_REGISTRY

    with pytest.raises(ValueError):
        get_provider("nonexistent")


def test_provider_instances():
    """测试Provider实例创建"""
    from research_agent.llm.provider import get_provider

    p = get_provider("openai", api_key="sk-test123456789")
    assert p.name == "openai"
    assert p.model != ""
    assert p._mask_key().startswith("sk-tes")


def test_provider_mask_key():
    """测试Key掩码"""
    from research_agent.llm.provider import OpenAIProvider

    p = OpenAIProvider(api_key="sk-test1234567890")
    masked = p._mask_key()
    assert "test" not in masked.replace("sk-", "")
    assert masked.endswith("7890")
    assert masked.startswith("sk-tes")


def test_openai_connection_check():
    """测试OpenAI连接检查"""
    from research_agent.llm.provider import OpenAIProvider

    assert OpenAIProvider(api_key="").check_connection() is False
    assert OpenAIProvider(api_key="sk-valid-key-123456").check_connection() is True


def test_anthropic_connection_check():
    """测试Anthropic连接检查"""
    from research_agent.llm.provider import AnthropicProvider

    assert AnthropicProvider(api_key="sk-ant-1234567890").check_connection() is True


@pytest.mark.asyncio
async def test_google_provider_uses_current_genai_async_client(monkeypatch):
    """The Gemini adapter targets the supported ``google.genai`` SDK API."""
    from google import genai
    from research_agent.llm.provider import GeminiProvider, LLMMessage

    usage = MagicMock(
        prompt_token_count=4,
        candidates_token_count=3,
        total_token_count=7,
    )
    response = MagicMock(text="gemini response", usage_metadata=usage)
    generate_content = AsyncMock(return_value=response)
    fake_client = MagicMock()
    fake_client.aio.models.generate_content = generate_content
    monkeypatch.setattr(genai, "Client", lambda **_: fake_client)

    provider = GeminiProvider(api_key="google-test-key-12345", model="gemini-test")
    result = await provider.chat([LLMMessage(role="user", content="hello")])

    assert result.content == "gemini response"
    assert result.usage["total_tokens"] == 7
    generate_content.assert_awaited_once()


# ========== API Key Manager ==========

def test_mask_key():
    """测试Key掩码静态方法"""
    from research_agent.llm.keys import APIKeyManager

    assert APIKeyManager.mask_key("") == ""
    assert APIKeyManager.mask_key("short") == "*****"
    masked = APIKeyManager.mask_key("sk-abcdefghijklmnop")
    assert masked.endswith("mnop")


@pytest.mark.asyncio
async def test_memory_key_manager():
    """测试内存Key管理器 (无DB)"""
    from research_agent.llm.keys import APIKeyManager

    manager = APIKeyManager(db=None)
    await manager.save_key("openai", "sk-test-1234567890")
    key = await manager.get_key("openai")
    assert key == "sk-test-1234567890"

    # 不支持的provider
    with pytest.raises(ValueError):
        await manager.save_key("unknown_provider", "xxx")


@pytest.mark.asyncio
async def test_env_var_fallback():
    """测试环境变量回退"""
    import os
    from research_agent.llm.keys import APIKeyManager

    os.environ["OPENAI_API_KEY"] = "sk-env-1234567890"
    manager = APIKeyManager(db=None)
    key = await manager.get_key("openai")
    assert key == "sk-env-1234567890"
    os.environ.pop("OPENAI_API_KEY", None)


@pytest.mark.asyncio
async def test_db_key_manager(mock_db_session):
    """测试数据库Key管理器"""
    from research_agent.llm.keys import APIKeyManager
    from research_agent.security import CryptoService

    # 模拟数据库记录
    mock_record = MagicMock()
    mock_record.encrypted_key = CryptoService.encrypt("sk-db-1234567890")
    mock_record.is_active = True

    async def fake_execute(query):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_record
        return mock_result
    mock_db_session.execute = fake_execute

    manager = APIKeyManager(db=mock_db_session)
    key = await manager.get_key("openai")
    assert key == "sk-db-1234567890"


@pytest.mark.asyncio
async def test_list_keys_status():
    """测试Key列表状态"""
    import os
    from research_agent.llm.keys import APIKeyManager

    os.environ["OPENAI_API_KEY"] = "sk-env-test-123456"
    manager = APIKeyManager(db=None)
    keys = await manager.list_keys()
    status = {k["provider"]: k["configured"] for k in keys}
    assert status["openai"] is True
    assert status["anthropic"] is False
    os.environ.pop("OPENAI_API_KEY", None)


# ========== Chat Engine ==========

@pytest.mark.asyncio
async def test_chat_engine_no_key():
    """测试无Key时ChatEngine报错"""
    import os
    from research_agent.llm.chat import ChatEngine

    for env in [
        "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "AGNES_API_KEY",
        "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    ]:
        os.environ.pop(env, None)

    engine = ChatEngine(provider_name="openai", db=None)
    with pytest.raises(RuntimeError) as exc:
        await engine.chat("hello")
    assert "API Key" in str(exc.value)


@pytest.mark.asyncio
async def test_chat_engine_status_no_config():
    """测试状态检查无配置"""
    import os
    from research_agent.llm.chat import ChatEngine

    for env in [
        "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "AGNES_API_KEY",
        "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    ]:
        os.environ.pop(env, None)

    engine = ChatEngine(provider_name="openai", db=None)
    status = await engine.check_status()
    assert status["configured"] is False
    assert status["success"] is False


@pytest.mark.asyncio
async def test_chat_engine_mock_provider():
    """测试ChatEngine使用mock provider"""
    from research_agent.llm.chat import ChatEngine
    from research_agent.llm.provider import LLMProvider, LLMMessage, LLMResponse

    class MockProvider(LLMProvider):
        name = "openai"
        display_name = "Mock"
        models = ["mock-model"]
        async def chat(self, messages, **kwargs):
            return LLMResponse(content="mock回复", provider="openai", model="mock-model")
        def check_connection(self): return True

    engine = ChatEngine(provider_name="openai", db=None)
    # 注入mock
    engine._get_provider = AsyncMock(return_value=MockProvider(api_key="x"))

    result = await engine.chat("测试消息")
    assert result["success"] is True
    assert result["response"] == "mock回复"
    assert result["provider"] == "openai"


def test_chat_engine_history():
    """测试对话历史记录"""
    import asyncio
    from research_agent.llm.chat import ChatEngine

    engine = ChatEngine(provider_name="openai", db=None)
    engine._conversation_history.append({"role": "user", "content": "a"})
    engine._conversation_history.append({"role": "assistant", "content": "b"})
    history = engine.get_history()
    assert len(history) == 2
    engine.clear_history()
    assert len(engine.get_history()) == 0


# ========== Multi-Agent ==========

@pytest.mark.asyncio
async def test_coordinator_routing():
    """测试路由决策"""
    from research_agent.agents.multi_agent import CoordinatorAgent

    coordinator = CoordinatorAgent(use_llm=False)
    state = {"user_message": "搜索关于CRISPR的文献"}
    assert coordinator.route(state) == "literature"

    state = {"user_message": "帮我分析SRA测序数据"}
    assert coordinator.route(state) == "data"

    state = {"user_message": "做差异表达分析"}
    assert coordinator.route(state) == "analysis"

    state = {"user_message": "渲染蛋白质结构"}
    assert coordinator.route(state) == "visualization"


@pytest.mark.asyncio
async def test_literature_agent():
    """测试文献智能体"""
    from research_agent.agents.multi_agent import LiteratureAgent

    agent = LiteratureAgent()
    state = {"user_message": "搜索关于CRISPR的文献", "results": {}}
    result = await agent.run(state)
    # 可能网络不可用，但应返回结构化结果
    assert "literature" in result["results"]


@pytest.mark.asyncio
async def test_analysis_agent():
    """测试分析智能体"""
    from research_agent.agents.multi_agent import AnalysisAgent

    agent = AnalysisAgent()
    state = {"user_message": "请给实验设计方案", "results": {}}
    result = await agent.run(state)
    assert "analysis" in result["results"]


@pytest.mark.asyncio
async def test_data_agent_genbank():
    """测试数据智能体GenBank分支"""
    from research_agent.agents.multi_agent import DataAgent

    agent = DataAgent()
    state = {"user_message": "获取基因序列 NM_001301714", "results": {}}
    result = await agent.run(state)
    assert "data" in result["results"]


@pytest.mark.asyncio
async def test_visualization_agent():
    """测试可视化智能体"""
    from research_agent.agents.multi_agent import VisualizationAgent

    agent = VisualizationAgent()
    state = {"user_message": "渲染蛋白质结构 pymol", "results": {}}
    result = await agent.run(state)
    assert "visualization" in result["results"]


@pytest.mark.asyncio
async def test_full_coordinator_run():
    """测试完整多智能体协作流程"""
    from research_agent.agents.multi_agent import CoordinatorAgent

    coordinator = CoordinatorAgent(use_llm=False)
    result = await coordinator.run("请给实验设计方案")
    assert result["success"] is True
    assert "response" in result
    assert "analysis" in result["agents_used"]
    assert "skills_used" in result
    assert "suggestions" in result


# ========== 集成测试 ==========

@pytest.fixture
def api_client():
    """Run application lifespan so the isolated database is initialized."""
    from fastapi.testclient import TestClient
    from research_agent.core.app import create_app

    with TestClient(create_app()) as client:
        yield client


def test_llm_api_routes_registered(api_client):
    """测试LLM API路由注册"""
    client = api_client

    r = client.get("/api/v1/llm/status")
    assert r.status_code == 200
    data = r.json()
    assert "providers" in data
    assert "openai" in data["providers"]

    r = client.get("/api/v1/llm/keys")
    assert r.status_code == 200
    assert "keys" in r.json()


def test_multi_agent_api(api_client):
    """测试多智能体API"""
    client = api_client

    r = client.get("/api/v1/agents/multi-agent/status")
    assert r.status_code == 200
    data = r.json()
    assert data["architecture"] == "LangGraph StateGraph"
    assert len(data["specialists"]) == 4

    r = client.post("/api/v1/agents/multi-agent", json={"content": "请给实验设计方案"})
    assert r.status_code == 200
    assert "message" in r.json()


def test_docking_api_routes(api_client):
    """测试对接API路由"""
    client = api_client

    r = client.get("/api/v1/docking/engines")
    assert r.status_code == 200
    engines = r.json()["engines"]
    names = [e["name"] for e in engines]
    assert "autodock_vina" in names
    assert "glide" in names
    assert "gold" in names

    r = client.get("/api/v1/docking/structure/tools")
    assert r.status_code == 200
    tools = r.json()["tools"]
    names = [t["name"] for t in tools]
    assert "pymol" in names
    assert "chimerax" in names

    r = client.get("/api/v1/docking/engines/autodock_vina")
    assert r.status_code == 200
    assert r.json()["name"] == "autodock_vina"

    r = client.get("/api/v1/docking/engines/nonexistent")
    assert r.status_code == 404


def test_save_key_api(api_client):
    """测试Key保存API"""
    client = api_client

    r = client.post("/api/v1/llm/keys", json={
        "provider": "openai",
        "api_key": "sk-test-mocked-123456",
    })
    assert r.status_code == 200
    assert r.json()["success"] is True
    masked = r.json()["key"]["key_masked"]
    assert "sk-tes" in masked
    assert "mocked" not in masked


def test_save_key_invalid_provider(api_client):
    """测试无效Provider"""
    client = api_client

    r = client.post("/api/v1/llm/keys", json={
        "provider": "invalid",
        "api_key": "sk-test-mocked-123456",
    })
    assert r.status_code == 400


def test_delete_key_api(api_client):
    """测试删除Key API"""
    client = api_client

    # 保存后再删除
    client.post("/api/v1/llm/keys", json={
        "provider": "anthropic",
        "api_key": "sk-ant-mocked-123456",
    })
    r = client.delete("/api/v1/llm/keys/anthropic")
    assert r.status_code == 200


def test_chat_api_missing_key(api_client):
    """测试无Key时chat API返回400"""
    import os
    for env in [
        "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "AGNES_API_KEY",
        "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    ]:
        os.environ.pop(env, None)
    client = api_client

    # 清理数据库中的key (避免前序测试污染)
    client.delete("/api/v1/llm/keys/openai")
    client.delete("/api/v1/llm/keys/anthropic")
    client.delete("/api/v1/llm/keys/google")
    client.delete("/api/v1/llm/keys/deepseek")
    client.delete("/api/v1/llm/keys/agnes")

    r = client.post("/api/v1/llm/chat", json={"message": "hello"})
    assert r.status_code == 400
    assert "API Key" in r.json()["detail"]
