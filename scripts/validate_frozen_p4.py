"""Validate the P4 model and Co-Scientist flow in the packaged desktop app."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def request(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str = "",
    payload: dict | None = None,
    timeout: int = 30,
) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base_url + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else {}


def wait_for_api(lock_file: Path, process: subprocess.Popen) -> tuple[str, dict]:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"desktop process exited early: {process.returncode}")
        if lock_file.is_file():
            try:
                lock = json.loads(lock_file.read_text(encoding="utf-8"))
                base_url = f"http://127.0.0.1:{int(lock['port'])}"
                code, health = request(base_url, "GET", "/health")
                if code == 200 and health.get("status") == "healthy":
                    return base_url, lock
            except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
                pass
        time.sleep(0.25)
    raise RuntimeError("packaged desktop API did not become healthy")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--profile-root", type=Path, required=True)
    parser.add_argument("--live-agnes", action="store_true")
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
    environment = {**os.environ, "APPDATA": str(appdata)}
    process = subprocess.Popen(
        [str(executable)],
        cwd=str(executable.parent),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        base_url, lock = wait_for_api(lock_file, process)
        code, health = request(base_url, "GET", "/health")
        if code != 200 or health.get("version") != "1.3.0":
            raise RuntimeError(f"unexpected packaged version: {health}")
        code, auth = request(
            base_url,
            "POST",
            "/api/v1/auth/setup",
            payload={
                "username": "p4_acceptance_owner",
                "password": "P4-Acceptance-Only!",
                "email": "p4-acceptance@example.org",
            },
        )
        if code != 200:
            raise RuntimeError(f"first-run setup failed: {auth}")
        token = str(auth["access_token"])

        code, model_status = request(base_url, "GET", "/api/v1/llm/status", token=token)
        providers = set(model_status.get("available_providers") or [])
        if code != 200 or not {"deepseek", "agnes"} <= providers:
            raise RuntimeError(f"packaged provider registry is incomplete: {model_status}")
        descriptors = {
            item["name"]: item for item in model_status.get("provider_descriptors") or []
        }
        if descriptors.get("agnes", {}).get("execution_mode") != "cli":
            raise RuntimeError("packaged Agnes execution mode is not CLI-first")
        agnes_live = None
        if args.live_agnes:
            code, agnes_live = request(
                base_url,
                "POST",
                "/api/v1/llm/providers/agnes/health?live=true",
                token=token,
                timeout=180,
            )
            if code != 200 or agnes_live.get("success") is not True:
                raise RuntimeError(f"packaged Agnes live check failed: {agnes_live}")

        code, missing_health = request(
            base_url,
            "POST",
            "/api/v1/llm/providers/deepseek/health?live=false",
            token=token,
        )
        if code != 200 or missing_health.get("code") != "missing_api_key":
            raise RuntimeError(f"missing-key diagnostic is incorrect: {missing_health}")
        code, blocked_preference = request(
            base_url,
            "PUT",
            "/api/v1/llm/preference",
            token=token,
            payload={"provider": "deepseek", "model": "deepseek-v4-pro"},
        )
        if code != 409:
            raise RuntimeError(
                f"unconfigured provider preference was not blocked: {blocked_preference}"
            )

        objective = "基于炎症通路证据生成可检验机制假设并设计验证实验，形成规范科研简报"
        code, created = request(
            base_url,
            "POST",
            "/api/v1/research/runs",
            token=token,
            payload={
                "objective": objective,
                "domains": ["literature", "discovery", "experiment", "writing", "integrity"],
                "context": {
                    "literature_records": [
                        {
                            "pmid": "P4-1001",
                            "title": "Inflammatory pathway and target response",
                            "abstract": "Perturbation changes a measurable target response.",
                            "year": "2025",
                        },
                        {
                            "pmid": "P4-1002",
                            "title": "Rescue experiments distinguish inflammatory mechanisms",
                            "abstract": "A rescue arm distinguishes alternative mechanisms.",
                            "year": "2024",
                        },
                    ]
                },
                "network_allowed": True,
                "max_concurrency": 3,
                "execute": True,
            },
        )
        if code != 201:
            raise RuntimeError(f"research run creation failed: {created}")
        run_id = str(created["id"])
        deadline = time.monotonic() + 60
        detail = created
        while time.monotonic() < deadline:
            code, detail = request(base_url, "GET", f"/api/v1/research/runs/{run_id}", token=token)
            if code != 200:
                raise RuntimeError(f"research run read failed: {detail}")
            if detail.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                break
            time.sleep(0.1)
        if detail.get("status") != "completed" or detail.get("progress") != 100:
            raise RuntimeError(f"Co-Scientist flow did not complete: {detail}")
        steps = {item["key"]: item for item in detail.get("steps") or []}
        expected = [
            "literature",
            "generation",
            "reflection",
            "ranking",
            "evolution",
            "meta_review",
            "experiment",
            "writing",
            "integrity",
        ]
        if list(steps) != expected:
            raise RuntimeError(f"unexpected discovery chain: {list(steps)}")
        if any(steps[key]["status"] not in {"completed", "degraded"} for key in expected):
            raise RuntimeError(f"one or more discovery stages failed: {steps}")
        if not steps["generation"]["output"].get("candidates"):
            raise RuntimeError("hypothesis generation returned no candidates")
        if not steps["meta_review"]["output"].get("recommended_hypotheses"):
            raise RuntimeError("meta-review returned no recommendation")

        code, runtime = request(base_url, "GET", "/api/v1/system/runtime", token=token)
        if code != 200 or runtime.get("active") != 0 or runtime.get("waiting") != 0:
            raise RuntimeError(f"global runtime did not drain: {runtime}")
        summary = {
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "version": health["version"],
            "process_id": process.pid,
            "lock_process_id_matches": lock.get("pid") == process.pid,
            "providers": sorted(providers),
            "agnes_execution_mode": descriptors["agnes"]["execution_mode"],
            "agnes_live": (
                {
                    "success": agnes_live.get("success"),
                    "model": agnes_live.get("model"),
                    "latency_ms": agnes_live.get("latency_ms"),
                    "cli_version": agnes_live.get("cli_version"),
                }
                if agnes_live
                else None
            ),
            "deepseek_missing_key_code": missing_health["code"],
            "unconfigured_preference_http": 409,
            "research_run_id": run_id,
            "research_status": detail["status"],
            "research_progress": detail["progress"],
            "research_steps": list(steps),
            "runtime_after_completion": {
                "active": runtime["active"],
                "waiting": runtime["waiting"],
            },
        }
        output = profile_root / "frozen-p4-result.json"
        output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
