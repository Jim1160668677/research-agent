"""插件市场测试 - 版本控制/依赖解析/一键部署/评价/更新机制"""

import os
import pytest
from fastapi.testclient import TestClient

from research_agent.core.app import create_app
from research_agent.plugins.dependency_resolver import DependencyResolver, VersionSpec


# ========== 单元测试: 版本约束 ==========

class TestVersionSpec:
    def test_ge(self):
        assert VersionSpec(">=1.2").matches("1.3.0")
        assert VersionSpec(">=1.2").matches("1.2.5")
        assert not VersionSpec(">=1.2").matches("1.1.9")

    def test_range(self):
        spec = VersionSpec(">=2.0,<3.0")
        assert spec.matches("2.5.1")
        assert not spec.matches("3.0.0")
        assert not spec.matches("1.9.9")

    def test_exact(self):
        assert VersionSpec("==1.2.5").matches("1.2.5")
        assert not VersionSpec("==1.2.5").matches("1.2.6")

    def test_empty_spec_matches_any(self):
        assert VersionSpec("").matches("anything")

    def test_simple_number(self):
        assert VersionSpec(">=8").matches("17.0.8")
        assert not VersionSpec(">=8").matches("7")


# ========== 单元测试: 依赖解析器 ==========

def _fake_get(registry, installed):
    async def get(name):
        p = registry.get(name)
        if p is None:
            return None
        return {
            "name": name,
            "version": p.get("version", "1.0.0"),
            "dependencies": p.get("deps", []),
            "is_installed": name in installed,
        }
    return get


class TestDependencyResolver:
    async def test_transitive_closure(self):
        """A → B → C, 传递依赖全部解析"""
        registry = {
            "a": {"deps": [{"name": "b", "version": ">=1.0"}], "version": "1.0.0"},
            "b": {"deps": [{"name": "c", "version": ">=2.0"}], "version": "1.5.0"},
            "c": {"deps": [], "version": "2.1.0"},
        }
        resolver = DependencyResolver(_fake_get(registry, installed={"c"}))
        result = await resolver.resolve("a")
        assert result["total"] == 3
        assert result["order"] == ["b", "a"]  # b缺失, a缺失; c已装
        assert [m["name"] for m in result["missing"]] == ["b", "a"]
        assert [s["name"] for s in result["satisfied"]] == ["c"]
        assert result["cycle"] is None
        assert result["conflicts"] == []

    async def test_dependency_install_order(self):
        """安装顺序: 依赖先于根插件"""
        registry = {
            "tool": {"deps": [{"name": "lib1"}, {"name": "lib2"}], "version": "3.0"},
            "lib1": {"deps": [{"name": "lib3"}], "version": "1.0"},
            "lib2": {"deps": [], "version": "2.0"},
            "lib3": {"deps": [], "version": "1.1"},
        }
        resolver = DependencyResolver(_fake_get(registry, installed=set()))
        result = await resolver.resolve("tool")
        order = result["order"]
        assert order.index("lib3") < order.index("lib1") < order.index("tool")
        assert order.index("lib2") < order.index("tool")

    async def test_cycle_detection(self):
        """循环依赖检测"""
        registry = {
            "a": {"deps": [{"name": "b"}]},
            "b": {"deps": [{"name": "a"}]},
        }
        resolver = DependencyResolver(_fake_get(registry, installed=set()))
        result = await resolver.resolve("a")
        assert result["cycle"] is not None
        assert "a" in result["cycle"] and "b" in result["cycle"]

    async def test_version_conflict(self):
        """版本冲突检测: 两个插件要求互斥的依赖版本"""
        registry = {
            "root": {"deps": [{"name": "x", "version": ">=2.0"}, {"name": "y", "version": ""}], "version": "1.0"},
            "x": {"deps": [], "version": "2.1.0"},
            "y": {"deps": [{"name": "x", "version": "<2.0"}], "version": "1.0"},
        }
        resolver = DependencyResolver(_fake_get(registry, installed={"x", "y"}))
        result = await resolver.resolve("root")
        assert result["conflicts"], "应当检测到 x 版本冲突"
        conflict = result["conflicts"][0]
        assert conflict["dependency"] in ("x",)
        assert "y" in conflict["required_by"]

    async def test_dependency_not_in_market(self):
        """依赖不在插件市场中"""
        registry = {
            "root": {"deps": [{"name": "ghost"}], "version": "1.0"},
        }
        resolver = DependencyResolver(_fake_get(registry, installed={"root"}))
        result = await resolver.resolve("root")
        missing = result["missing"]
        assert any(m["name"] == "ghost" and m["reason"] == "not_in_market" for m in missing)


