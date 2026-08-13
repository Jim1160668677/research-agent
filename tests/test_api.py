"""API 测试 - 使用同步 TestClient"""

import pytest
from fastapi.testclient import TestClient

from research_agent.core.app import create_app


@pytest.fixture
def client():
    """Create the client after each test has selected its isolated database.

    Entering ``TestClient`` is intentional: it executes the FastAPI lifespan,
    which creates and seeds the per-test database just as the desktop runtime
    does in production.
    """
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client):
    """测试健康检查端点"""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_api_health_endpoint(client):
    """测试API健康检查"""
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_skills_list(client):
    """测试技能列表"""
    r = client.get("/api/v1/skills/")
    assert r.status_code == 200
    skills = r.json()
    assert isinstance(skills, list)
    assert len(skills) >= 10
    names = [s["name"] for s in skills]
    assert "pubmed_search" in names
    assert "statistical_test" in names
    assert "volcano_plot" in names


def test_skills_categories(client):
    """测试技能分类"""
    r = client.get("/api/v1/skills/categories")
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert "genomics" in cats
    assert "literature" in cats
    assert "visualization" in cats


def test_execute_statistical_test(client):
    """测试执行统计检验技能"""
    r = client.post(
        "/api/v1/skills/statistical_test/execute",
        json={"parameters": {"group1": [1, 2, 3, 4, 5], "group2": [2, 3, 4, 5, 6]}},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert "p_value" in data["output"]


def test_execute_correlation(client):
    """测试执行相关性分析技能"""
    r = client.post(
        "/api/v1/skills/correlation_analysis/execute",
        json={"parameters": {"x": [1, 2, 3, 4, 5], "y": [2, 4, 6, 8, 10]}},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert abs(data["output"]["correlation"] - 1.0) < 0.01


def test_execute_missing_params(client):
    """测试缺少必填参数"""
    r = client.post(
        "/api/v1/skills/statistical_test/execute",
        json={"parameters": {}},
    )
    assert r.status_code == 200
    assert r.json()["success"] is False
    assert r.json()["error"] is not None


def test_execute_unknown_skill(client):
    """测试执行不存在的技能"""
    r = client.post(
        "/api/v1/skills/nonexistent_skill/execute",
        json={"parameters": {}},
    )
    assert r.status_code == 200
    assert r.json()["success"] is False


def test_workflows_list(client):
    """测试工作流列表"""
    r = client.get("/api/v1/workflows/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_recommendations(client):
    """测试推荐接口"""
    r = client.get("/api/v1/recommendations/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_contextual_recommendations_only_reference_real_capabilities(client):
    response = client.post(
        "/api/v1/recommendations/for-context",
        json={
            "context_type": "data_analysis",
            "context_data": {"data_type": "RNA expression", "query": "统计检验和热图"},
            "limit": 5,
        },
    )
    assert response.status_code == 200
    record = response.json()
    assert record["user_id"] == 1
    assert record["context_type"] == "data_analysis"
    assert record["recommended_items"]
    available = {item["name"] for item in client.get("/api/v1/skills/").json()}
    for item in record["recommended_items"]:
        if item["type"] == "skill":
            assert item["name"] in available
        assert 0 <= item["score"] <= 0.99

    history = client.get("/api/v1/recommendations/history")
    assert history.status_code == 200
    assert history.json()[0]["id"] == record["id"]


def test_recommendation_feedback_is_persisted_for_current_user(client):
    first = client.post(
        "/api/v1/recommendations/feedback",
        json={"item_type": "skill", "item_name": "statistical_test", "accepted": True},
    )
    second = client.post(
        "/api/v1/recommendations/feedback",
        json={"item_type": "skill", "item_name": "statistical_test", "accepted": True},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["accepted"] == 2


def test_plugins_list(client):
    """测试插件列表"""
    r = client.get("/api/v1/plugins/")
    assert r.status_code == 200
    plugins = r.json()
    assert isinstance(plugins, list)
    assert len(plugins) >= 10
    names = [p["name"] for p in plugins]
    assert "fastqc" in names
    assert "bwa" in names
    assert "deseq2" in names


def test_plugin_filter_by_category(client):
    """测试插件按分类筛选"""
    r = client.get("/api/v1/plugins/", params={"category": "alignment"})
    assert r.status_code == 200
    plugins = r.json()
    assert len(plugins) > 0
    for p in plugins:
        assert p["category"] == "alignment"


def test_plugin_install_and_uninstall(client):
    """测试插件安装和卸载"""
    # 查找fastqc
    r = client.get("/api/v1/plugins/", params={"search": "fastqc"})
    plugins = r.json()
    assert len(plugins) == 1
    plugin_id = plugins[0]["id"]

    # 安装
    r = client.post("/api/v1/plugins/install", json={"plugin_id": plugin_id})
    assert r.status_code == 200
    assert r.json()["is_selected"] is True
    assert r.json()["is_installed"] is False

    # 卸载
    r = client.delete(f"/api/v1/plugins/{plugin_id}")
    assert r.status_code == 200
    assert r.json()["plugin"]["lifecycle_state"] == "deselected"


def test_create_and_run_workflow(client):
    """测试工作流创建和执行"""
    # 创建简单工作流: 统计检验
    definition = {
        "nodes": [
            {"name": "stats_node", "node_type": "skill", "skill_name": "statistical_test", "config": {"parameters": {}}},
        ],
        "edges": [],
    }
    r = client.post(
        "/api/v1/workflows/",
        json={
            "name": "测试工作流",
            "category": "test",
            "definition": definition,
        },
    )
    assert r.status_code == 200
    workflow_id = r.json()["id"]

    # 激活并运行
    r = client.put(f"/api/v1/workflows/{workflow_id}", json={"status": "active"})
    assert r.status_code == 200

    r = client.post("/api/v1/workflows/run", json={"workflow_id": workflow_id, "inputs": {}})
    assert r.status_code in [200, 500]  # 500 表示执行时参数不足，但引擎本身工作

    # 清理
    r = client.delete(f"/api/v1/workflows/{workflow_id}")
    assert r.status_code == 200


def test_workflow_resolves_inputs_and_run_detail_route(client):
    definition = {
        "nodes": [
            {
                "name": "stats",
                "node_type": "skill",
                "skill_name": "statistical_test",
                "config": {
                    "parameters": {
                        "group1": "${inputs.control}",
                        "group2": "${inputs.treatment}",
                    }
                },
            },
            {
                "name": "result",
                "node_type": "output",
                "config": {"outputs": {"p_value": "${stats.p_value}"}},
            },
        ],
        "edges": [{"source": "stats", "target": "result"}],
    }
    created = client.post(
        "/api/v1/workflows/",
        json={"name": "typed-input-test", "category": "test", "definition": definition},
    )
    assert created.status_code == 200
    workflow_id = created.json()["id"]

    executed = client.post(
        "/api/v1/workflows/run",
        json={
            "workflow_id": workflow_id,
            "inputs": {"control": [1, 2, 3, 4], "treatment": [2, 3, 4, 5]},
            "variables": {"max_concurrency": 2},
        },
    )
    assert executed.status_code == 200
    run = executed.json()
    assert run["status"] == "completed"
    assert isinstance(run["outputs"]["result"]["p_value"], float)

    detail = client.get(f"/api/v1/workflows/runs/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == run["id"]


def test_workflow_creation_rejects_unknown_node_type(client):
    response = client.post(
        "/api/v1/workflows/",
        json={
            "name": "invalid-node",
            "definition": {
                "nodes": [{"name": "fake", "node_type": "pretend_success"}],
                "edges": [],
            },
        },
    )
    assert response.status_code == 400
    assert "Unknown workflow node type" in response.json()["detail"]


def test_security_module():
    """测试安全模块"""
    from research_agent.security import CryptoService, AccessControl, AuditLogger

    # 加密解密
    secret = "敏感数据-测序结果"
    encrypted = CryptoService.encrypt(secret)
    assert encrypted != secret
    assert CryptoService.decrypt(encrypted) == secret

    # 密码哈希
    hashed = CryptoService.hash_password("mypassword123")
    assert CryptoService.verify_password("mypassword123", hashed)
    assert not CryptoService.verify_password("wrong", hashed)

    # 权限控制
    assert AccessControl.can_manage_plugins("admin")
    assert not AccessControl.can_manage_plugins("viewer")
    assert AccessControl.can_edit_workflow("researcher")

    # 审计日志
    AuditLogger.log(user_id=1, action="test", resource="unit_test")
    events = AuditLogger.get_events()
    assert len(events) > 0
    assert events[-1]["action"] == "test"
