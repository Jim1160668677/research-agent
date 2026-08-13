import asyncio
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from research_agent.core.app import create_app, settings
from research_agent.core.models.db import AuditLog, ResearchArtifact
from research_agent.research.artifacts import ArtifactStore


@pytest.fixture
def client():
    with TestClient(create_app()) as value:
        yield value


def _encrypted_files(tmp_path: Path) -> list[Path]:
    return list((tmp_path / "artifacts").rglob("*.raenc"))


def test_upload_is_encrypted_download_is_verified_and_tamper_is_blocked(client, tmp_path):
    plaintext = b"participant_secret,measurement\nSUBJECT-ALPHA,42\n"
    upload = client.post(
        "/api/v1/research/artifacts",
        files={"file": ("sensitive.csv", plaintext, "text/csv")},
        headers={"X-Request-ID": "upload-security-test"},
    )
    assert upload.status_code == 201, upload.text
    artifact = upload.json()
    assert artifact["encrypted_at_rest"] is True
    assert "participant_secret" not in str(artifact["summary"])

    files = _encrypted_files(tmp_path)
    assert len(files) == 1
    encrypted_path = files[0]
    encrypted = encrypted_path.read_bytes()
    assert encrypted.startswith(b"RAART001")
    assert plaintext not in encrypted

    download = client.get(f"/api/v1/research/artifacts/{artifact['id']}/download")
    assert download.status_code == 200
    assert download.content == plaintext
    assert download.headers["x-content-type-options"] == "nosniff"

    status = client.get("/api/v1/system/security-integrity")
    assert status.status_code == 200
    assert status.json()["artifacts"] == {
        "scope": "current_user",
        "total": 1,
        "encrypted": 1,
        "legacy_plaintext": 0,
        "encryption_format": "ra-aes256-gcm-v1",
    }
    assert status.json()["global_artifacts"]["encrypted"] == 1
    assert status.json()["audit_chain"]["valid"] is True
    assert status.json()["audit_chain"]["chained_entries"] == 2

    damaged = bytearray(encrypted)
    damaged[-1] ^= 0x01
    encrypted_path.write_bytes(damaged)
    blocked = client.get(f"/api/v1/research/artifacts/{artifact['id']}/download")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "Artifact integrity verification failed"


def test_legacy_plaintext_can_be_explicitly_migrated(client, tmp_path):
    from research_agent.core import db as db_module

    artifact_id = str(uuid.uuid4())
    plaintext = b"sample,value\nlegacy,7\n"
    legacy_path = tmp_path / "artifacts" / "user-1" / "inbox" / f"{artifact_id}.csv"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_bytes(plaintext)

    async def seed() -> None:
        async with db_module.AsyncSessionLocal() as db:
            db.add(ResearchArtifact(
                id=artifact_id,
                user_id=1,
                name="legacy.csv",
                relative_path=legacy_path.relative_to(tmp_path / "artifacts").as_posix(),
                media_type="text/csv",
                kind="input",
                size_bytes=len(plaintext),
                sha256=__import__("hashlib").sha256(plaintext).hexdigest(),
                summary={"modality": "table"},
                status="ready",
            ))
            await db.commit()

    asyncio.run(seed())
    before = client.get("/api/v1/system/security-integrity").json()["artifacts"]
    assert before["legacy_plaintext"] == 1

    migrated = client.post(
        "/api/v1/research/artifacts/migrate-encryption",
        json={"artifact_ids": [artifact_id]},
    )
    assert migrated.status_code == 200, migrated.text
    assert migrated.json()["migrated"] == [artifact_id]
    assert migrated.json()["failed"] == []
    assert not legacy_path.exists()
    assert client.get(f"/api/v1/research/artifacts/{artifact_id}/download").content == plaintext
    after = client.get("/api/v1/system/security-integrity").json()["artifacts"]
    assert after["legacy_plaintext"] == 0


def test_audit_chain_detects_database_tampering(client):
    upload = client.post(
        "/api/v1/research/artifacts",
        files={"file": ("audit.txt", b"audit payload", "text/plain")},
    )
    assert upload.status_code == 201
    assert client.get("/api/v1/system/security-integrity").json()["audit_chain"]["valid"] is True

    from research_agent.core import db as db_module

    async def tamper() -> None:
        async with db_module.AsyncSessionLocal() as db:
            result = await db.execute(
                select(AuditLog).where(AuditLog.entry_hash.is_not(None)).order_by(AuditLog.chain_index)
            )
            entry = result.scalars().first()
            entry.detail = {"tampered": True}
            await db.commit()

    asyncio.run(tamper())
    integrity = client.get("/api/v1/system/security-integrity").json()["audit_chain"]
    assert integrity["valid"] is False
    assert "entry_hash_mismatch" in integrity["issues"][0]["reasons"]


def test_artifact_download_is_user_scoped(monkeypatch):
    monkeypatch.setattr(settings, "debug", False)
    with TestClient(create_app()) as client:
        owner = client.post("/api/v1/auth/setup", json={
            "username": "security_owner",
            "email": "security-owner@example.org",
            "password": "secure-owner-password",
        }).json()
        other = client.post("/api/v1/auth/register", json={
            "username": "security_other",
            "email": "security-other@example.org",
            "password": "secure-other-password",
        }).json()
        owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        upload = client.post(
            "/api/v1/research/artifacts",
            headers=owner_headers,
            files={"file": ("private.txt", b"private", "text/plain")},
        )
        artifact_id = upload.json()["id"]
        assert client.get(
            f"/api/v1/research/artifacts/{artifact_id}/download",
            headers=other_headers,
        ).status_code == 404
        integrity = client.get("/api/v1/system/security-integrity", headers=other_headers)
        assert integrity.status_code == 403


def test_unclean_exit_plaintext_is_purged(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    stale = store.root / ".materialized" / "user-7" / "stale.csv"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"sensitive")
    assert store.purge_materialized() == 1
    assert not stale.exists()
    assert not (store.root / ".materialized").exists()
