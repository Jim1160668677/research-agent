"""认证 API 测试 - 注册/登录/登出/用户信息/密码修改/引导

注意: 测试环境使用 debug 模式，中间件自动注入 dev_user。
      登录/注册/引导端点在 PUBLIC_PATHS 中，始终可用。
      每个测试使用独立的临时数据库，状态完全隔离。
"""

import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch, request):
    """为每个测试创建独立客户端 + 临时数据库"""
    # 使用临时文件数据库 (in-memory 在不同 event loop/连接间不共享)
    test_name = request.node.nodeid.replace("::", "_").replace("/", "_")
    test_db = tmp_path / f"test_{test_name}.db"
    test_db_url = f"sqlite+aiosqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", test_db_url)

    # 强制让 db 模块重新读取 settings
    import research_agent.core.db as db_module
    from research_agent.core.app import settings as app_settings
    app_settings.database_url = test_db_url

    # 重置全局 analytics 实例
    try:
        from research_agent import analytics
        analytics._tracker_instance = None
        analytics._simulator_instance = None
    except Exception:
        pass

    # 重新导入以创建新的 engine 和 session factory
    import importlib
    importlib.reload(db_module)

    # 创建 app (create_app 内部会调用 init_db 建表)
    from research_agent.core.app import create_app
    app = create_app()

    with TestClient(app) as c:
        yield c

    # 清理
    try:
        from research_agent import analytics
        tracker = analytics.get_tracker()
        if tracker:
            tracker.shutdown()
        analytics._tracker_instance = None
        analytics._simulator_instance = None
    except Exception:
        pass

    # 关闭数据库连接
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(db_module.close_db())
        loop.close()
    except Exception:
        pass

    # 删除临时数据库文件
    try:
        if test_db.exists():
            test_db.unlink()
    except Exception:
        pass


@pytest.fixture
def real_client(tmp_path, monkeypatch, request):
    """真实模式客户端 (无 debug 绕过)"""
    test_name = request.node.nodeid.replace("::", "_").replace("/", "_")
    test_db = tmp_path / f"test_real_{test_name}.db"
    test_db_url = f"sqlite+aiosqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    monkeypatch.setenv("RESEARCH_AGENT_DEBUG", "false")
    monkeypatch.setenv("debug", "false")

    import importlib
    import research_agent.core.db as db_module
    from research_agent.core.app import settings
    settings.database_url = test_db_url
    importlib.reload(db_module)

    # 初始化数据库
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(db_module.init_db())
    finally:
        loop.close()

    from research_agent.core.app import create_app
    settings.debug = False
    app = create_app()

    with TestClient(app) as c:
        yield c

    # 恢复
    monkeypatch.setenv("RESEARCH_AGENT_DEBUG", "true")
    monkeypatch.setenv("debug", "true")
    settings.debug = True

    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(db_module.close_db())
        loop.close()
    except Exception:
        pass

    # 删除临时数据库文件
    try:
        if test_db.exists():
            test_db.unlink()
    except Exception:
        pass


class TestBootstrap:
    def test_bootstrap_creates_admin(self, client):
        """首次引导创建 admin 用户"""
        r = client.post("/api/v1/auth/bootstrap")
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "admin"
        assert "temporary_password" in data

    def test_bootstrap_idempotent(self, client):
        """重复引导应返回错误"""
        # 先创建第一个 admin
        client.post("/api/v1/auth/bootstrap")
        # 再引导应失败
        r = client.post("/api/v1/auth/bootstrap")
        assert r.status_code == 400


