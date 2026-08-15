"""Capability manifest, catalog synchronization, and platform probe tests."""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import research_agent.core.db as db_module
from research_agent.core.app import create_app
from research_agent.core.models.db import CatalogSync, Plugin, PluginInstallation
from research_agent.plugins.catalog_sync import BiocondaCatalogSync
from research_agent.plugins.deployer import Deployer
from research_agent.plugins.lifecycle import (
    DEPLOYED,
    DEPLOYING,
    INSTALLED_STATES,
    UNINSTALLED,
    latest_installation,
    transition,
)
from research_agent.plugins.manager import PluginManager
from research_agent.plugins.manifest import CapabilityManifestV1, manifest_digest
from research_agent.plugins.platform_probe import _decode_output


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def _plugin_id(client, name="fastqc"):
    response = client.get("/api/v1/plugins/", params={"search": name})
    assert response.status_code == 200
    return next(item["id"] for item in response.json() if item["name"] == name)


def test_manifest_schema_validation_and_plugin_contract(client):
    schema = client.get("/api/v1/plugins/manifest/schema")
    assert schema.status_code == 200
    assert schema.json()["properties"]["schema_version"]["const"] == "1.0"

    plugin_id = _plugin_id(client)
    response = client.get(f"/api/v1/plugins/{plugin_id}/manifest")
    assert response.status_code == 200
    data = response.json()
    manifest = CapabilityManifestV1.model_validate(data["manifest"])
    assert manifest.name == "fastqc"
    assert manifest.runtime.executor == "conda"
    assert manifest.runtime.package == "fastqc==0.12.1"
    assert manifest.permissions.network == "restricted"
    assert data["digest"] == manifest_digest(manifest)

    unsafe = data["manifest"] | {
        "runtime": {"executor": "container", "image": "latest/unpinned:latest"}
    }
    rejected = client.post("/api/v1/plugins/manifest/validate", json=unsafe)
    assert rejected.status_code == 422


def test_selection_is_not_reported_as_deployment(client):
    plugin_id = _plugin_id(client)
    selected = client.post("/api/v1/plugins/install", json={"plugin_id": plugin_id})
    assert selected.status_code == 200
    data = selected.json()
    assert data["lifecycle_state"] == "selected"
    assert data["is_selected"] is True
    assert data["is_installed"] is False
    assert data["is_deployed"] is False
    assert data["is_verified"] is False
    assert data["is_enabled"] is False

    cannot_enable = client.post(f"/api/v1/plugins/{plugin_id}/enable")
    assert cannot_enable.status_code == 409
    preview = client.post(
        f"/api/v1/plugins/{plugin_id}/deploy", json={"simulate": True}
    )
    assert preview.status_code == 200
    detail = client.get(f"/api/v1/plugins/{plugin_id}").json()
    assert detail["lifecycle_state"] == "selected"

    deselected = client.delete(f"/api/v1/plugins/{plugin_id}")
    assert deselected.status_code == 200
    assert deselected.json()["plugin"]["lifecycle_state"] == "deselected"