# ========== 单元测试: 一键部署 (计划生成) ==========

def _make_plugin(**over):
    from research_agent.core.models.db import Plugin
    base = dict(
        name="tool", version="1.0", install_method={"method": "manual"},
        os_compatibility=[], config_schema={}, dependencies=[], source_url="https://example.com",
        docs_url=None, homepage=None,
    )
    base.update(over)
    return Plugin(**base)


class TestDeployerPlan:
    def test_conda_plan(self):
        from research_agent.plugins.deployer import Deployer
        p = _make_plugin(install_method={"method": "conda", "package": "autodock-vina", "channel": "conda-forge"})
        deployer = Deployer.__new__(Deployer)
        deployer.os_name = "linux"
        deployer.tools_available = lambda: {"conda": True, "mamba": False, "pip": True, "git": False}
        plan = deployer.build_plan(p)
        assert plan["supported"] is True
        run_step = next(s for s in plan["steps"] if s["action"] == "run")
        assert "conda" in run_step["command"]
        assert run_step["argv"][:3] == ["conda", "create", "-y"]
        assert "-p" in run_step["argv"]
        assert "base" not in run_step["argv"]
        assert plan["environment_prefix"].endswith("plugin-tool-1.0")

    def test_pip_plan_creates_a_dedicated_virtual_environment(self):
        from research_agent.plugins.deployer import Deployer
        p = _make_plugin(install_method={"method": "pip", "package": "paper-qa==5.0.0"})
        deployer = Deployer.__new__(Deployer)
        deployer.os_name = "linux"
        deployer.tools_available = lambda: {}

        plan = deployer.build_plan(p)

        run_steps = [step for step in plan["steps"] if step["action"] == "run"]
        assert len(run_steps) == 2
        assert run_steps[0]["argv"][1:3] == ["-m", "venv"]
        assert run_steps[1]["argv"][-4:] == ["-m", "pip", "install", "paper-qa==5.0.0"]
        assert all(step["env"]["prefix"] == plan["environment_prefix"] for step in run_steps)

    def test_catalog_command_injection_is_rejected(self):
        from research_agent.plugins.deployer import Deployer
        p = _make_plugin(
            install_method={
                "method": "conda",
                "package": "fastqc; Remove-Item important",
                "channel": "bioconda",
            }
        )
        deployer = Deployer.__new__(Deployer)
        deployer.os_name = "linux"
        deployer.tools_available = lambda: {"conda": True}

        with pytest.raises(ValueError, match="Invalid conda package specification"):
            deployer.build_plan(p)

    def test_conda_missing_aborts(self):
        from research_agent.plugins.deployer import Deployer
        p = _make_plugin(install_method={"method": "conda"})
        deployer = Deployer.__new__(Deployer)
        deployer.os_name = "linux"
        deployer.tools_available = lambda: {"conda": False, "mamba": False, "pip": True, "git": False}
        plan = deployer.build_plan(p)
        assert any(s["action"] == "abort" for s in plan["steps"])

    def test_binary_windows_download(self):
        from research_agent.plugins.deployer import Deployer
        p = _make_plugin(install_method={"method": "binary",
                                         "download": {"windows": "https://x.com/pkg.exe", "linux": "https://x.com/pkg"}})
        deployer = Deployer.__new__(Deployer)
        deployer.os_name = "windows"
        plan = deployer.build_plan(p)
        assert any(s["action"] == "download" and "pkg.exe" in s.get("url", "") for s in plan["steps"])

    def test_platform_incompatible(self):
        from research_agent.plugins.deployer import Deployer
        p = _make_plugin(os_compatibility=["linux"], install_method={"method": "conda"})
        deployer = Deployer.__new__(Deployer)
        deployer.os_name = "windows"
        plan = deployer.build_plan(p)
        assert plan["supported"] is False

    def test_manual_hint(self):
        from research_agent.plugins.deployer import Deployer
        p = _make_plugin(install_method={"method": "manual"})
        deployer = Deployer.__new__(Deployer)
        deployer.os_name = "linux"
        plan = deployer.build_plan(p)
        assert any(s["action"] == "manual_hint" for s in plan["steps"])
        assert plan["requires_manual_download"] is True


