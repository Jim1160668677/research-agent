"""RO-Crate 研究结果导出器。

生成符合 Research Object Crate (RO-Crate) 规范的研究结果压缩包，
包含 JSON-LD 元数据、所有相关制品和可复现性信息。

规格参考：https://www.researchobject.org/ro-crate/
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..research.artifacts import ArtifactError


# RO-Crate 必需的核心元数据关键字段
_CORE_METADATA = {
    "@context": "https://w3id.org/ro/crate/1.1/context",
    "@graph": [],
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_entity(
    identifier: str,
    type_: str | list[str],
    name: str,
    additional: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "@id": identifier,
        "@type": type_,
        "name": name,
    }
    if additional:
        entity.update(additional)
    return entity


def _entity_for_artifact(artifact: dict[str, Any], run_id: str) -> dict[str, Any]:
    """为单个制品生成 RO-Crate entity。"""
    entity = _make_entity(
        identifier=f"artifacts/{quote(artifact['name'])}",
        type_=["File", "FileObject"],
        name=artifact["name"],
        additional={
            "encodingFormat": artifact.get("media_type") or "application/octet-stream",
            "sha256": artifact["sha256"],
            "contentSize": str(artifact.get("size_bytes", 0)),
        },
    )
    if artifact.get("summary"):
        entity["description"] = json.dumps(artifact["summary"], ensure_ascii=False)
    if artifact.get("created_at"):
        entity["dateCreated"] = str(artifact["created_at"])
    return entity


def _entity_for_run(run: dict[str, Any]) -> dict[str, Any]:
    """为科研运行生成 RO-Crate 主 entity。"""
    steps = run.get("steps") or []
    plan = run.get("plan") or {}
    result = run.get("result") or {}
    evidence = run.get("evidence") or []

    pipeline_ids = set()
    for step in steps:
        cap = step.get("capability", "")
        if cap.startswith("pipeline_"):
            pipeline_ids.add(cap)

    entity = _make_entity(
        identifier="#",
        type_=["ScholarlyArticle", "ResearchArticle"],
        name=run.get("objective", "Research Run"),
        additional={
            "datePublished": str(run.get("created_at") or _utcnow_iso()),
            "description": result.get("summary") or result.get("message") or "",
            "keywords": (plan.get("domains") or []) + (result.get("domains") or []),
            "author": [],  # placeholder - will be filled from user profile if available
            "about": [],
            "generatedBy": [
                {
                    "@id": "#software",
                    "@type": "SoftwareApplication",
                    "name": "Research Agent",
                    "version": "1.5+",
                    "url": "https://github.com/research-agent",
                }
            ],
            "workflowDescription": "\n".join(
                f"- {step.get('title', step.get('key', '?'))}: {step.get('capability', '-')}"
                for step in steps
            ) or "-",
            "status": run.get("status", "unknown"),
            "progress": str(run.get("progress", 0)),
            "totalSteps": str(len(steps)),
            "evidenceCount": str(len(evidence)),
            "confidence": str(result.get("confidence", 0.0)),
            "runId": run.get("id", ""),
        },
    )
    return entity


def _build_rocrate_payload(
    run: dict[str, Any],
    artifacts: list[dict[str, Any]],
    pipeline_runs: list[dict[str, Any]],
    store_root: Path | None = None,
) -> tuple[bytes, str]:
    """构建 RO-Crate zip 二进制内容。"""

    output_buffer = io.BytesIO()

    # Collect artifact bytes for inclusion in the crate
    artifact_files: dict[str, bytes] = {}
    if store_root is not None:
        for artifact in artifacts:
            try:
                from ..research.artifacts import ArtifactStore
                store = ArtifactStore(store_root)
                with store.materialize(artifact) as path:
                    raw = path.read_bytes()
                    artifact_files[artifact["name"]] = raw
            except Exception:
                # Skip artifacts that cannot be read
                pass

    with zipfile.ZipFile(output_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # --- ro-crate-metadata.json (root metadata) ---
        graph: list[dict[str, Any]] = []

        # Main entity
        graph.append(_entity_for_run(run))

        # Software entity
        graph.append({
            "@id": "#software",
            "@type": "SoftwareApplication",
            "name": "Research Agent",
            "version": "1.5+",
            "url": "https://github.com/research-agent",
            "programmingLanguage": "Python",
            "operatingSystem": "Windows / Linux (WSL2)",
            "description": "本地生物信息学研究与分析平台",
        })

        # Pipeline entities
        for pr in pipeline_runs:
            pid = pr.get("pipeline_id", "unknown")
            rev = pr.get("revision", "unknown")
            graph.append({
                "@id": f"#pipeline/{hashlib.md5(pid.encode()).hexdigest()[:8]}",
                "@type": ["Workflow", "SoftwareSourceCode"],
                "name": f"{pid}@{rev}",
                "softwareVersion": rev,
                "profile": pr.get("profile", ""),
                "status": pr.get("status", "unknown"),
                "error": pr.get("error") or "",
            })

        # Artifact entities
        for artifact in artifacts:
            graph.append(_entity_for_artifact(artifact, run.get("id", "")))

        # Evidence entities
        for idx, ev in enumerate((run.get("evidence") or [])[:100]):
            graph.append({
                "@id": f"#evidence/{idx}",
                "@type": "CreativeWork",
                "name": f"Evidence {idx + 1}",
                "sourceType": ev.get("source_type", "unknown"),
                "id": ev.get("id", ""),
                "locator": ev.get("locator") or ev.get("url") or "",
                "summary": ev.get("summary") or "",
            })

        # Results summary entity
        result = run.get("result") or {}
        if result:
            graph.append({
                "@id": "#result",
                "@type": "Dataset",
                "name": "Run Results Summary",
                "description": json.dumps(result, ensure_ascii=False, default=str)[:2000],
            })

        # Step entities (detailed)
        for step in (run.get("steps") or [])[:50]:
            graph.append({
                "@id": f"#step/{step.get('key', '')}",
                "@type": "Method",
                "name": step.get("title", step.get("key", "?")),
                "capability": step.get("capability", ""),
                "status": step.get("status", "pending"),
                "dependencies": step.get("dependencies") or [],
                "confidence": str(step.get("confidence", "")),
                "durationMs": str(step.get("duration_ms", "")),
                "error": step.get("error") or "",
                "warnings": step.get("warnings") or [],
                "inputData": json.dumps(step.get("input_data") or {}, ensure_ascii=False),
                "outputData": json.dumps(step.get("output_data") or {}, ensure_ascii=False),
            })

        root_metadata = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": graph,
        }

        zf.writestr("ro-crate-metadata.json", json.dumps(root_metadata, ensure_ascii=False, indent=2))

        # --- data/ directory with artifacts ---
        for name, raw in artifact_files.items():
            safe_name = Path(name).name
            zf.writestr(f"data/{safe_name}", raw)

        # --- brief.md ---
        from ..reporting.brief import build_brief_markdown
        pipeline_runs_out = [
            {
                "pipeline_id": pr.get("pipeline_id", "-"),
                "revision": pr.get("revision", "-"),
                "profile": pr.get("profile", "-"),
                "status": pr.get("status", "-"),
                "task_summary": (pr.get("task_summary") or {}),
                "error": pr.get("error") or "",
            }
            for pr in pipeline_runs
        ]
        brief = build_brief_markdown(run, artifacts, pipeline_runs_out)
        zf.writestr("brief.md", brief)

        # --- provenance.json ---
        provenance = {
            "generatedAt": _utcnow_iso(),
            "generator": "Research Agent RO-Crate Exporter v1.0",
            "runId": run.get("id", ""),
            "userId": run.get("user_id", ""),
            "objective": run.get("objective", ""),
            "status": run.get("status", ""),
            "created": str(run.get("created_at", "")),
            "completed": str(run.get("completed_at", "")),
            "artifactCount": len(artifacts),
            "pipelineRunCount": len(pipeline_runs),
            "evidenceCount": len(run.get("evidence") or []),
            "sha256Crate": "",
        }
        crate_bytes = output_buffer.getvalue()
        provenance["sha256Crate"] = _sha256_bytes(crate_bytes)

        zf.writestr("provenance.json", json.dumps(provenance, ensure_ascii=False, indent=2))

    return output_buffer.getvalue(), f"ro-crate-{quote(run.get('id', 'run'))}.zip"


async def generate_rocrate(
    run: dict[str, Any],
    artifacts: list[dict[str, Any]],
    pipeline_runs: list[dict[str, Any]],
    store_root: Path | None = None,
) -> tuple[bytes, str]:
    """生成 RO-Crate zip 包，返回 (bytes, filename)。"""
    payload, filename = _build_rocrate_payload(run, artifacts, pipeline_runs, store_root)
    return payload, filename


__all__ = ["generate_rocrate"]