def test_platform_capabilities_are_read_only_and_structured(client):
    response = client.get("/api/v1/plugins/platform/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["host"]["system"] in {"windows", "linux", "darwin"}
    assert data["execution_backends"]
    assert data["tools"]["conda"]["available"] in {True, False}
    assert data["deep_probe"] is False


def test_wsl_utf16_output_is_decoded():
    assert _decode_output("Ubuntu\r\nDebian\r\n".encode("utf-16")) == "Ubuntu\r\nDebian"


@pytest.mark.asyncio
async def test_bioconda_sync_imports_metadata_without_installing(tmp_path):
    await db_module.init_db()
    payload = {
        "packages.conda": {
            "seqkit-2.9.0-h9ee0642_0.conda": {
                "name": "seqkit",
                "version": "2.9.0",
                "build": "h9ee0642_0",
                "build_number": 0,
                "depends": ["libgcc >=13", "zlib >=1.2"],
                "license": "MIT",
                "sha256": "a" * 64,
                "size": 1048576,
                "timestamp": 1767225600000,
            },
            "seqkit-2.8.0-h9ee0642_0.conda": {
                "name": "seqkit",
                "version": "2.8.0",
                "build": "h9ee0642_0",
                "build_number": 0,
                "depends": ["zlib >=1.2"],
                "license": "MIT",
                "sha256": "b" * 64,
                "size": 900000,
                "timestamp": 1735689600000,
            },
        }
    }

    def handler(request: httpx.Request):
        assert request.url.host == "conda.anaconda.org"
        return httpx.Response(
            200,
            request=request,
            json=payload,
            headers={"etag": '"test-etag"'},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        async with db_module.AsyncSessionLocal() as db:
            service = BiocondaCatalogSync(
                db,
                user_id=1,
                client=http_client,
                cache_root=tmp_path / "catalog-cache",
            )
            result = await service.sync(["seqkit"], ["linux-64"])
            assert result["imported"] == 1
            assert result["cache_status"] == "fresh"
            plugin_result = await db.execute(select(Plugin).where(Plugin.name == "seqkit"))
            plugin = plugin_result.scalar_one()
            assert plugin.latest_version == "2.9.0"
            assert plugin.source_registry == "bioconda"
            assert plugin.trust_status == "unreviewed"
            assert plugin.manifest["runtime"]["package"] == "seqkit==2.9.0"
            installations = await db.execute(
                select(PluginInstallation).where(
                    PluginInstallation.plugin_id == plugin.id,
                    PluginInstallation.status.in_(INSTALLED_STATES),
                )
            )
            assert installations.scalars().all() == []
            history = await service.history()
            assert history[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_bioconda_sync_uses_cache_after_network_failure(tmp_path):
    await db_module.init_db()
    payload = {"packages": {}}

    def success(request: httpx.Request):
        return httpx.Response(200, request=request, json=payload)

    cache_root = tmp_path / "catalog-cache"
    async with httpx.AsyncClient(transport=httpx.MockTransport(success)) as http_client:
        async with db_module.AsyncSessionLocal() as db:
            first = BiocondaCatalogSync(
                db, 1, client=http_client, cache_root=cache_root
            )
            await first.sync(["missing-tool"], ["noarch"])

    def offline(request: httpx.Request):
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as http_client:
        async with db_module.AsyncSessionLocal() as db:
            second = BiocondaCatalogSync(
                db, 1, client=http_client, cache_root=cache_root
            )
            result = await second.sync(["missing-tool"], ["noarch"])
            assert result["cache_status"] == "fallback_cache"
            assert result["missing"] == ["missing-tool"]


@pytest.mark.asyncio
async def test_failed_catalog_sync_rolls_back_partial_imports(tmp_path):
    await db_module.init_db()

    class FailingSync(BiocondaCatalogSync):
        async def _apply(self, requested, payloads):
            self.db.add(Plugin(
                name="partial-import-must-rollback",
                version="1.0.0",
                description="transaction probe",
            ))
            await self.db.flush()
            raise RuntimeError("simulated apply failure")

    def handler(request: httpx.Request):
        return httpx.Response(200, request=request, json={"packages": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        async with db_module.AsyncSessionLocal() as db:
            service = FailingSync(db, 1, client=http_client, cache_root=tmp_path / "cache")
            with pytest.raises(RuntimeError, match="simulated apply failure"):
                await service.sync(["fastqc"], ["noarch"])
            plugin = await db.scalar(
                select(Plugin).where(Plugin.name == "partial-import-must-rollback")
            )
            assert plugin is None
            record = await db.scalar(
                select(CatalogSync).order_by(CatalogSync.id.desc())
            )
            assert record.status == "failed"


@pytest.mark.asyncio
async def test_managed_deployment_removal_is_scoped_to_environment_root(tmp_path):
    await db_module.init_db()
    async with db_module.AsyncSessionLocal() as db:
        plugin = await db.scalar(select(Plugin).where(Plugin.name == "fastqc"))
        deployer = Deployer(db, user_id=1)
        deployer.env_root = tmp_path / "plugin-envs"
        prefix = deployer._environment_prefix(plugin)
        prefix.mkdir(parents=True)
        (prefix / "probe.txt").write_text("managed", encoding="utf-8")
        await transition(
            db,
            plugin.id,
            1,
            DEPLOYING,
            version=plugin.version,
            config={"environment_prefix": str(prefix), "method": "conda"},
        )
        await transition(
            db,
            plugin.id,
            1,
            DEPLOYED,
            version=plugin.version,
            config={"environment_prefix": str(prefix), "method": "conda"},
        )
        await db.commit()

        result = await deployer.remove_environment(plugin)
        assert result["removed"] is True
        assert not prefix.exists()
        assert (await latest_installation(db, plugin.id, 1)).status == UNINSTALLED
        assert await PluginManager(db).get_installed_plugins(user_id=1) == []

        outside = tmp_path / "outside-environment"
        outside.mkdir()
        await transition(
            db,
            plugin.id,
            1,
            DEPLOYING,
            config={"environment_prefix": str(outside), "method": "conda"},
        )
        await transition(
            db,
            plugin.id,
            1,
            DEPLOYED,
            config={"environment_prefix": str(outside), "method": "conda"},
        )
        await db.commit()
        with pytest.raises(ValueError, match="outside the managed root"):
            await deployer.remove_environment(plugin)
        assert outside.exists()


def test_bioconda_request_rejects_injection():
    with pytest.raises(ValueError, match="Invalid Bioconda package"):
        BiocondaCatalogSync.validate_request(
            ["fastqc; Remove-Item data"], ["linux-64"]
        )