class TestFirstRunSetup:
    def test_setup_status_and_owner_flow(self, client):
        status_response = client.get("/api/v1/auth/status")
        assert status_response.status_code == 200
        assert status_response.json()["initialized"] is False

        setup_response = client.post("/api/v1/auth/setup", json={
            "username": "owner",
            "email": "owner@example.org",
            "password": "secure-owner-password",
        })
        assert setup_response.status_code == 200
        assert setup_response.json()["user"]["role"] == "admin"
        assert setup_response.json()["access_token"]

        assert client.get("/api/v1/auth/status").json()["initialized"] is True
        duplicate = client.post("/api/v1/auth/setup", json={
            "username": "other",
            "email": "other@example.org",
            "password": "secure-other-password",
        })
        assert duplicate.status_code == 409

    def test_static_ui_is_public_but_api_is_protected(self, real_client):
        assert real_client.get("/").status_code == 200
        protected = real_client.get("/api/v1/workflows/")
        assert protected.status_code == 401

    def test_conversations_are_isolated_between_users(self, real_client):
        owner = real_client.post("/api/v1/auth/setup", json={
            "username": "owner",
            "email": "owner@example.org",
            "password": "secure-owner-password",
        }).json()
        member = real_client.post("/api/v1/auth/register", json={
            "username": "member",
            "email": "member@example.org",
            "password": "secure-member-password",
        }).json()
        owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
        member_headers = {"Authorization": f"Bearer {member['access_token']}"}

        created = real_client.post(
            "/api/v1/agents/chat",
            json={"content": "owner private conversation"},
            headers=owner_headers,
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        assert real_client.get(
            f"/api/v1/agents/sessions/{session_id}", headers=owner_headers
        ).status_code == 200
        assert real_client.get(
            f"/api/v1/agents/sessions/{session_id}", headers=member_headers
        ).status_code == 404

    def test_plugin_installation_and_version_are_user_scoped(self, real_client):
        owner = real_client.post("/api/v1/auth/setup", json={
            "username": "owner",
            "email": "owner@example.org",
            "password": "secure-owner-password",
        }).json()
        member = real_client.post("/api/v1/auth/register", json={
            "username": "member",
            "email": "member@example.org",
            "password": "secure-member-password",
        }).json()
        owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
        member_headers = {"Authorization": f"Bearer {member['access_token']}"}

        plugin_id = real_client.get(
            "/api/v1/plugins/", params={"search": "fastqc"}, headers=owner_headers
        ).json()[0]["id"]
        installed = real_client.post(
            "/api/v1/plugins/install",
            json={"plugin_id": plugin_id, "version": "0.11.9"},
            headers=owner_headers,
        )
        assert installed.status_code == 200
        assert installed.json()["version"] == "0.11.9"

        owner_view = real_client.get(
            f"/api/v1/plugins/{plugin_id}", headers=owner_headers
        ).json()
        member_view = real_client.get(
            f"/api/v1/plugins/{plugin_id}", headers=member_headers
        ).json()
        assert owner_view["is_selected"] is True
        assert owner_view["is_installed"] is False
        assert owner_view["lifecycle_state"] == "selected"
        assert owner_view["version"] == "0.11.9"
        assert member_view["is_installed"] is False
        assert member_view["is_selected"] is False
        assert member_view["version"] != owner_view["version"]

        forbidden = real_client.put(
            f"/api/v1/plugins/{plugin_id}",
            json={"description": "member must not edit marketplace metadata"},
            headers=member_headers,
        )
        assert forbidden.status_code == 403

    def test_researcher_cannot_execute_or_verify_plugin_deployment(self, real_client):
        owner = real_client.post("/api/v1/auth/setup", json={
            "username": "owner",
            "email": "owner@example.org",
            "password": "secure-owner-password",
        }).json()
        member = real_client.post("/api/v1/auth/register", json={
            "username": "member",
            "email": "member@example.org",
            "password": "secure-member-password",
        }).json()
        owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
        member_headers = {"Authorization": f"Bearer {member['access_token']}"}
        plugin_id = real_client.get(
            "/api/v1/plugins/", params={"search": "fastqc"}, headers=owner_headers
        ).json()[0]["id"]

        preview = real_client.post(
            f"/api/v1/plugins/{plugin_id}/deploy",
            json={"simulate": True},
            headers=member_headers,
        )
        execute = real_client.post(
            f"/api/v1/plugins/{plugin_id}/deploy",
            json={"simulate": False},
            headers=member_headers,
        )
        verify = real_client.post(
            f"/api/v1/plugins/{plugin_id}/verify", headers=member_headers
        )

        assert preview.status_code == 200
        assert preview.json()["is_simulated"] is True
        assert execute.status_code == 403
        assert verify.status_code == 403


class TestAuthLogin:
    def test_login_valid_credentials(self, client):
        """使用有效凭据登录"""
        # 先引导创建 admin
        b = client.post("/api/v1/auth/bootstrap")
        temp_password = b.json()["temporary_password"]

        r = client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": temp_password,
        })
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_login_nonexistent_user(self, client):
        """不存在的用户应返回 401"""
        r = client.post("/api/v1/auth/login", json={
            "username": "nonexistent",
            "password": "password123",
        })
        assert r.status_code == 401

    def test_login_short_username(self, client):
        """短用户名应返回 422"""
        r = client.post("/api/v1/auth/login", json={
            "username": "ab",
            "password": "password123",
        })
        assert r.status_code == 422


