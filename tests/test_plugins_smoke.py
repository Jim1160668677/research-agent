"""RA-Eval v1 冒烟评测测试：白名单校验、执行断言、权限与历史。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from research_agent.core.app import create_app
from research_agent.core.db import init_db
from research_agent.core.models.db import Plugin, PluginSmokeRun
from research_agent.plugins.lifecycle import DEPLOYED, transition
from research_agent.plugins.smoke_runner import SmokeRunner, validate_smoke_spec


def test_validate_smoke_spec_accepts_benign_case():
    ok, reason = validate_smoke_spec({
        "id": "version",
        "command": "fastqc",
        "args": ["--version"],
        "expect_exit": 0,
        "expect_stdout": "FastQC",
        "timeout_s": 60,
    })
    assert ok, reason


@pytest.mark.parametrize("spec", [
    {"command": "rm -rf /"},
    {"command": "fastqc && rm -rf /"},
    {"command": "a;b"},
    {"command": "fastqc", "args": ["x; rm -rf /"]},
    {"command": "fastqc", "args": ["$(id)"]},
    {"command": "fastqc", "args": ["--outdir", ""]},
    {"command": "fastqc", "expect_exit": "zero"},
    {"command": "fastqc", "timeout_s": 0},
    {"command": "fastqc", "timeout_s": "60"},
    {"command": "fastqc", "expect_stdout": ""},
    {"command": "fastqc", "args": "not-a-list"},
    {"command": "fastqc", "args": ["<file"]},
])
def test_validate_smoke_spec_rejects_injection_and_bad_shapes(spec):
    ok, reason = validate_smoke_spec(spec)
    assert not ok
    assert reason


@pytest.mark.asyncio
async def test_smoke_runner_passes_and_records(tmp_path):
    await init_db()
    async with __import__("research_agent.core.db", fromlist=["AsyncSessionLocal"]).AsyncSessionLocal() as db:
        plugin = await db.scalar(select(Plugin).where(Plugin.name == "fastqc"))
        prefix = tmp_path / "plugin-env"
        prefix.mkdir(parents=True)
        await transition(db, plugin.id, 1, "deploying", version=plugin.version,
                         config={"environment_prefix": str(prefix), "method": "conda"})
        await transition(db, plugin.id, 1, DEPLOYED, version=plugin.version,
                         config={"environment_prefix": str(prefix), "method": "conda"})
        await db.commit()

        runner = SmokeRunner(db, user_id=1)
        async def _fake_run(argv, timeout=60):
            return 0, "FastQC v0.12.1", ""
        runner.deployer._run_command = _fake_run

        result = await runner.run(plugin)
        assert result["status"] == "passed"
        assert result["detail"]["exit_code"] == 0
        assert result["detail"]["stdout_matched"] is True
        assert result["duration_ms"] >= 0

        rows = await db.execute(select(PluginSmokeRun).where(PluginSmokeRun.plugin_id == plugin.id))
        records = rows.scalars().all()
        assert len(records) == 1
        assert records[0].status == "passed"

        history = await runner.history(plugin.id)
        assert history[0]["smoke_id"] == "version"


@pytest.mark.asyncio
async def test_smoke_runner_fails_on_exit_code_and_stdout_mismatch(tmp_path):
    await init_db()
    async with __import__("research_agent.core.db", fromlist=["AsyncSessionLocal"]).AsyncSessionLocal() as db:
        plugin = await db.scalar(select(Plugin).where(Plugin.name == "samtools"))
        prefix = tmp_path / "plugin-env"
        prefix.mkdir(parents=True)
        await transition(db, plugin.id, 1, "deploying", version=plugin.version,
                         config={"environment_prefix": str(prefix), "method": "conda"})
        await transition(db, plugin.id, 1, DEPLOYED, version=plugin.version,
                         config={"environment_prefix": str(prefix), "method": "conda"})
        await db.commit()

        runner = SmokeRunner(db, user_id=1)
        async def _fake_run(argv, timeout=60):
            return 1, "", "samtools: command not found"
        runner.deployer._run_command = _fake_run

        result = await runner.run(plugin)
        assert result["status"] == "failed"
        assert result["detail"]["exit_code"] == 1
        assert result["detail"]["expect_exit"] == 0

        async def _fake_run_mismatch(argv, timeout=60):
            return 0, "WARNING: unknown option --bogus", ""
        runner.deployer._run_command = _fake_run_mismatch
        result = await runner.run(plugin, smoke_id="version")
        assert result["status"] == "failed"
        assert result["detail"]["stdout_matched"] is False


@pytest.mark.asyncio
async def test_smoke_runner_rejects_undeployed_plugin(tmp_path):
    await init_db()
    async with __import__("research_agent.core.db", fromlist=["AsyncSessionLocal"]).AsyncSessionLocal() as db:
        plugin = await db.scalar(select(Plugin).where(Plugin.name == "kallisto"))
        runner = SmokeRunner(db, user_id=1)
        with pytest.raises(ValueError, match="没有已部署的隔离环境"):
            await runner.run(plugin)


@pytest.mark.asyncio
async def test_smoke_runner_rejects_unknown_smoke_id(tmp_path):
    await init_db()
    async with __import__("research_agent.core.db", fromlist=["AsyncSessionLocal"]).AsyncSessionLocal() as db:
        plugin = await db.scalar(select(Plugin).where(Plugin.name == "fastqc"))
        prefix = tmp_path / "plugin-env"
        prefix.mkdir(parents=True)
        await transition(db, plugin.id, 1, "deploying", version=plugin.version,
                         config={"environment_prefix": str(prefix), "method": "conda"})
        await transition(db, plugin.id, 1, DEPLOYED, version=plugin.version,
                         config={"environment_prefix": str(prefix), "method": "conda"})
        await db.commit()
        runner = SmokeRunner(db, user_id=1)
        with pytest.raises(ValueError, match="没有可执行的冒烟用例"):
            await runner.run(plugin, smoke_id="nonexistent")


def test_smoke_api_scopes_admin_and_requires_deployment(monkeypatch):
    from research_agent.core.app import settings

    monkeypatch.setattr(settings, "debug", False)
    with TestClient(create_app()) as client:
        admin = client.post("/api/v1/auth/setup", json={
            "username": "smoke_admin",
            "email": "smoke-admin@example.org",
            "password": "secure-smoke-password",
        }).json()
        admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
        member = client.post("/api/v1/auth/register", json={
            "username": "smoke_member",
            "email": "smoke-member@example.org",
            "password": "secure-smoke-password",
        }).json()
        member_headers = {"Authorization": f"Bearer {member['access_token']}"}

        plugins = client.get("/api/v1/plugins/", headers=admin_headers).json()
        fastqc = next(item for item in plugins if item["name"] == "fastqc")

        denied = client.post(f"/api/v1/plugins/{fastqc['id']}/smoke", headers=member_headers, json={})
        assert denied.status_code == 403

        undeployed = client.post(f"/api/v1/plugins/{fastqc['id']}/smoke", headers=admin_headers, json={})
        assert undeployed.status_code == 409

        history = client.get(f"/api/v1/plugins/{fastqc['id']}/smoke-history", headers=member_headers)
        assert history.status_code == 200
        assert history.json()["history"] == []
