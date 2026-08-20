import shutil

import pytest
from fastapi.testclient import TestClient

from research_agent.core.app import create_app


@pytest.fixture
def real_client(monkeypatch):
    from research_agent.core.app import settings

    monkeypatch.setattr(settings, "debug", False)
    with TestClient(create_app()) as value:
        yield value


@pytest.fixture
def client():
    with TestClient(create_app()) as value:
        yield value


def upload_csv(client):
    response = client.post(
        "/api/v1/research/artifacts",
        files={"file": ("samples.csv", b"sample,fastq_1,fastq_2,strandedness\nS1,reads.fastq.gz,,auto\n", "text/csv")},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_catalog_discloses_pins_and_execution_policy(client):
    response = client.get("/api/v1/pipelines/catalog")
    assert response.status_code == 200
    data = response.json()
    assert data["policy"] == "allowlisted-and-revision-pinned"
    pins = {item["id"]: item["revision"] for item in data["pipelines"]}
    assert set(pins.keys()) == {
        "nf-core/rnaseq", "nf-core/sarek",
        "nf-core/atacseq", "nf-core/chipseq",
        "nf-core/scrnaseq", "nf-core/spatialvi", "nf-core/spatialaxe",
        "nf-core/diaproteomics", "nf-core/metaboigniter",
    }
    assert pins["nf-core/rnaseq"] == "3.26.0"
    assert pins["nf-core/sarek"] == "3.9.0"
    assert pins["nf-core/atacseq"] == "2.1.2"
    assert pins["nf-core/chipseq"] == "2.1.0"
    assert pins["nf-core/scrnaseq"] == "4.2.0"
    assert pins["nf-core/spatialvi"] == "0.1.0"
    assert pins["nf-core/spatialaxe"] == "1.0.1"
    assert pins["nf-core/diaproteomics"] == "1.2.4"
    assert pins["nf-core/metaboigniter"] == "2.0.1"
    assert data["execution_requires_role"] == "admin"


def test_create_plan_is_persisted_without_installed_nextflow(client, monkeypatch):
    artifact_id = upload_csv(client)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    response = client.post("/api/v1/pipelines/runs", json={
        "pipeline_id": "nf-core/rnaseq",
        "revision": "3.26.0",
        "profile": "docker",
        "parameters": {"genome": "GRCh38", "max_cpus": 2, "max_memory": "8 GB"},
        "artifact_bindings": {"input": artifact_id},
        "network_allowed": True,
        "timeout_seconds": 3600,
        "execute": False,
    })
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "planned"
    public_argv = run["plan"]["argv"]
    assert public_argv[0] == "wsl.exe"
    assert "nf-core/rnaseq" in public_argv
    assert public_argv[public_argv.index("-r") + 1] == "3.26.0"
    assert not any(artifact_id in item for item in run["plan"]["argv"])

    detail = client.get(f"/api/v1/pipelines/runs/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["provenance"]["artifact_sha256"]["input"]
    assert client.get("/api/v1/pipelines/runs").json()["runs"][0]["id"] == run["id"]


def test_execute_reports_truthful_unavailability_and_rejects_bad_inputs(client, monkeypatch):
    artifact_id = upload_csv(client)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    payload = {
        "pipeline_id": "nf-core/rnaseq", "revision": "3.26.0", "profile": "docker",
        "parameters": {"genome": "GRCh38"}, "artifact_bindings": {"input": artifact_id},
        "network_allowed": True, "timeout_seconds": 3600, "execute": True,
    }
    response = client.post("/api/v1/pipelines/runs", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "planned"
    assert response.json()["preflight"]["ready"] is False
    assert any("Nextflow is unavailable" in item for item in response.json()["preflight"]["issues"])

    payload["revision"] = "latest"
    invalid = client.post("/api/v1/pipelines/runs", json=payload)
    assert invalid.status_code == 422
    assert "pinned revision" in invalid.json()["detail"]

    payload["revision"] = "3.26.0"
    payload["parameters"] = {"script": "unsafe"}
    invalid = client.post("/api/v1/pipelines/runs", json=payload)
    assert invalid.status_code == 422
    assert "Unknown pipeline parameter" in invalid.json()["detail"]


def test_real_auth_enforces_admin_execution_and_user_isolation(real_client, monkeypatch):
    owner = real_client.post("/api/v1/auth/setup", json={
        "username": "pipeline_owner", "email": "owner@example.org", "password": "secure-owner-password",
    }).json()
    member = real_client.post("/api/v1/auth/register", json={
        "username": "pipeline_member", "email": "member@example.org", "password": "secure-member-password",
    }).json()
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    member_headers = {"Authorization": f"Bearer {member['access_token']}"}
    uploaded = real_client.post(
        "/api/v1/research/artifacts", headers=owner_headers,
        files={"file": ("samples.csv", b"sample,fastq_1,fastq_2,strandedness\nS1,x.fastq.gz,,auto\n", "text/csv")},
    )
    artifact_id = uploaded.json()["id"]
    monkeypatch.setattr(shutil, "which", lambda _: None)
    payload = {
        "pipeline_id": "nf-core/rnaseq", "revision": "3.26.0", "profile": "docker",
        "parameters": {"genome": "GRCh38"}, "artifact_bindings": {"input": artifact_id}, "execute": False,
    }
    created = real_client.post("/api/v1/pipelines/runs", headers=owner_headers, json=payload)
    assert created.status_code == 201
    run_id = created.json()["id"]

    forbidden = real_client.post(
        "/api/v1/pipelines/runs", headers=member_headers, json={**payload, "execute": True}
    )
    assert forbidden.status_code == 403
    assert real_client.get(f"/api/v1/pipelines/runs/{run_id}", headers=member_headers).status_code == 404
    assert real_client.get("/api/v1/pipelines/runs", headers=member_headers).json()["runs"] == []


def test_state_transitions_refresh_async_rows_after_commit(real_client, monkeypatch):
    """Every mutation may safely read the run after SQLAlchemy expires it on commit."""

    class ReadyBackend:
        async def preflight(self, **kwargs):
            return {"ready": True, "issues": [], "warnings": []}

    class FakeManager:
        backend = ReadyBackend()

        def __init__(self):
            self.submitted = []
            self.cancelled = []

        async def plan_run(self, run_id):
            return {"run_id": run_id}

        def submit(self, run_id):
            self.submitted.append(run_id)
            return True

        def cancel(self, run_id):
            self.cancelled.append(run_id)
            return True

    from research_agent.core.api import pipelines as pipelines_api

    manager = FakeManager()
    monkeypatch.setattr(pipelines_api, "get_pipeline_manager", lambda: manager)
    owner = real_client.post(
        "/api/v1/auth/setup",
        json={
            "username": "transition_owner",
            "email": "transition@example.org",
            "password": "secure-transition-password",
        },
    ).json()
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    payload = {
        "pipeline_id": "nf-core/rnaseq",
        "revision": "3.26.0",
        "profile": "docker",
        "parameters": {"test_profile": True},
        "artifact_bindings": {},
        "network_allowed": True,
        "timeout_seconds": 3600,
    }

    created = real_client.post(
        "/api/v1/pipelines/runs", headers=headers, json={**payload, "execute": True}
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "queued"
    run_id = created.json()["id"]
    assert manager.submitted == [run_id]

    cancelled = real_client.post(f"/api/v1/pipelines/runs/{run_id}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json() == {"run_id": run_id, "status": "cancelled", "task_signalled": True}

    resumed = real_client.post(f"/api/v1/pipelines/runs/{run_id}/resume", headers=headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "queued"
    assert resumed.json()["resume_count"] == 1

    planned = real_client.post(
        "/api/v1/pipelines/runs", headers=headers, json={**payload, "execute": False}
    )
    planned_id = planned.json()["id"]
    started = real_client.post(f"/api/v1/pipelines/runs/{planned_id}/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json() == {"run_id": planned_id, "status": "queued"}