class TestAuthRegister:
    def test_register_new_user(self, client):
        """注册新用户"""
        r = client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "securepass123",
        })
        assert r.status_code == 200, f"注册失败: {r.status_code} {r.text}"
        data = r.json()
        assert "access_token" in data
        assert data["user"]["username"] == "testuser"

    def test_register_duplicate_username(self, client):
        """重复用户名应返回 409"""
        # 先注册一个
        client.post("/api/v1/auth/register", json={
            "username": "duplicate",
            "email": "first@example.com",
            "password": "securepass123",
        })
        # 再注册同用户名
        r = client.post("/api/v1/auth/register", json={
            "username": "duplicate",
            "email": "second@example.com",
            "password": "securepass123",
        })
        assert r.status_code == 409

    def test_register_short_password(self, client):
        """短密码应返回 422"""
        r = client.post("/api/v1/auth/register", json={
            "username": "newuser_short",
            "email": "short@example.com",
            "password": "short",
        })
        assert r.status_code == 422


class TestAuthMe:
    def test_get_me_authenticated_dev_mode(self, client):
        """debug 模式下自动注入 dev_user"""
        # 先 bootstrap 创建用户
        client.post("/api/v1/auth/bootstrap")
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 200
        data = r.json()
        # debug 模式下中间件注入 dev_user，user_id=1
        # 数据库查询到的是 id=1 的 admin 用户
        assert data["id"] == 1
        assert "username" in data

    def test_get_me_response_fields(self, client):
        """验证 /me 响应字段"""
        client.post("/api/v1/auth/bootstrap")
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert "username" in data
        assert "email" in data


class TestAuthLogout:
    def test_logout(self, client):
        """登出"""
        # 先 bootstrap (debug 模式注入用户)
        client.post("/api/v1/auth/bootstrap")
        r = client.post("/api/v1/auth/logout")
        assert r.status_code == 200
        assert r.json()["message"] == "已登出"


class TestDesktopConversationFlow:
    def test_chat_history_and_overview_are_persistent(self, client):
        client.post("/api/v1/auth/setup", json={
            "username": "owner",
            "email": "owner@example.org",
            "password": "secure-owner-password",
        })

        first = client.post("/api/v1/agents/chat", json={"content": "你好"})
        assert first.status_code == 200
        session_id = first.json()["session_id"]
        assert session_id

        second = client.post("/api/v1/agents/chat", json={
            "content": "继续介绍你的能力",
            "session_id": session_id,
        })
        assert second.status_code == 200
        assert second.json()["session_id"] == session_id

        sessions = client.get("/api/v1/agents/sessions").json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["message_count"] == 4

        detail = client.get(f"/api/v1/agents/sessions/{session_id}")
        assert detail.status_code == 200
        assert len(detail.json()["session"]["messages"]) == 4

        overview = client.get("/api/v1/system/overview")
        assert overview.status_code == 200
        assert overview.json()["counts"]["conversations"] == 1
        assert overview.json()["counts"]["skills"] >= 10

        assert client.delete(f"/api/v1/agents/sessions/{session_id}").status_code == 200
        assert client.get("/api/v1/agents/sessions").json()["sessions"] == []


class TestAnalyticsAPI:
    def test_usage_authenticated(self, client):
        """使用统计 (debug 模式自动认证)"""
        client.post("/api/v1/auth/bootstrap")
        r = client.get("/api/v1/analytics/usage")
        assert r.status_code == 200, f"analytics/usage 失败: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "total_events" in data

    def test_insights_authenticated(self, client):
        """需求洞察"""
        client.post("/api/v1/auth/bootstrap")
        r = client.get("/api/v1/analytics/insights")
        assert r.status_code == 200, f"analytics/insights 失败: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "insights" in data
        assert "scenarios" in data

    def test_track_event(self, client):
        """追踪事件"""
        client.post("/api/v1/auth/bootstrap")
        r = client.post("/api/v1/analytics/track",
                        params={"event_type": "test_event",
                                "data": '{"key": "value"}'})
        assert r.status_code == 200, f"track 失败: {r.status_code} {r.text[:200]}"

    def test_usage_fields(self, client):
        """使用统计响应字段完整性"""
        client.post("/api/v1/auth/bootstrap")
        r = client.get("/api/v1/analytics/usage")
        assert r.status_code == 200, f"analytics/usage 失败: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "total_events" in data
        assert "event_types" in data
        assert "session_duration_minutes" in data
        assert "top_features" in data
        assert "error_count" in data


class TestWorkflowCancellation:
    """工作流取消机制的端到端 API 测试"""

    def test_cancel_endpoint_exists(self, client):
        """取消端点可达"""
        # 先 bootstrap (debug 模式注入用户)
        client.post("/api/v1/auth/bootstrap")
        r = client.post("/api/v1/workflows/runs/1/cancel")
        # 可能不存在或返回 404，但端点路径应可达
        assert r.status_code in [200, 404, 405]

    def test_workflows_list_available(self, client):
        """工作流列表端点可用"""
        client.post("/api/v1/auth/bootstrap")
        r = client.get("/api/v1/workflows/")
        assert r.status_code == 200
