"""Exercise the packaged desktop executable through its loopback API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


_LOCAL_MONITOR = re.compile(
    r"Creating local task monitor .*cpus=(?P<cpus>\d+); "
    r"memory=(?P<memory>[^;]+); capacity=(?P<capacity>\d+)"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _execution_evidence(data_dir: Path, run_id: str) -> dict[str, object]:
    candidates = list((data_dir / "pipeline-runs").glob(f"user-*/run-{run_id}"))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one managed run directory, found {len(candidates)}")
    run_root = candidates[0]
    log_path = run_root / "nextflow.log"
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    monitor = _LOCAL_MONITOR.search(log_text)
    if monitor is None:
        raise RuntimeError("Nextflow did not report the resolved local executor limits")
    resolved = {
        "cpus": int(monitor.group("cpus")),
        "memory": monitor.group("memory").strip(),
        "capacity": int(monitor.group("capacity")),
    }
    if resolved != {"cpus": 4, "memory": "7 GB", "capacity": 1}:
        raise RuntimeError(f"unexpected resolved local executor limits: {resolved}")

    active = peak_active = completed_events = 0
    for line in log_text.splitlines():
        if "Submitted process >" in line:
            active += 1
            peak_active = max(peak_active, active)
        elif "Task completed >" in line:
            active -= 1
            completed_events += 1
            if active < 0:
                raise RuntimeError("Nextflow task event accounting became negative")
    if active != 0 or peak_active > 1:
        raise RuntimeError(
            f"local executor concurrency escaped its single slot: active={active}, peak={peak_active}"
        )
    if "Pipeline completed successfully" not in log_text:
        raise RuntimeError("Nextflow success marker is missing")

    report_paths = {
        "report": run_root / "reports" / "report.html",
        "timeline": run_root / "reports" / "timeline.html",
        "trace": run_root / "reports" / "trace.tsv",
        "dag": run_root / "reports" / "dag.html",
        "nextflow_log": log_path,
    }
    reports: dict[str, object] = {}
    for name, path in report_paths.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"required report is missing or empty: {path}")
        reports[name] = {
            "relative_path": path.relative_to(run_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    multiqc = list((run_root / "results").glob("**/multiqc_report.html"))
    if len(multiqc) != 1:
        raise RuntimeError(f"expected one MultiQC report, found {len(multiqc)}")
    reports["multiqc"] = {
        "relative_path": multiqc[0].relative_to(run_root).as_posix(),
        "bytes": multiqc[0].stat().st_size,
        "sha256": _sha256(multiqc[0]),
    }
    return {
        "resolved_local_executor": resolved,
        "observed_submitted_peak": peak_active,
        "completed_task_events": completed_events,
        "reports": reports,
    }


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, object] | None = None,
    token: str | None = None,
    timeout: float = 60,
) -> tuple[int, dict[str, object]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url}{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned {exc.code}: {response_body[:500]}") from exc


def _wait_for_lock(
    lock_file: Path, process: subprocess.Popen[bytes]
) -> tuple[str, dict[str, object]]:
    deadline = time.monotonic() + 90
    last_error = "desktop lock was not created"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"desktop process exited early with status {process.returncode}")
        try:
            record = json.loads(lock_file.read_text(encoding="utf-8"))
            port = record.get("port")
            if isinstance(port, int) and port > 0:
                base_url = f"http://127.0.0.1:{port}"
                status, health = _request(base_url, "GET", "/health", timeout=3)
                if status == 200 and health.get("status") == "healthy":
                    return base_url, record
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"desktop API did not become healthy: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--profile-root", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--execution-timeout", type=int, default=7200)
    parser.add_argument("--reuse-profile", action="store_true")
    parser.add_argument("--resume-run-id")
    args = parser.parse_args()
    if args.resume_run_id and not args.reuse_profile:
        parser.error("--resume-run-id requires --reuse-profile")
    executable = args.exe.resolve()
    if not executable.is_file():
        raise SystemExit(f"Packaged executable is missing: {executable}")
    profile_root = args.profile_root.resolve()
    appdata = profile_root / "AppData" / "Roaming"
    appdata.mkdir(parents=True, exist_ok=args.reuse_profile)
    data_dir = appdata / "ResearchAgent"
    lock_file = data_dir / "ResearchAgent.lock"
    environment = {**os.environ, "APPDATA": str(appdata)}
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        [str(executable)],
        env=environment,
        cwd=str(executable.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    try:
        base_url, lock = _wait_for_lock(lock_file, process)
        _, status = _request(base_url, "GET", "/api/v1/auth/status")
        credentials = {
            "username": "p2_smoke_owner",
            "password": "P2-Smoke-Only-Password!",
        }
        performed_first_run_setup = status.get("initialized") is False
        if status.get("initialized") is True and args.reuse_profile:
            _, setup = _request(
                base_url,
                "POST",
                "/api/v1/auth/login",
                payload=credentials,
            )
        elif status.get("initialized") is False:
            _, setup = _request(
                base_url,
                "POST",
                "/api/v1/auth/setup",
                payload={**credentials, "email": "p2-smoke@example.org"},
            )
        else:
            raise RuntimeError("frozen profile initialization state does not match the request")
        token = str(setup.get("access_token") or "")
        if not token:
            raise RuntimeError("first-run setup returned no access token")
        _, capabilities = _request(
            base_url,
            "GET",
            "/api/v1/pipelines/capabilities?deep=true",
            token=token,
            timeout=90,
        )
        pipeline_request = {
            "pipeline_id": "nf-core/rnaseq",
            "revision": "3.26.0",
            "profile": "docker",
                "parameters": {
                    "test_profile": True,
                    "max_cpus": 4,
                    "max_memory": "7 GB",
            },
            "artifact_bindings": {},
            "network_allowed": True,
            "timeout_seconds": 3600,
        }
        _, preflight = _request(
            base_url,
            "POST",
            "/api/v1/pipelines/preflight",
            token=token,
            payload=pipeline_request,
            timeout=90,
        )
        if args.resume_run_id:
            _, planned = _request(
                base_url,
                "GET",
                f"/api/v1/pipelines/runs/{args.resume_run_id}",
                token=token,
            )
            _request(
                base_url,
                "POST",
                f"/api/v1/pipelines/runs/{args.resume_run_id}/resume",
                token=token,
                timeout=90,
            )
            args.execute = True
        else:
            _, planned = _request(
                base_url,
                "POST",
                "/api/v1/pipelines/runs",
                token=token,
                payload={**pipeline_request, "execute": args.execute},
            )
        final_run = planned
        if args.execute:
            run_id = str(planned.get("id") or "")
            deadline = time.monotonic() + args.execution_timeout
            terminal = {"completed", "failed", "cancelled", "interrupted"}
            while time.monotonic() < deadline:
                _, final_run = _request(
                    base_url,
                    "GET",
                    f"/api/v1/pipelines/runs/{run_id}",
                    token=token,
                    timeout=30,
                )
                if final_run.get("status") in terminal:
                    break
                time.sleep(2)
            else:
                raise RuntimeError(
                    f"packaged pipeline did not reach a terminal state in "
                    f"{args.execution_timeout} seconds"
                )
            if final_run.get("status") != "completed":
                raise RuntimeError(
                    "packaged pipeline failed: "
                    + str(final_run.get("error") or final_run.get("result"))[:1000]
                )
        result = dict(final_run.get("result") or {})
        task_summary = dict(result.get("task_summary") or {})
        output_manifest = dict(task_summary.get("output_manifest") or {})
        if preflight.get("ready") is not True:
            raise RuntimeError(f"packaged preflight was not ready: {preflight}")
        if capabilities.get("available") is not True:
            raise RuntimeError(f"packaged Nextflow runtime was unavailable: {capabilities}")
        if lock.get("pid") != process.pid:
            raise RuntimeError("single-instance lock does not identify the launched process")
        public_argv = list(dict(planned.get("plan") or {}).get("argv") or [])
        if "<wsl-private-work-dir>" not in public_argv:
            raise RuntimeError("public execution plan did not redact the private WSL work path")
        if args.execute:
            if result.get("exit_code") != 0:
                raise RuntimeError(f"packaged pipeline returned exit code {result.get('exit_code')}")
            if task_summary.get("tasks") != 234 or task_summary.get("failed"):
                raise RuntimeError(f"unexpected packaged task summary: {task_summary}")
            if output_manifest.get("truncated") or output_manifest.get(
                "hash_budget_exhausted"
            ):
                raise RuntimeError(f"incomplete packaged result manifest: {output_manifest}")
        summary = {
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "profile_root": str(profile_root),
            "process_id": process.pid,
            "lock_process_id_matches": lock.get("pid") == process.pid,
            "health": "healthy",
            "authenticated": True,
            "first_run_setup": performed_first_run_setup,
            "nextflow": {
                "available": capabilities.get("available"),
                "version": capabilities.get("version"),
                "transport": capabilities.get("transport"),
                "docker_ready": dict(capabilities.get("profiles") or {}).get("docker"),
                "work_storage": capabilities.get("work_storage_probe"),
            },
            "preflight": {
                "ready": preflight.get("ready"),
                "issues": preflight.get("issues"),
                "wsl_work_free_bytes": preflight.get("wsl_work_free_bytes"),
            },
            "planned_run": {
                "id": planned.get("id"),
                "status": final_run.get("status"),
                "physical_paths_redacted": "<wsl-private-work-dir>" in public_argv,
            },
            "execution": (
                {
                    "exit_code": result.get("exit_code"),
                    "tasks": task_summary.get("tasks"),
                    "statuses": task_summary.get("statuses"),
                    "failed": task_summary.get("failed"),
                    "result_files": output_manifest.get("files_recorded"),
                    "manifest_truncated": output_manifest.get("truncated"),
                    "hash_budget_exhausted": output_manifest.get("hash_budget_exhausted"),
                    **_execution_evidence(data_dir, str(planned.get("id") or "")),
                }
                if args.execute
                else None
            ),
        }
        result_path = profile_root / "frozen-smoke-result.json"
        result_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=True))
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
