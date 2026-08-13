"""Validate packaged artifact encryption, restart recovery, and audit integrity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
    token: str | None = None,
    timeout: float = 30,
) -> tuple[int, bytes, dict[str, str]]:
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        content_type = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url}{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


def _json(*args, **kwargs) -> tuple[int, dict]:
    status, raw, _ = _request(*args, **kwargs)
    value = json.loads(raw.decode("utf-8"))
    return status, value


def _multipart(filename: str, media_type: str, raw: bytes) -> tuple[bytes, str]:
    boundary = f"----ResearchAgent{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {media_type}\r\n\r\n"
    ).encode() + raw + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


def _wait_for_api(lock_file: Path, process: subprocess.Popen) -> str:
    deadline = time.monotonic() + 90
    last_error = "lock file not created"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"desktop exited early with status {process.returncode}")
        try:
            lock = json.loads(lock_file.read_text(encoding="utf-8"))
            port = int(lock["port"])
            base_url = f"http://127.0.0.1:{port}"
            status, health = _json(base_url, "GET", "/health", timeout=3)
            if status == 200 and health.get("status") == "healthy":
                if lock.get("pid") != process.pid:
                    raise RuntimeError("single-instance lock PID mismatch")
                return base_url
        except Exception as exc:  # noqa: BLE001 - bounded startup retry
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"desktop did not become healthy: {last_error}")


def _launch(executable: Path, appdata: Path) -> subprocess.Popen:
    environment = {**os.environ, "APPDATA": str(appdata)}
    return subprocess.Popen(
        [str(executable)],
        cwd=str(executable.parent),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


def _stop(process: subprocess.Popen, lock_file: Path | None = None) -> None:
    if process.poll() is not None:
        pass
    else:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    # Windows TerminateProcess cannot run application cleanup. This harness owns
    # the isolated profile and may remove only the confirmed-dead process's lock.
    if lock_file and lock_file.exists():
        try:
            record = json.loads(lock_file.read_text(encoding="utf-8"))
            if record.get("pid") == process.pid:
                lock_file.unlink()
        except (OSError, ValueError, TypeError):
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--profile-root", type=Path, required=True)
    args = parser.parse_args()
    executable = args.exe.resolve()
    if not executable.is_file():
        raise SystemExit(f"Packaged executable is missing: {executable}")
    profile_root = args.profile_root.resolve()
    profile_root.mkdir(parents=True, exist_ok=False)
    appdata = profile_root / "AppData" / "Roaming"
    appdata.mkdir(parents=True)
    data_dir = appdata / "ResearchAgent"
    lock_file = data_dir / "ResearchAgent.lock"
    credentials = {"username": "p3_security_owner", "password": "P3-Security-Only!"}
    plaintext = b"participant_id,measurement\nSUBJECT-P3-SECRET,42\n"

    first = _launch(executable, appdata)
    try:
        base_url = _wait_for_api(lock_file, first)
        code, auth = _json(
            base_url,
            "POST",
            "/api/v1/auth/setup",
            payload={**credentials, "email": "p3-security@example.org"},
        )
        if code != 200:
            raise RuntimeError(f"first-run setup failed: {auth}")
        token = str(auth["access_token"])
        body, content_type = _multipart("sensitive.csv", "text/csv", plaintext)
        code, uploaded = _json(
            base_url,
            "POST",
            "/api/v1/research/artifacts",
            body=body,
            content_type=content_type,
            token=token,
        )
        if code != 201 or uploaded.get("encrypted_at_rest") is not True:
            raise RuntimeError(f"encrypted upload failed: {uploaded}")
        if b"participant_id" in json.dumps(uploaded).encode("utf-8"):
            raise RuntimeError("artifact summary leaked a source column name")
        artifact_id = str(uploaded["id"])
        encrypted_files = list((data_dir / "artifacts").rglob("*.raenc"))
        if len(encrypted_files) != 1:
            raise RuntimeError(f"expected one encrypted file, found {len(encrypted_files)}")
        encrypted_path = encrypted_files[0]
        encrypted = encrypted_path.read_bytes()
        if not encrypted.startswith(b"RAART001") or plaintext in encrypted:
            raise RuntimeError("stored artifact is not a valid opaque encrypted envelope")
        code, downloaded, _ = _request(
            base_url,
            "GET",
            f"/api/v1/research/artifacts/{artifact_id}/download",
            token=token,
        )
        if code != 200 or downloaded != plaintext:
            raise RuntimeError("verified download did not reproduce the input")
    finally:
        _stop(first, lock_file)

    second = _launch(executable, appdata)
    try:
        base_url = _wait_for_api(lock_file, second)
        code, auth = _json(
            base_url, "POST", "/api/v1/auth/login", payload=credentials
        )
        if code != 200:
            raise RuntimeError(f"restart login failed: {auth}")
        token = str(auth["access_token"])
        code, downloaded, _ = _request(
            base_url,
            "GET",
            f"/api/v1/research/artifacts/{artifact_id}/download",
            token=token,
        )
        if code != 200 or downloaded != plaintext:
            raise RuntimeError("stable installation key did not survive restart")
        code, integrity = _json(
            base_url, "GET", "/api/v1/system/security-integrity", token=token
        )
        if code != 200 or integrity["audit_chain"]["valid"] is not True:
            raise RuntimeError(f"audit chain verification failed: {integrity}")
        damaged = bytearray(encrypted_path.read_bytes())
        damaged[-1] ^= 1
        encrypted_path.write_bytes(damaged)
        code, _, _ = _request(
            base_url,
            "GET",
            f"/api/v1/research/artifacts/{artifact_id}/download",
            token=token,
        )
        if code != 409:
            raise RuntimeError(f"tampered ciphertext returned HTTP {code}, expected 409")
        code, integrity_after = _json(
            base_url, "GET", "/api/v1/system/security-integrity", token=token
        )
        if code != 200 or integrity_after["audit_chain"]["valid"] is not True:
            raise RuntimeError("failed-download audit event broke the valid chain")
        summary = {
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "executable": str(executable),
            "executable_bytes": executable.stat().st_size,
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest().upper(),
            "profile_root": str(profile_root),
            "fresh_profile_setup": True,
            "encrypted_envelope": True,
            "plaintext_absent_from_disk_envelope": True,
            "restart_decryption": True,
            "tamper_blocked_http": 409,
            "audit_chain_valid": integrity_after["audit_chain"]["valid"],
            "chained_entries": integrity_after["audit_chain"]["chained_entries"],
            "encrypted_artifacts": integrity_after["artifacts"]["encrypted"],
        }
        output = profile_root / "frozen-security-result.json"
        output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=True))
    finally:
        _stop(second, lock_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