# ========== 集成测试: 插件市场 API ==========

@pytest.fixture
def client(monkeypatch, tmp_path):
    """每个测试使用独立客户端 + 临时数据库"""
    test_db = tmp_path / f"test_plugins_{os.getpid()}.db"
    test_db_url = f"sqlite+aiosqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    monkeypatch.setattr("research_agent.core.app.settings.database_url", test_db_url)

    import importlib
    import research_agent.core.db as db_module
    importlib.reload(db_module)

    app = create_app()
    with TestClient(app) as c:
        yield c

    # 清理
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(db_module.close_db())
        loop.close()
    except Exception:
        pass

    try:
        if test_db.exists():
            test_db.unlink()
    except Exception:
        pass


def _get_plugin_id(client, name):
    r = client.get("/api/v1/plugins/", params={"search": name})
    assert r.status_code == 200
    plugins = [p for p in r.json() if p["name"] == name]
    assert plugins, f"插件 {name} 未找到"
    return plugins[0]["id"]


class TestMarketAPI:
    def test_categories_with_counts(self, client):
        """分类浏览带计数"""
        r = client.get("/api/v1/plugins/categories")
        assert r.status_code == 200
        cats = {c["category"]: c["count"] for c in r.json()}
        assert cats.get("docking", 0) >= 3
        assert cats.get("structure", 0) >= 2
        assert "runtime" in cats  # 依赖节点也入市场

    def test_core_tools_in_market(self, client):
        """核心工具必须在市场中"""
        r = client.get("/api/v1/plugins/")
        names = {p["name"] for p in r.json()}
        for tool in ("autodock_vina", "glide", "gold", "pymol", "chimerax", "swiss_pdbviewer"):
            assert tool in names, f"缺少核心工具: {tool}"

    def test_detail_contains_market_info(self, client):
        """详情: 版本历史/评分/支持渠道/安装方式"""
        pid = _get_plugin_id(client, "autodock_vina")
        r = client.get(f"/api/v1/plugins/{pid}")
        data = r.json()
        assert data["install_method"]["method"] == "conda"
        assert data["support_email"]
        assert data["homepage"] or data["docs_url"]
        assert data["os_compatibility"]
        assert data["downloads"] > 0
        assert len(data["versions"]) >= 2  # 版本历史
        assert data["rating_summary"]["count"] > 0  # 种子评分

    def test_version_history_sorted(self, client):
        """版本历史含最新标记"""
        pid = _get_plugin_id(client, "samtools")
        r = client.get(f"/api/v1/plugins/{pid}/versions")
        versions = r.json()["versions"]
        assert versions, "samtools 应有版本历史"
        latest = [v for v in versions if v["is_latest"]]
        assert latest and latest[0]["version"] == "1.21"

    def test_switch_version(self, client):
        """版本切换 (回滚)"""
        pid = _get_plugin_id(client, "fastqc")
        client.post("/api/v1/plugins/install", json={"plugin_id": pid})
        # 重置到最新版本 (幂等, 防止上次残留)
        client.post(f"/api/v1/plugins/{pid}/versions/0.12.1/switch")
        r = client.post(f"/api/v1/plugins/{pid}/versions/0.11.9/switch")
        assert r.status_code == 200
        detail = client.get(f"/api/v1/plugins/{pid}").json()
        assert detail["version"] == "0.11.9"
        assert detail["update_available"] is True  # 已非最新
        # 切回
        client.post(f"/api/v1/plugins/{pid}/versions/0.12.1/switch")
        detail = client.get(f"/api/v1/plugins/{pid}").json()
        assert detail["version"] == "0.12.1"
        assert detail["update_available"] is False
        client.delete(f"/api/v1/plugins/{pid}")

    def test_register_version_and_upgrade(self, client):
        """注册新版本 (幂等) + 升级"""
        pid = _get_plugin_id(client, "fastp")
        r = client.post(f"/api/v1/plugins/{pid}/versions",
                        json={"version": "0.99.0", "changelog": "测试版本",
                              "release_date": "2026-01-01"})
        assert r.status_code == 200
        assert r.json()["latest_version"] == "0.99.0"
        # 幂等: 重复注册返回原状态
        r = client.post(f"/api/v1/plugins/{pid}/versions",
                        json={"version": "0.99.0"})
        assert r.status_code == 200

        # 安装后升级
        client.post("/api/v1/plugins/install", json={"plugin_id": pid})
        up = client.post(f"/api/v1/plugins/{pid}/upgrade")
        assert up.status_code == 200
        assert up.json()["upgraded"] is True
        assert up.json()["target_version"] == "0.99.0"

        # 清理: 回滚市场版本 + 删除测试版本 + 恢复 latest + 卸载
        client.post(f"/api/v1/plugins/{pid}/versions/0.24.0/switch")
        r = client.delete(f"/api/v1/plugins/{pid}/versions/0.99.0")
        assert r.status_code == 200
        client.put(f"/api/v1/plugins/{pid}", json={"latest_version": "0.24.0"})
        client.delete(f"/api/v1/plugins/{pid}")

    def test_upgrade_rejects_unregistered_target_version(self, client):
        pid = _get_plugin_id(client, "fastqc")
        client.post("/api/v1/plugins/install", json={"plugin_id": pid})

        response = client.post(
            f"/api/v1/plugins/{pid}/upgrade",
            json={"target_version": "999.0-not-registered"},
        )

        assert response.status_code == 400
        assert "not available" in response.json()["detail"]

    def test_update_detection_flow(self, client):
        """更新检测: 安装旧版 → 检测到更新 → 升级"""
        pid = _get_plugin_id(client, "bowtie2")
        # 重置为市场基线版本 (幂等)
        client.post(f"/api/v1/plugins/{pid}/versions/2.5.3/switch")
        client.post("/api/v1/plugins/install", json={"plugin_id": pid})

        r = client.get("/api/v1/plugins/updates")
        assert r.status_code == 200
        updates = {u["name"]: u for u in r.json()["updates"]}
        assert "bowtie2" in updates, "bowtie2 应有可用更新"
        assert updates["bowtie2"]["current_version"] == "2.5.3"
        assert updates["bowtie2"]["latest_version"] == "2.5.4"

        # 升级后更新消失
        client.post(f"/api/v1/plugins/{pid}/upgrade")
        r = client.get("/api/v1/plugins/updates")
        assert "bowtie2" not in {u["name"] for u in r.json()["updates"]}

        # 清理
        client.delete(f"/api/v1/plugins/{pid}")
        client.post(f"/api/v1/plugins/{pid}/versions/2.5.3/switch")

    def test_reviews_seed_and_aggregation(self, client):
        """评价列表 + 提交新评价聚合评分"""
        pid = _get_plugin_id(client, "pymol")
        r = client.get(f"/api/v1/plugins/{pid}/reviews")
        data = r.json()
        assert data["summary"]["count"] >= 2
        assert "distribution" in data["summary"]

        before = client.get(f"/api/v1/plugins/{pid}").json()
        before_rating = before["rating_avg"]
        before_count = before["rating_count"]

        add = client.post(f"/api/v1/plugins/{pid}/reviews",
                          json={"rating": 5, "comment": "测试评价"})
        assert add.status_code == 200
        assert add.json()["rating"] == 5
        assert add.json()["is_verified"] is False
        added_id = add.json()["id"]

        after = client.get(f"/api/v1/plugins/{pid}").json()
        assert after["rating_count"] == before_count + 1
        assert after["rating_avg"] >= before_rating

        # 清理: 删除测试评价, 评分恢复
        rm = client.delete(f"/api/v1/plugins/{pid}/reviews/{added_id}")
        assert rm.status_code == 200
        final = client.get(f"/api/v1/plugins/{pid}").json()
        assert final["rating_count"] == before_count

    def test_review_invalid_rating(self, client):
        """非法评分被拒绝"""
        pid = _get_plugin_id(client, "glide")
        r = client.post(f"/api/v1/plugins/{pid}/reviews", json={"rating": 9})
        assert r.status_code == 422
        r = client.post(f"/api/v1/plugins/{pid}/reviews", json={"rating": 0})
        assert r.status_code == 422

    def test_dependency_resolution_api(self, client):
        """依赖解析 API: deseq2 需要 r + bioconductor"""
        pid = _get_plugin_id(client, "deseq2")
        r = client.get(f"/api/v1/plugins/{pid}/dependencies")
        assert r.status_code == 200
        result = r.json()
        deps = result["graph"].get("deseq2", [])
        assert "r" in deps and "bioconductor" in deps
        assert result["cycle"] is None

    def test_dependency_resolution_vina(self, client):
        """vina 依赖 mgltools"""
        pid = _get_plugin_id(client, "autodock_vina")
        r = client.get(f"/api/v1/plugins/{pid}/dependencies")
        assert r.status_code == 200
        deps = r.json()["graph"].get("autodock_vina", [])
        assert "mgltools" in deps

    def test_deploy_simulate_conda(self, client):
        """一键部署 (模拟): conda 工具生成安装命令"""
        pid = _get_plugin_id(client, "fastqc")
        r = client.post(f"/api/v1/plugins/{pid}/deploy", json={"simulate": True})
        assert r.status_code == 200
        data = r.json()
        assert data["is_simulated"] is True
        assert data["ok"] is True
        assert any("conda" in (s.get("command") or "") for s in data["steps"])

    def test_deploy_simulate_manual(self, client):
        """一键部署 (模拟): 商业/手动工具给出手动指引"""
        pid = _get_plugin_id(client, "glide")
        r = client.post(f"/api/v1/plugins/{pid}/deploy", json={"simulate": True})
        assert r.status_code == 200
        data = r.json()
        assert any(s["action"] == "manual_hint" for s in data["steps"])
        assert data["requires_manual_download"] is True

    def test_deploy_history(self, client):
        """部署历史"""
        pid = _get_plugin_id(client, "fastqc")
        r = client.get(f"/api/v1/plugins/{pid}/deploy/history")
        assert r.status_code == 200
        assert isinstance(r.json()["history"], list)

    def test_verify_endpoint(self, client):
        """验证端点可调用"""
        pid = _get_plugin_id(client, "pymol")
        r = client.post(f"/api/v1/plugins/{pid}/verify")
        assert r.status_code == 200
        assert "found" in r.json()

    def test_sort_by_rating(self, client):
        """按评分/下载量排序"""
        r = client.get("/api/v1/plugins/", params={"sort": "rating"})
        ratings = [p["rating_avg"] for p in r.json() if p["rating_count"] > 0]
        assert ratings == sorted(ratings, reverse=True), "应按评分降序"
        assert ratings[0] == max(ratings)
        assert 4.5 <= ratings[0] <= 5.0

    def test_filter_installed_and_updates(self, client):
        """筛选: 已安装 / 可更新 (在测试流程已安装过则正确过滤)"""
        r = client.get("/api/v1/plugins/", params={"installed_only": True})
        assert all(p["is_installed"] for p in r.json())
        r = client.get("/api/v1/plugins/", params={"update_available_only": True})
        assert all(p["update_available"] for p in r.json())
