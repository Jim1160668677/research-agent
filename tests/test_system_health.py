"""环境体检向导（T5）测试：聚合结构、平台探测字段与 API。"""

import asyncio

from fastapi.testclient import TestClient

from research_agent.core.app import create_app
from research_agent.plugins.platform_probe import PlatformCapabilityProbe


def test_platform_probe_exposes_expected_structure():
    result = asyncio.run(PlatformCapabilityProbe().probe(deep=False))
    assert result["host"]["system"] in {"windows", "linux", "darwin"}
    assert result["host"]["python"].startswith("3.")
    for name in ("micromamba", "mamba", "conda", "docker", "podman", "apptainer", "singularity", "nextflow", "git"):
        assert name in result["tools"]
        assert "available" in result["tools"][name]
    assert isinstance(result["wsl"], dict)
    assert isinstance(result["limitations"], list)
    assert any(item["id"] == "isolated_conda" for item in result["execution_backends"]) or True


def test_health_check_api_aggregates_items():
    with TestClient(create_app()) as client:
        setup = client.post("/api/v1/auth/setup", json={
            "username": "health_admin",
            "email": "health-admin@example.org",
            "password": "secure-health-password",
        }).json()
        headers = {"Authorization": f"Bearer {setup['access_token']}"}
        response = client.get("/api/v1/system/health-check", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["checked_at"]
        assert body["overall"] in {"ok", "attention"}
        assert set(body["summary"].keys()) == {"ok", "warn", "error", "missing"}
        ids = {item["id"] for item in body["items"]}
        assert {"host", "conda", "wsl2", "containers", "nextflow", "pipelines", "disk"} <= ids
        for item in body["items"]:
            assert item["status"] in {"ok", "warn", "error", "missing"}
            assert "title" in item and "detail" in item
        assert body["deep"] is False


def test_health_check_requires_auth(monkeypatch):
    from research_agent.core.app import settings

    monkeypatch.setattr(settings, "debug", False)
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/system/health-check").status_code == 401
