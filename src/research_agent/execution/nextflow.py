"""Allowlisted, revision-pinned Nextflow/nf-core execution backend."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from ..core.app import settings
from .base import ExecutionBackend, ExecutionPlan, ExecutionResult

PIPELINES: dict[str, dict[str, Any]] = {
    "nf-core/rnaseq": {
        "title": "nf-core/rnaseq",
        "description": "RNA-seq alignment, quantification and quality-control pipeline.",
        "revision": "3.26.0",
        "commit_sha": "e7ca46272c8f9d5ceee3f71759f4ba551d3217a4",
        "minimum_nextflow": "25.04.3",
        "source_url": "https://github.com/nf-core/rnaseq",
        "artifact_parameters": {
            "input": {"required": True, "suffixes": [".csv"]},
            "fasta": {"required": False, "suffixes": [".fa", ".fasta", ".fna", ".txt"]},
            "gtf": {"required": False, "suffixes": [".gtf", ".txt"]},
        },
        "parameters": {
            "test_profile": {"type": "boolean", "control": True},
            "genome": {"type": "string", "max_length": 80},
            "aligner": {
                "type": "enum",
                "values": ["star_salmon", "star_rsem", "hisat2", "hisat2_rsem"],
            },
            "skip_trimming": {"type": "boolean"},
            "save_reference": {"type": "boolean"},
            "max_cpus": {
                "type": "integer",
                "minimum": 1,
                "maximum": 256,
                "control": True,
            },
            "max_memory": {"type": "memory", "control": True},
        },
    },
    "nf-core/sarek": {
        "title": "nf-core/sarek",
        "description": "Germline and somatic variant calling and annotation pipeline.",
        "revision": "3.9.0",
        "commit_sha": "b97952e5bac68d5deb93d4a3349a45f146be9830",
        "minimum_nextflow": "25.10.2",
        "source_url": "https://github.com/nf-core/sarek",
        "artifact_parameters": {
            "input": {"required": True, "suffixes": [".csv"]},
            "fasta": {"required": False, "suffixes": [".fa", ".fasta", ".fna", ".txt"]},
            "intervals": {"required": False, "suffixes": [".bed", ".interval_list", ".txt"]},
        },
        "parameters": {
            "genome": {"type": "string", "max_length": 80},
            "wes": {"type": "boolean"},
            "tools": {
                "type": "enum",
                "values": ["haplotypecaller", "deepvariant", "mutect2", "strelka"],
            },
            "step": {
                "type": "enum",
                "values": [
                    "mapping",
                    "markduplicates",
                    "prepare_recalibration",
                    "recalibrate",
                    "variant_calling",
                    "annotate",
                ],
            },
            "max_cpus": {
                "type": "integer",
                "minimum": 1,
                "maximum": 256,
                "control": True,
            },
            "max_memory": {"type": "memory", "control": True},
        },
    },
}

# One engine version is used for probes and executions so a self-installing
# Nextflow launcher cannot silently move a validated desktop installation to a
# newer release.  It satisfies the strictest minimum across the pinned
# pipelines above (currently nf-core/sarek).
NEXTFLOW_VERSION = "25.10.2"
_RNASEQ_TEST_GENERAL_REVISION = "626c8fab639062eade4b10747e919341cbf9b41a"
_RNASEQ_TEST_READS_REVISION = "e07c1b158d1c4c9ea7978959d31e651098bec581"
_RNASEQ_TEST_KRAKEN_REVISION = "eb0cbf73c3f103f8aeda9878ba200e92b4d045d8"
_TEST_DATA_CDN = "https://cdn.jsdelivr.net/gh/nf-core/test-datasets@"
_RNASEQ_TEST_ROWS = (
    ("WT_REP1", "SRR6357070_1.fastq.gz", "SRR6357070_2.fastq.gz", "auto"),
    ("WT_REP1", "SRR6357071_1.fastq.gz", "SRR6357071_2.fastq.gz", "auto"),
    ("WT_REP2", "SRR6357072_1.fastq.gz", "SRR6357072_2.fastq.gz", "reverse"),
    ("RAP1_UNINDUCED_REP1", "SRR6357073_1.fastq.gz", "", "reverse"),
    ("RAP1_UNINDUCED_REP2", "SRR6357074_1.fastq.gz", "", "reverse"),
    ("RAP1_UNINDUCED_REP2", "SRR6357075_1.fastq.gz", "", "reverse"),
    ("RAP1_IAA_30M_REP1", "SRR6357076_1.fastq.gz", "SRR6357076_2.fastq.gz", "reverse"),
)

PROFILES = {
    "docker": "docker",
    "podman": "podman",
    "singularity": "singularity",
    "apptainer": "apptainer",
    "conda": "conda",
}
_PROFILE_PROBE_ARGS = {
    "docker": ["info", "--format", "{{.ServerVersion}}"],
    "podman": ["info", "--format", "{{.Version.Version}}"],
    "singularity": ["version"],
    "apptainer": ["version"],
    "conda": ["--version"],
}
_SAFE_STRING = re.compile(r"^[A-Za-z0-9_.:+,/ -]{1,200}$")
_SAFE_MEMORY = re.compile(r"^([1-9][0-9]{0,5}(?:\.[0-9]+)?)\s*(KB|MB|GB|TB)$", re.I)
_VERSION = re.compile(r"(?:nextflow\s+version\s+|version\s+)([0-9]+(?:\.[0-9]+){1,3})", re.I)
_TAIL_BYTES = 64 * 1024
_MAX_TRACE_BYTES = 16 * 1024 * 1024
_MAX_TRACE_ROWS = 20_000
_MAX_OUTPUT_FILES = 2_000
_MAX_OUTPUT_HASH_BYTES = 2 * 1024 * 1024 * 1024
_RESOURCE_DEFAULTS = {"max_cpus": 8, "max_memory": "32 GB"}
_MEMORY_MULTIPLIERS = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
_WSL_WORK_TOKEN = "__RESEARCH_AGENT_WSL_EXT4_WORK_DIR__"
_WSL_RUNNER = """#!/usr/bin/env bash
set -euo pipefail
umask 077
pid_file="$1"
work_path_file="$2"
run_key="$3"
shift 3
if [ "${1:-}" = "--" ]; then shift; fi
if [[ ! "$run_key" =~ ^user-[0-9]+/run-[a-f0-9-]{36}$ ]]; then
    printf 'Invalid managed WSL work key\\n' >&2
    exit 64
fi
home_real="$(realpath -e "$HOME")"
work_root="$home_real/research-agent-data/pipeline-work"
work_dir="$work_root/$run_key"
mkdir -p "$work_dir"
chmod 700 "$work_root" "$work_dir"
work_dir="$(realpath -e "$work_dir")"
case "$work_dir" in
    "$home_real"/*) ;;
    *) printf 'Managed WSL work directory escaped HOME\\n' >&2; exit 73 ;;
esac
if [ ! -w "$work_dir" ]; then
    printf 'Managed WSL work directory is not writable\\n' >&2
    exit 73
fi
printf '%s' "$work_dir" > "$work_path_file"
args=()
for arg in "$@"; do
    if [ "$arg" = "__RESEARCH_AGENT_WSL_EXT4_WORK_DIR__" ]; then
        args+=("$work_dir")
    else
        args+=("$arg")
    fi
done
setsid "${args[@]}" &
child_pid=$!
printf '%s' "$child_pid" > "$pid_file"
wait "$child_pid"
"""


def pipeline_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": pipeline_id,
            "title": item["title"],
            "description": item["description"],
            "revision": item["revision"],
            "commit_sha": item["commit_sha"],
            "minimum_nextflow": item["minimum_nextflow"],
            "nextflow_version": NEXTFLOW_VERSION,
            "source_url": item["source_url"],
            "artifact_parameters": item["artifact_parameters"],
            "parameters": item["parameters"],
            "profiles": list(PROFILES),
        }
        for pipeline_id, item in PIPELINES.items()
    ]


def validate_request(
    pipeline_id: str,
    revision: str,
    profile: str,
    parameters: dict[str, Any],
    artifact_bindings: dict[str, str],
) -> dict[str, Any]:
    spec = PIPELINES.get(pipeline_id)
    if spec is None:
        raise ValueError("Pipeline is not in the administrator allowlist")
    if revision != spec["revision"]:
        raise ValueError(f"Only the pinned revision {spec['revision']} is allowed")
    if profile not in PROFILES:
        raise ValueError("Unsupported Nextflow execution profile")
    unknown = sorted(set(parameters) - set(spec["parameters"]))
    if unknown:
        raise ValueError(f"Unknown pipeline parameter: {unknown[0]}")
    unknown_artifacts = sorted(set(artifact_bindings) - set(spec["artifact_parameters"]))
    if unknown_artifacts:
        raise ValueError(f"Unknown artifact parameter: {unknown_artifacts[0]}")
    test_profile = pipeline_id == "nf-core/rnaseq" and parameters.get("test_profile") is True
    if test_profile:
        incompatible = sorted(set(parameters) - {"test_profile", "max_cpus", "max_memory"})
        if incompatible:
            raise ValueError(
                f"The official test profile cannot be combined with parameter {incompatible[0]}"
            )
    missing = [
        name
        for name, rule in spec["artifact_parameters"].items()
        if rule.get("required") and not artifact_bindings.get(name) and not test_profile
    ]
    if missing:
        raise ValueError(f"Missing required artifact binding: {missing[0]}")

    has_genome = bool(parameters.get("genome"))
    if pipeline_id == "nf-core/rnaseq" and not test_profile:
        has_custom_reference = bool(artifact_bindings.get("fasta") or artifact_bindings.get("gtf"))
        if has_genome and has_custom_reference:
            raise ValueError("Choose either a genome catalogue entry or custom FASTA and GTF files")
        if not has_genome and not (artifact_bindings.get("fasta") and artifact_bindings.get("gtf")):
            raise ValueError("RNA-seq requires a genome entry or both custom FASTA and GTF files")
    elif pipeline_id == "nf-core/sarek":
        has_fasta = bool(artifact_bindings.get("fasta"))
        if has_genome and has_fasta:
            raise ValueError("Choose either a genome catalogue entry or a custom FASTA file")
        if not has_genome and not has_fasta:
            raise ValueError("Sarek requires a genome entry or a custom FASTA file")

    normalized: dict[str, Any] = {}
    for name, value in parameters.items():
        rule = spec["parameters"][name]
        kind = rule["type"]
        if kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"Parameter {name} must be boolean")
        elif kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"Parameter {name} must be an integer")
            if not rule["minimum"] <= value <= rule["maximum"]:
                raise ValueError(f"Parameter {name} is outside its allowed range")
        elif kind == "enum":
            if value not in rule["values"]:
                raise ValueError(f"Parameter {name} is not an allowed value")
        elif kind == "memory":
            match = _SAFE_MEMORY.fullmatch(value.strip()) if isinstance(value, str) else None
            if not match:
                raise ValueError(f"Parameter {name} must be a bounded memory value such as 16 GB")
            number_text, unit = match.groups()
            unit = unit.upper()
            value = f"{number_text} {unit}"
            memory_bytes = float(number_text) * _MEMORY_MULTIPLIERS[unit]
            if not 512 * 1024**2 <= memory_bytes <= 2 * 1024**4:
                raise ValueError(f"Parameter {name} must be between 512 MB and 2 TB")
        elif kind == "string":
            if (
                not isinstance(value, str)
                or len(value) > rule["max_length"]
                or not _SAFE_STRING.fullmatch(value)
            ):
                raise ValueError(f"Parameter {name} contains unsupported characters")
        normalized[name] = value
    for name, value in _RESOURCE_DEFAULTS.items():
        if name in spec["parameters"]:
            normalized.setdefault(name, value)
    return normalized


def validate_samplesheet(pipeline_id: str, path: Path) -> dict[str, Any]:
    """Apply the pinned nf-core input contract before allocating compute."""
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Samplesheet exceeds the 16 MiB validation limit")
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = [str(item or "").strip() for item in (reader.fieldnames or [])]
        if pipeline_id == "nf-core/rnaseq":
            expected = ["sample", "fastq_1", "fastq_2", "strandedness"]
            if headers[:4] != expected:
                raise ValueError(
                    "nf-core/rnaseq samplesheet must start with: " + ",".join(expected)
                )
        elif pipeline_id == "nf-core/sarek":
            required = {"patient", "sample"}
            missing = sorted(required - set(headers))
            if missing:
                raise ValueError(f"nf-core/sarek samplesheet is missing column: {missing[0]}")
            if not set(headers).intersection({"fastq_1", "bam", "cram", "vcf"}):
                raise ValueError(
                    "nf-core/sarek samplesheet needs a FASTQ, BAM, CRAM, or VCF input column"
                )
        rows = 0
        row_keys: set[tuple[str, ...]] = set()
        for row_number, row in enumerate(reader, start=2):
            rows += 1
            if rows > 100_000:
                raise ValueError("Samplesheet exceeds the 100,000-row validation limit")
            if pipeline_id == "nf-core/rnaseq":
                sample = str(row.get("sample") or "").strip()
                fastq_1 = str(row.get("fastq_1") or "").strip()
                fastq_2 = str(row.get("fastq_2") or "").strip()
                strandedness = str(row.get("strandedness") or "").strip().lower()
                if not sample or not fastq_1:
                    raise ValueError(
                        f"rnaseq samplesheet row {row_number} needs sample and fastq_1"
                    )
                if not fastq_1.lower().endswith((".fastq.gz", ".fq.gz")):
                    raise ValueError(f"rnaseq samplesheet row {row_number} has an invalid fastq_1")
                if fastq_2 and not fastq_2.lower().endswith((".fastq.gz", ".fq.gz")):
                    raise ValueError(f"rnaseq samplesheet row {row_number} has an invalid fastq_2")
                if strandedness not in {"auto", "forward", "reverse", "unstranded"}:
                    raise ValueError(
                        f"rnaseq samplesheet row {row_number} has invalid strandedness"
                    )
                key = (sample, fastq_1, fastq_2)
            else:
                patient = str(row.get("patient") or "").strip()
                sample = str(row.get("sample") or "").strip()
                if not patient or not sample:
                    raise ValueError(f"sarek samplesheet row {row_number} needs patient and sample")
                present_inputs = [
                    str(row.get(name) or "").strip() for name in ("fastq_1", "bam", "cram", "vcf")
                ]
                if not any(present_inputs):
                    raise ValueError(f"sarek samplesheet row {row_number} has no supported input")
                if present_inputs[0] and not str(row.get("lane") or "").strip():
                    raise ValueError(f"sarek FASTQ row {row_number} needs a lane")
                if present_inputs[0] and not present_inputs[0].lower().endswith(
                    (".fastq.gz", ".fq.gz")
                ):
                    raise ValueError(f"sarek samplesheet row {row_number} has an invalid fastq_1")
                fastq_2 = str(row.get("fastq_2") or "").strip()
                if fastq_2 and not fastq_2.lower().endswith((".fastq.gz", ".fq.gz")):
                    raise ValueError(f"sarek samplesheet row {row_number} has an invalid fastq_2")
                key = (patient, sample, str(row.get("lane") or "").strip(), *present_inputs)
            if key in row_keys:
                raise ValueError(f"Samplesheet contains a duplicate input row at line {row_number}")
            row_keys.add(key)
    if rows == 0:
        raise ValueError("Samplesheet contains no data rows")
    return {"rows": rows, "columns": headers}


def _data_root() -> Path:
    configured = os.environ.get("RESEARCH_AGENT_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    prefix = "sqlite+aiosqlite:///"
    if settings.database_url.startswith(prefix):
        return Path(settings.database_url[len(prefix) :]).expanduser().resolve().parent
    return (Path.cwd() / ".research-agent").resolve()


def to_wsl_path(path: Path) -> str:
    """Convert an absolute Windows drive path without invoking a shell."""
    resolved = str(path.resolve())
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", resolved)
    if not match:
        raise ValueError("WSL execution requires a path on a mounted Windows drive")
    tail = match.group(2).replace("\\", "/")
    return f"/mnt/{match.group(1).lower()}/{tail}"


def _tail(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _TAIL_BYTES))
            return handle.read().decode("utf-8", errors="replace")[-16_000:]
    except OSError:
        return ""


def _redact_output(text: str, plan: ExecutionPlan) -> str:
    redacted = text
    replacements: dict[str, str] = {
        str(plan.cwd): "<managed-run-dir>",
        str(plan.work_dir): "<managed-work-dir>",
        str(plan.output_dir): "<managed-output-dir>",
    }
    runtime_work_path = plan.control_paths.get("runtime_work_path")
    if runtime_work_path and runtime_work_path.is_file():
        try:
            physical_work_dir = runtime_work_path.read_text(encoding="utf-8").strip()
        except OSError:
            physical_work_dir = ""
        if physical_work_dir:
            replacements[physical_work_dir] = "<wsl-private-work-dir>"
    for physical, public in zip(plan.argv, plan.display_argv, strict=True):
        if physical != public and ("/" in physical or "\\" in physical):
            replacements.setdefault(physical, public)
    for physical in sorted(replacements, key=len, reverse=True):
        if physical:
            redacted = redacted.replace(physical, replacements[physical])
    return redacted


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _groovy_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _write_rnaseq_test_samplesheet(path: Path) -> None:
    reads = f"{_TEST_DATA_CDN}{_RNASEQ_TEST_READS_REVISION}/testdata/GSE110004"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("sample", "fastq_1", "fastq_2", "strandedness"))
        for sample, read_1, read_2, strandedness in _RNASEQ_TEST_ROWS:
            writer.writerow(
                (
                    sample,
                    f"{reads}/{read_1}",
                    f"{reads}/{read_2}" if read_2 else "",
                    strandedness,
                )
            )


def _write_rnaseq_test_bbsplit_list(path: Path) -> None:
    reference = f"{_TEST_DATA_CDN}{_RNASEQ_TEST_READS_REVISION}/reference"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("sarscov2", f"{reference}/GCA_009858895.3_ASM985889v3_genomic.200409.fna"))
        writer.writerow(("human", f"{reference}/chr22_23800000-23980000.fa"))


def _artifact(path: Path, root: Path, kind: str) -> dict[str, Any]:
    return {
        "name": path.name,
        "kind": kind,
        "relative_path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def parse_trace(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"tasks": 0, "statuses": {}, "failed": []}
    if path.stat().st_size > _MAX_TRACE_BYTES:
        return {
            "tasks": 0,
            "statuses": {},
            "failed": [],
            "warning": "trace exceeded the parsing limit",
        }
    statuses: Counter[str] = Counter()
    failed = []
    rows = 0
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            rows += 1
            status = str(row.get("status") or "UNKNOWN").upper()
            statuses[status] += 1
            if status in {"FAILED", "ABORTED"} and len(failed) < 100:
                failed.append(
                    {
                        "name": str(row.get("name") or "")[:300],
                        "exit": str(row.get("exit") or "")[:30],
                        "hash": str(row.get("hash") or "")[:80],
                    }
                )
            if rows >= _MAX_TRACE_ROWS:
                break
    return {
        "tasks": rows,
        "statuses": dict(statuses),
        "failed": failed,
        "truncated": rows >= _MAX_TRACE_ROWS,
    }


def collect_output_artifacts(
    output: Path, root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a bounded output manifest without following paths outside the run root."""
    artifacts: list[dict[str, Any]] = []
    hashed_bytes = 0
    seen = 0
    truncated = False
    for path in output.rglob("*") if output.is_dir() else []:
        if not path.is_file():
            continue
        seen += 1
        if len(artifacts) >= _MAX_OUTPUT_FILES:
            truncated = True
            break
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(root.resolve()):
                continue
            size = path.stat().st_size
            item = {
                "name": path.name,
                "kind": "result",
                "relative_path": path.relative_to(root).as_posix(),
                "size_bytes": size,
                "sha256": None,
            }
            if hashed_bytes + size <= _MAX_OUTPUT_HASH_BYTES:
                item["sha256"] = _sha256(path)
                hashed_bytes += size
            artifacts.append(item)
        except OSError:
            continue
    return artifacts, {
        "files_seen": seen,
        "files_recorded": len(artifacts),
        "hashed_bytes": hashed_bytes,
        "truncated": truncated,
        "hash_budget_exhausted": any(item["sha256"] is None for item in artifacts),
    }


class NextflowBackend(ExecutionBackend):
    backend_id = "nextflow"

    def __init__(
        self,
        executable: str | None = None,
        root: Path | None = None,
        transport: str | None = None,
    ):
        self.transport = transport or ("native" if executable or os.name != "nt" else "wsl2")
        if self.transport not in {"native", "wsl2"}:
            raise ValueError("Nextflow transport must be native or wsl2")
        self.launcher = shutil.which("wsl.exe") if self.transport == "wsl2" else None
        self.executable = (
            (executable or "nextflow")
            if self.transport == "wsl2"
            else (executable or shutil.which("nextflow"))
        )
        self.root = (root or (_data_root() / "pipeline-runs")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _pipeline_asset(self, pipeline_id: str) -> Path:
        if pipeline_id not in PIPELINES:
            raise ValueError("Pipeline is not in the administrator allowlist")
        asset = (self.root / "nextflow-home" / "assets" / Path(*pipeline_id.split("/"))).resolve()
        assets_root = (self.root / "nextflow-home" / "assets").resolve()
        if not asset.is_relative_to(assets_root):
            raise ValueError("Pipeline cache escaped the managed asset root")
        return asset

    async def _run_git(
        self,
        *arguments: str,
        cwd: Path | None = None,
        timeout: float = 600,
    ) -> bytes:
        executable = shutil.which("git")
        if not executable:
            raise RuntimeError(
                "Git for Windows is required to prefetch a fixed pipeline revision"
            )
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_LFS_SKIP_SMUDGE": "1",
            }
        )
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            cwd=str(cwd) if cwd else None,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError("Timed out while preparing the fixed pipeline cache") from exc
        if process.returncode != 0:
            detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                "Git pipeline cache operation failed: " + (detail[-1000:] or "unknown error")
            )
        return stdout

    async def _inspect_pipeline_cache(
        self, pipeline_id: str, revision: str
    ) -> dict[str, Any]:
        spec = PIPELINES.get(pipeline_id)
        if spec is None:
            return {"ready": False, "status": "invalid", "error": "Pipeline is not allowlisted"}
        if revision != spec["revision"]:
            return {
                "ready": False,
                "status": "invalid",
                "error": f"Only the pinned revision {spec['revision']} is allowed",
            }
        asset = self._pipeline_asset(pipeline_id)
        public = {
            "pipeline": pipeline_id,
            "revision": revision,
            "commit_sha": spec["commit_sha"],
            "source_url": spec["source_url"],
        }
        if not asset.is_dir():
            return {**public, "ready": False, "status": "missing"}
        try:
            head = (
                await self._run_git("-C", str(asset), "rev-parse", "HEAD", timeout=30)
            ).decode("ascii", errors="strict").strip()
            tag_commit = (
                await self._run_git(
                    "-C",
                    str(asset),
                    "rev-parse",
                    f"refs/tags/{revision}^{{commit}}",
                    timeout=30,
                )
            ).decode("ascii", errors="strict").strip()
            if head != spec["commit_sha"] or tag_commit != spec["commit_sha"]:
                raise RuntimeError("Cached pipeline does not match the pinned commit")
            status = await self._run_git(
                "-C",
                str(asset),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                timeout=60,
            )
            if status.strip():
                preview = status.decode("utf-8", errors="replace").strip()[:300]
                raise RuntimeError(
                    "Cached pipeline worktree contains unverified changes: " + preview
                )
            await self._verify_worktree_blobs(asset, "Cached pipeline")
        except (OSError, RuntimeError, UnicodeError) as exc:
            return {**public, "ready": False, "status": "invalid", "error": str(exc)[:500]}
        return {**public, "ready": True, "status": "verified"}

    async def prepare_pipeline(
        self,
        *,
        pipeline_id: str,
        revision: str,
        network_allowed: bool,
    ) -> dict[str, Any]:
        """Atomically prefetch one allowlisted pipeline on the Windows network plane.

        Git for Windows can use the desktop proxy even when a WSL NAT guest cannot.
        The checkout is detached at an exact commit, materialized with LF line endings,
        verified before activation, and never exposes proxy credentials in the plan.
        """
        state = await self._inspect_pipeline_cache(pipeline_id, revision)
        if state.get("ready"):
            return state
        if not network_allowed:
            raise RuntimeError(
                "Offline execution requires a verified, previously cached pipeline revision"
            )
        spec = PIPELINES.get(pipeline_id)
        if spec is None or revision != spec["revision"]:
            raise ValueError("Pipeline revision is not in the administrator allowlist")
        if not shutil.which("git"):
            raise RuntimeError(
                "Git for Windows is required to securely prefetch the fixed pipeline revision"
            )
        asset = self._pipeline_asset(pipeline_id)
        asset.parent.mkdir(parents=True, exist_ok=True)
        staging = asset.parent / f".{asset.name}.staging-{uuid.uuid4().hex}"
        source = spec["source_url"].rstrip("/") + ".git"
        backup: Path | None = None
        try:
            await self._run_git(
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.eol=lf",
                "-c",
                "core.longpaths=true",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                source,
                str(staging),
            )
            await self._run_git("-C", str(staging), "config", "core.autocrlf", "false")
            await self._run_git("-C", str(staging), "config", "core.eol", "lf")
            await self._run_git("-C", str(staging), "config", "core.safecrlf", "true")
            await self._run_git("-C", str(staging), "config", "core.longpaths", "true")
            await self._run_git(
                "-C", str(staging), "checkout", "--detach", spec["commit_sha"]
            )
            staged_state = await self._inspect_pipeline_cache_at(
                staging, pipeline_id, revision
            )
            if not staged_state.get("ready"):
                raise RuntimeError(str(staged_state.get("error") or "Pipeline verification failed"))
            if asset.exists():
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup = asset.parent / f"{asset.name}.invalid-{timestamp}-{uuid.uuid4().hex[:8]}"
                asset.rename(backup)
            try:
                staging.rename(asset)
            except Exception:
                if backup is not None and backup.exists() and not asset.exists():
                    backup.rename(asset)
                raise
            activated = await self._inspect_pipeline_cache(pipeline_id, revision)
            if not activated.get("ready"):
                rejected = asset.parent / (
                    f"{asset.name}.rejected-{uuid.uuid4().hex[:8]}"
                )
                asset.rename(rejected)
                if backup is not None and backup.exists():
                    backup.rename(asset)
                raise RuntimeError(
                    str(activated.get("error") or "Activated pipeline cache failed verification")
                )
            return {**activated, "status": "downloaded_and_verified"}
        finally:
            # Preserve a failed staging tree intact for diagnosis. Successful
            # activation renames it to the final asset path, so nothing remains.
            # A later successful attempt uses a fresh UUID and never overwrites it.
            pass

    async def _inspect_pipeline_cache_at(
        self, asset: Path, pipeline_id: str, revision: str
    ) -> dict[str, Any]:
        """Verify a staging checkout by temporarily applying the normal cache checks."""
        expected = self._pipeline_asset(pipeline_id)
        if asset.resolve() == expected:
            return await self._inspect_pipeline_cache(pipeline_id, revision)
        spec = PIPELINES[pipeline_id]
        try:
            head = (
                await self._run_git("-C", str(asset), "rev-parse", "HEAD", timeout=30)
            ).decode("ascii", errors="strict").strip()
            tag_commit = (
                await self._run_git(
                    "-C",
                    str(asset),
                    "rev-parse",
                    f"refs/tags/{revision}^{{commit}}",
                    timeout=30,
                )
            ).decode("ascii", errors="strict").strip()
            if head != spec["commit_sha"] or tag_commit != spec["commit_sha"]:
                raise RuntimeError("Downloaded pipeline does not match the pinned commit")
            status = await self._run_git(
                "-C", str(asset), "status", "--porcelain=v1", "--untracked-files=all", timeout=60
            )
            if status.strip():
                preview = status.decode("utf-8", errors="replace").strip()[:300]
                raise RuntimeError(
                    "Downloaded pipeline contains unverified changes: " + preview
                )
            await self._verify_worktree_blobs(asset, "Downloaded pipeline")
        except (OSError, RuntimeError, UnicodeError) as exc:
            return {"ready": False, "status": "invalid", "error": str(exc)[:500]}
        return {"ready": True, "status": "verified"}

    async def _verify_worktree_blobs(self, asset: Path, label: str) -> None:
        """Prove every regular worktree file matches the pinned Git object.

        Git reads the files so Windows long paths remain supported. Passing raw
        path bytes through stdin avoids shell parsing and PowerShell encoding.
        """
        index = await self._run_git(
            "-C", str(asset), "ls-files", "-s", "-z", timeout=60
        )
        paths: list[bytes] = []
        expected: list[str] = []
        for entry in index.split(b"\0"):
            if not entry:
                continue
            try:
                metadata, path = entry.split(b"\t", 1)
                mode, sha, stage = metadata.split(b" ")
            except ValueError as exc:
                raise RuntimeError(f"{label} returned an invalid Git index entry") from exc
            if mode not in {b"100644", b"100755"} or stage != b"0":
                raise RuntimeError(f"{label} contains an unsupported Git object mode")
            if not path or b"\n" in path or b"\r" in path or b"\0" in path:
                raise RuntimeError(f"{label} contains an unsafe tracked filename")
            paths.append(path)
            expected.append(sha.decode("ascii", errors="strict"))
        if not paths:
            raise RuntimeError(f"{label} contains no tracked files")
        executable = shutil.which("git")
        if not executable:
            raise RuntimeError("Git for Windows is unavailable during pipeline verification")
        process = await asyncio.create_subprocess_exec(
            executable,
            "-C",
            str(asset),
            "hash-object",
            "--no-filters",
            "--stdin-paths",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(b"\n".join(paths) + b"\n"), timeout=120
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError(f"{label} blob verification timed out") from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"{label} blob verification failed: {detail[-500:]}")
        actual = stdout.decode("ascii", errors="strict").splitlines()
        if len(actual) != len(expected):
            raise RuntimeError(f"{label} blob verification returned an incomplete result")
        mismatches = sum(left != right for left, right in zip(expected, actual, strict=True))
        if mismatches:
            raise RuntimeError(
                f"{label} differs from the pinned commit in {mismatches} tracked file(s)"
            )

    def _command(self, executable: str, *args: str) -> list[str]:
        if self.transport == "wsl2":
            return [
                self.launcher or "wsl.exe",
                "--exec",
                "/usr/bin/env",
                f"NXF_VER={NEXTFLOW_VERSION}",
                executable,
                *args,
            ]
        located = self.executable if executable == "nextflow" else shutil.which(executable)
        return [located or executable, *args]

    async def _probe_wsl_work_storage(self) -> dict[str, Any]:
        """Prove that the private Linux work filesystem is writable and FIFO-capable."""
        script = (
            "set -eu; "
            "home_real=$(realpath -e \"$HOME\"); "
            "probe=$(mktemp -d \"$home_real/.research-agent-preflight.XXXXXX\"); "
            "trap 'rm -f \"$probe/fifo\"; rmdir \"$probe\"' EXIT; "
            "probe_real=$(realpath -e \"$probe\"); "
            "case \"$probe_real\" in \"$home_real\"/*) ;; *) exit 73 ;; esac; "
            "mkfifo \"$probe/fifo\"; "
            "fs_type=$(stat -f -c %T \"$probe\"); "
            "free_kib=$(df -Pk \"$probe\" | awk 'NR==2 {print $4}'); "
            "printf '%s\\t%s\\n' \"$fs_type\" \"$free_kib\""
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command("bash", "-lc", script),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "NXF_VER": NEXTFLOW_VERSION},
            )
            output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            text = output.decode("utf-8", errors="replace").strip()
            fields = text.rsplit("\t", 1)
            free_bytes = int(fields[1]) * 1024 if len(fields) == 2 else 0
            return {
                "ready": process.returncode == 0 and free_bytes > 0,
                "filesystem": fields[0][:80] if fields else "",
                "free_bytes": free_bytes,
                "fifo_supported": process.returncode == 0,
                **({"error": text[:300]} if process.returncode != 0 else {}),
            }
        except (OSError, ValueError, asyncio.TimeoutError) as exc:
            return {
                "ready": False,
                "filesystem": "",
                "free_bytes": 0,
                "fifo_supported": False,
                "error": str(exc)[:300],
            }

    async def capabilities(self, *, deep: bool = False) -> dict[str, Any]:
        executable = (
            self.executable
            if self.transport == "wsl2"
            else (self.executable or shutil.which("nextflow"))
        )
        transport_available = bool(self.launcher) if self.transport == "wsl2" else bool(executable)
        response: dict[str, Any] = {
            "backend": self.backend_id,
            "available": bool(executable) if self.transport == "native" else False,
            "transport": self.transport,
            "transport_available": transport_available,
            "probe_required": self.transport == "wsl2" and not deep,
            "executable": Path(executable).name if executable else None,
            "profiles": {profile: bool(shutil.which(tool)) for profile, tool in PROFILES.items()}
            if self.transport == "native"
            else dict.fromkeys(PROFILES, False),
            "pipelines": pipeline_catalog(),
            "deep_probe": deep,
        }
        if deep and executable and transport_available:
            try:
                process = await asyncio.create_subprocess_exec(
                    *self._command("nextflow", "-version"),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env={**os.environ, "NXF_VER": NEXTFLOW_VERSION},
                )
                # A WSL JVM cold start can legitimately exceed a few seconds,
                # especially immediately after the distribution starts.
                output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
                text = output.decode("utf-8", errors="replace")
                match = _VERSION.search(text)
                response.update(
                    {
                        "probe_ok": process.returncode == 0,
                        "available": process.returncode == 0 and bool(match),
                        "version": match.group(1) if match else "",
                        "version_output": text.strip()[:500],
                    }
                )
                if match:
                    detected = Version(match.group(1))
                    response["pipeline_compatibility"] = {
                        pipeline_id: detected >= Version(spec["minimum_nextflow"])
                        for pipeline_id, spec in PIPELINES.items()
                    }
            except (OSError, asyncio.TimeoutError) as exc:
                response.update({"probe_ok": False, "probe_error": str(exc)[:500]})
        if deep:

            async def probe_profile(profile: str, tool: str) -> tuple[str, dict[str, Any]]:
                located = tool if self.transport == "wsl2" else shutil.which(tool)
                if not located or (self.transport == "wsl2" and not self.launcher):
                    return profile, {"ready": False, "error": f"{tool} is unavailable"}
                try:
                    process = await asyncio.create_subprocess_exec(
                        *self._command(tool, *_PROFILE_PROBE_ARGS[profile]),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        env={**os.environ, "NXF_VER": NEXTFLOW_VERSION},
                    )
                    output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
                    result = {
                        "ready": process.returncode == 0,
                        "output": output.decode("utf-8", errors="replace").strip()[:300],
                    }
                    return profile, result
                except (OSError, asyncio.TimeoutError) as exc:
                    return profile, {"ready": False, "error": str(exc)[:300]}

            probe_results = await asyncio.gather(
                *(probe_profile(profile, tool) for profile, tool in PROFILES.items())
            )
            profile_probes = dict(probe_results)
            for profile, result in probe_results:
                response["profiles"][profile] = bool(result.get("ready"))
            response["profile_probes"] = profile_probes
            if self.transport == "wsl2" and self.launcher:
                response["work_storage_probe"] = await self._probe_wsl_work_storage()
        return response

    async def preflight(
        self,
        *,
        pipeline_id: str,
        revision: str,
        profile: str,
        network_allowed: bool,
    ) -> dict[str, Any]:
        spec = PIPELINES.get(pipeline_id)
        issues: list[str] = []
        warnings: list[str] = []
        if spec is None:
            issues.append("Pipeline is not in the administrator allowlist")
        elif revision != spec["revision"]:
            issues.append(f"Only the pinned revision {spec['revision']} is allowed")
        if profile not in PROFILES:
            issues.append("Unsupported Nextflow execution profile")
        capabilities = await self.capabilities(deep=True)
        if not capabilities.get("available"):
            issues.append(
                "Nextflow is unavailable in WSL2"
                if self.transport == "wsl2"
                else "Nextflow is not installed or not available on PATH"
            )
        elif not capabilities.get("probe_ok"):
            issues.append("Nextflow version probe failed")
        elif spec:
            version = capabilities.get("version") or ""
            try:
                if Version(version) < Version(spec["minimum_nextflow"]):
                    issues.append(
                        f"Nextflow {version} is below the required {spec['minimum_nextflow']}"
                    )
            except InvalidVersion:
                issues.append("Nextflow returned an unrecognized version")
        if profile in PROFILES:
            profile_probe = capabilities.get("profile_probes", {}).get(profile, {})
            if not profile_probe.get("ready"):
                issue = profile_probe.get("error") or profile_probe.get("output") or "probe failed"
                issues.append(f"Execution profile {profile} is not ready: {issue}")
        wsl_work_free_bytes = None
        if self.transport == "wsl2":
            storage_probe = capabilities.get("work_storage_probe", {})
            if not storage_probe.get("ready") or not storage_probe.get("fifo_supported"):
                issue = storage_probe.get("error") or "private WSL work storage probe failed"
                issues.append(f"WSL work storage is not ready: {issue}")
            else:
                wsl_work_free_bytes = int(storage_probe.get("free_bytes") or 0)
                if wsl_work_free_bytes < 5 * 1024**3:
                    issues.append("The private WSL work filesystem has less than 5 GiB free")
                elif wsl_work_free_bytes < 50 * 1024**3:
                    warnings.append("The private WSL work filesystem has less than 50 GiB free")
        free_bytes = shutil.disk_usage(self.root).free
        if free_bytes < 5 * 1024**3:
            issues.append("The managed pipeline workspace has less than 5 GiB free")
        elif free_bytes < 50 * 1024**3:
            warnings.append("The managed pipeline workspace has less than 50 GiB free")
        cache_state = None
        if spec:
            cache_state = await self._inspect_pipeline_cache(pipeline_id, revision)
            if not cache_state.get("ready"):
                if not network_allowed:
                    issues.append(
                        "Offline execution requires a verified, previously cached pipeline revision"
                    )
                elif not shutil.which("git"):
                    issues.append(
                        "Git for Windows is required to securely prefetch the fixed pipeline revision"
                    )
                else:
                    warnings.append(
                        "The fixed pipeline revision will be downloaded and verified before execution"
                    )
            elif not network_allowed:
                warnings.append(
                    "Container and reference caches cannot be proven complete before execution"
                )
        return {
            "ready": not issues,
            "issues": issues,
            "warnings": warnings,
            "backend": self.backend_id,
            "pipeline": pipeline_id,
            "revision": revision,
            "profile": profile,
            "network_allowed": network_allowed,
            "capabilities": capabilities,
            "workspace_free_bytes": free_bytes,
            "wsl_work_free_bytes": wsl_work_free_bytes,
            "pipeline_cache": cache_state,
        }

    def resolve_artifact(self, user_id: int, run_id: str, relative_path: str) -> Path:
        root = self._run_root(user_id, run_id)
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ValueError("Pipeline artifact is unavailable")
        return candidate

    def _run_root(self, user_id: int, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9-]{36}", run_id):
            raise ValueError("Invalid pipeline run identifier")
        path = (self.root / f"user-{user_id}" / f"run-{run_id}").resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Pipeline workspace escaped the managed root")
        return path

    async def build_plan(
        self,
        *,
        run_id: str,
        user_id: int,
        pipeline_id: str,
        revision: str,
        profile: str,
        parameters: dict[str, Any],
        artifact_paths: dict[str, Path],
        resume: bool,
        network_allowed: bool,
        timeout_seconds: int,
    ) -> ExecutionPlan:
        normalized = validate_request(
            pipeline_id,
            revision,
            profile,
            parameters,
            dict.fromkeys(artifact_paths, "bound"),
        )
        executable = self.executable or shutil.which("nextflow") or "nextflow"
        test_profile = normalized.pop("test_profile", False)
        max_cpus = normalized.pop("max_cpus")
        max_memory = normalized.pop("max_memory")
        if test_profile and not network_allowed:
            raise ValueError("The official nf-core test profile requires network access")

        root = self._run_root(user_id, run_id)
        output = root / "results"
        work = root / "work"
        reports = root / "reports"
        for directory in (root, output, reports):
            directory.mkdir(parents=True, exist_ok=True)
        if self.transport == "native":
            work.mkdir(parents=True, exist_ok=True)
        report_paths = {
            "report": reports / "report.html",
            "timeline": reports / "timeline.html",
            "trace": reports / "trace.tsv",
            "dag": reports / "dag.html",
            "nextflow_log": root / "nextflow.log",
            "stdout": reports / "stdout.log",
            "stderr": reports / "stderr.log",
        }
        test_data_provenance = None
        test_samplesheet = None
        test_bbsplit_list = None
        if test_profile:
            test_samplesheet = root / "test-profile-samplesheet.csv"
            test_bbsplit_list = root / "test-profile-bbsplit.csv"
            _write_rnaseq_test_samplesheet(test_samplesheet)
            _write_rnaseq_test_bbsplit_list(test_bbsplit_list)
            test_data_provenance = {
                "repository": "nf-core/test-datasets",
                "transport": "jsdelivr-github-commit",
                "general_revision": _RNASEQ_TEST_GENERAL_REVISION,
                "reads_revision": _RNASEQ_TEST_READS_REVISION,
                "kraken_revision": _RNASEQ_TEST_KRAKEN_REVISION,
                "samplesheet_sha256": _sha256(test_samplesheet),
                "bbsplit_list_sha256": _sha256(test_bbsplit_list),
            }
        resource_config = root / "resource-limits.config"
        memory_number, memory_unit = max_memory.split()
        managed_config = (
            "executor {\n"
            "    queueSize = 1\n"
            "    $local {\n"
            f"        cpus = {max_cpus}\n"
            f"        memory = {memory_number}.{memory_unit}\n"
            "    }\n"
            "}\n\n"
            "process {\n"
            "    resourceLimits = [\n"
            f"        cpus: {max_cpus},\n"
            f"        memory: {memory_number}.{memory_unit}\n"
            "    ]\n"
            "}\n"
        )
        if test_samplesheet is not None and test_bbsplit_list is not None:
            general = f"{_TEST_DATA_CDN}{_RNASEQ_TEST_GENERAL_REVISION}"
            kraken = f"{_TEST_DATA_CDN}{_RNASEQ_TEST_KRAKEN_REVISION}"
            input_path = (
                to_wsl_path(test_samplesheet) if self.transport == "wsl2" else str(test_samplesheet)
            )
            bbsplit_path = (
                to_wsl_path(test_bbsplit_list)
                if self.transport == "wsl2"
                else str(test_bbsplit_list)
            )
            test_values = {
                "input": input_path,
                "fasta": f"{general}/reference/genome.fasta",
                "gtf": f"{general}/reference/genes_with_empty_tid.gtf.gz",
                "gff": f"{general}/reference/genes.gff.gz",
                "transcript_fasta": f"{general}/reference/transcriptome.fasta",
                "additional_fasta": f"{general}/reference/gfp.fa.gz",
                "bbsplit_fasta_list": bbsplit_path,
                "hisat2_index": f"{general}/reference/hisat2.tar.gz",
                "salmon_index": f"{general}/reference/salmon.tar.gz",
                "kraken_db": (f"{kraken}/data/genomics/sarscov2/genome/db/kraken2.tar.gz"),
            }
            managed_config += "\nparams {\n"
            managed_config += "".join(
                f"    {name} = {_groovy_string(value)}\n" for name, value in test_values.items()
            )
            managed_config += "}\n"
        resource_config.write_text(
            managed_config,
            encoding="utf-8",
            newline="\n",
        )
        config_argument = (
            to_wsl_path(resource_config) if self.transport == "wsl2" else str(resource_config)
        )
        inner_argv = [
            executable,
            "-c",
            config_argument,
            "-log",
            to_wsl_path(report_paths["nextflow_log"])
            if self.transport == "wsl2"
            else str(report_paths["nextflow_log"]),
            "run",
            pipeline_id,
            "-r",
            revision,
            "-profile",
            f"test,{profile}" if test_profile else profile,
            "-work-dir",
            _WSL_WORK_TOKEN if self.transport == "wsl2" else str(work),
            "-with-report",
            to_wsl_path(report_paths["report"])
            if self.transport == "wsl2"
            else str(report_paths["report"]),
            "-with-timeline",
            to_wsl_path(report_paths["timeline"])
            if self.transport == "wsl2"
            else str(report_paths["timeline"]),
            "-with-trace",
            to_wsl_path(report_paths["trace"])
            if self.transport == "wsl2"
            else str(report_paths["trace"]),
            "-with-dag",
            to_wsl_path(report_paths["dag"])
            if self.transport == "wsl2"
            else str(report_paths["dag"]),
            "--outdir",
            to_wsl_path(output) if self.transport == "wsl2" else str(output),
        ]
        if resume:
            inner_argv.append("-resume")
        for name in sorted(artifact_paths):
            path = artifact_paths[name].resolve()
            if not path.is_file():
                raise ValueError(f"Bound artifact is unavailable: {name}")
            allowed = PIPELINES[pipeline_id]["artifact_parameters"][name]["suffixes"]
            if path.suffix.lower() not in allowed:
                raise ValueError(
                    f"Artifact {name} must use one of these suffixes: {', '.join(allowed)}"
                )
            inner_argv.extend(
                [
                    f"--{name}",
                    to_wsl_path(path) if self.transport == "wsl2" else str(path),
                ]
            )
        if not test_profile:
            validate_samplesheet(pipeline_id, artifact_paths["input"])
        for name in sorted(normalized):
            value = normalized[name]
            if PIPELINES[pipeline_id]["parameters"][name].get("control"):
                continue
            if isinstance(value, bool):
                if value:
                    inner_argv.append(f"--{name}")
            else:
                inner_argv.extend([f"--{name}", str(value)])

        environment = {
            "NXF_HOME": to_wsl_path((self.root / "nextflow-home").resolve())
            if self.transport == "wsl2"
            else str((self.root / "nextflow-home").resolve()),
            "NXF_VER": NEXTFLOW_VERSION,
            "NXF_ANSI_LOG": "false",
            "NXF_OFFLINE": "false" if network_allowed else "true",
        }
        control_paths: dict[str, Path] = {"resource_config": resource_config}
        if test_samplesheet is not None:
            control_paths["test_samplesheet"] = test_samplesheet
        if test_bbsplit_list is not None:
            control_paths["test_bbsplit_list"] = test_bbsplit_list
        if self.transport == "wsl2":
            runner = root / "wsl-runner.sh"
            runner.write_text(_WSL_RUNNER, encoding="utf-8", newline="\n")
            pid_file = root / "wsl-runner.pid"
            runtime_work_path = root / "wsl-work-dir.txt"
            control_paths.update(
                {"runner": runner, "pid": pid_file, "runtime_work_path": runtime_work_path}
            )
            argv = [
                self.launcher or "wsl.exe",
                "--cd",
                to_wsl_path(root),
                "--exec",
                "/bin/bash",
                to_wsl_path(runner),
                to_wsl_path(pid_file),
                to_wsl_path(runtime_work_path),
                f"user-{user_id}/run-{run_id}",
                "--",
                "env",
                *[f"{key}={value}" for key, value in environment.items()],
                *inner_argv,
            ]
            process_environment: dict[str, str] = {}
        else:
            argv = inner_argv
            process_environment = environment

        display = []
        replacements = {
            str(root): "<managed-run-dir>",
            str(self.root): "<managed-pipeline-root>",
            **{str(path.resolve()): f"<artifact:{name}>" for name, path in artifact_paths.items()},
        }
        if self.transport == "wsl2":
            replacements.update(
                {
                    _WSL_WORK_TOKEN: "<wsl-private-work-dir>",
                    to_wsl_path(root): "<managed-run-dir>",
                    to_wsl_path(self.root): "<managed-pipeline-root>",
                    **{
                        to_wsl_path(path): f"<artifact:{name}>"
                        for name, path in artifact_paths.items()
                    },
                }
            )
        for item in argv:
            shown = "nextflow" if item == executable else item
            for physical, label in replacements.items():
                shown = shown.replace(physical, label)
            display.append(shown)
        return ExecutionPlan(
            backend=self.backend_id,
            run_id=run_id,
            argv=argv,
            display_argv=display,
            cwd=root,
            environment=process_environment,
            work_dir=work,
            output_dir=output,
            report_paths=report_paths,
            timeout_seconds=timeout_seconds,
            control_paths=control_paths,
            provenance={
                "pipeline": pipeline_id,
                "revision": revision,
                "profile": profile,
                "validation_profile": "test" if test_profile else None,
                "minimum_nextflow": PIPELINES[pipeline_id]["minimum_nextflow"],
                "nextflow_version": NEXTFLOW_VERSION,
                "source_url": PIPELINES[pipeline_id]["source_url"],
                "network_allowed": network_allowed,
                "resume": resume,
                "transport": self.transport,
                "work_storage": (
                    {
                        "filesystem": "wsl-ext4",
                        "location": "private per-user application data",
                    }
                    if self.transport == "wsl2"
                    else {"filesystem": "native", "location": "managed run directory"}
                ),
                "resource_limits": {
                    "max_cpus": max_cpus,
                    "max_memory": max_memory,
                    "executor_queue_size": 1,
                    "scope": "single-slot-local-executor-pool-and-per-task-cap",
                },
                "test_data": test_data_provenance,
            },
        )

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        archived_attempt = None
        if plan.provenance.get("resume"):
            archived_attempt = self._archive_previous_attempt(plan)
            if archived_attempt is not None:
                plan.provenance["archived_attempt"] = archived_attempt
        env = os.environ.copy()
        env.update(plan.environment)
        stdout_path = plan.report_paths["stdout"]
        stderr_path = plan.report_paths["stderr"]
        started = datetime.now(timezone.utc).isoformat()
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = None
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = await asyncio.create_subprocess_exec(
                    *plan.argv,
                    cwd=str(plan.cwd),
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    **kwargs,
                )
                try:
                    exit_code = await asyncio.wait_for(process.wait(), timeout=plan.timeout_seconds)
                except asyncio.TimeoutError:
                    await self._terminate(process, plan)
                    return ExecutionResult(
                        run_id=plan.run_id,
                        status="failed",
                        exit_code=124,
                        stdout_tail=_redact_output(_tail(stdout_path), plan),
                        stderr_tail=_redact_output(_tail(stderr_path), plan),
                        provenance={
                            **plan.provenance,
                            "backend": self.backend_id,
                            "started_at": started,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                            "argv": plan.display_argv,
                        },
                        error=f"Execution exceeded the {plan.timeout_seconds}-second limit",
                    )
        except asyncio.CancelledError:
            if process and process.returncode is None:
                await self._terminate(process, plan)
            raise
        except OSError as exc:
            return ExecutionResult(
                run_id=plan.run_id,
                status="failed",
                exit_code=127,
                error=str(exc),
                provenance={**plan.provenance, "started_at": started},
            )

        artifacts = []
        for kind, path in plan.report_paths.items():
            if path.is_file():
                artifacts.append(_artifact(path, plan.cwd, kind))
        if archived_attempt is not None:
            manifest_path = plan.cwd / archived_attempt["manifest"]
            if manifest_path.is_file():
                artifacts.append(_artifact(manifest_path, plan.cwd, "attempt_manifest"))
        summary = parse_trace(plan.report_paths["trace"])
        outputs, output_manifest = collect_output_artifacts(plan.output_dir, plan.cwd)
        artifacts.extend(outputs)
        summary["output_manifest"] = output_manifest
        status = "completed" if exit_code == 0 else "failed"
        return ExecutionResult(
            run_id=plan.run_id,
            status=status,
            exit_code=exit_code,
            stdout_tail=_redact_output(_tail(stdout_path), plan),
            stderr_tail=_redact_output(_tail(stderr_path), plan),
            artifacts=artifacts,
            task_summary=summary,
            provenance={
                **plan.provenance,
                "backend": self.backend_id,
                "started_at": started,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "argv": plan.display_argv,
            },
            error="" if exit_code == 0 else "Nextflow exited with a non-zero status",
        )

    def _archive_previous_attempt(self, plan: ExecutionPlan) -> dict[str, Any] | None:
        """Move prior reports aside so Nextflow can safely regenerate them on resume."""
        existing: list[tuple[str, Path]] = []
        root = plan.cwd.resolve()
        for kind, path in plan.report_paths.items():
            if not path.exists() and not path.is_symlink():
                continue
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"Unsafe prior report path prevents resume: {kind}")
            if not path.resolve().is_relative_to(root):
                raise RuntimeError(f"Prior report path escapes the managed run: {kind}")
            existing.append((kind, path))
        if not existing:
            return None

        attempts = plan.cwd / "attempts"
        attempts.mkdir(parents=True, exist_ok=True)
        attempt_numbers = []
        for candidate in attempts.glob("attempt-*"):
            match = re.fullmatch(r"attempt-([0-9]+)", candidate.name)
            if match:
                attempt_numbers.append(int(match.group(1)))
        archive = attempts / f"attempt-{max(attempt_numbers, default=0) + 1:03d}"
        archive.mkdir()

        moved = []
        for kind, path in existing:
            relative_path = path.relative_to(plan.cwd)
            destination = archive / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.replace(destination)
            moved.append(
                {
                    "kind": kind,
                    "from": relative_path.as_posix(),
                    "archived_as": destination.relative_to(plan.cwd).as_posix(),
                    "size_bytes": destination.stat().st_size,
                    "sha256": _sha256(destination),
                }
            )

        manifest = archive / "attempt.json"
        manifest.write_text(
            json.dumps(
                {
                    "reason": "resume",
                    "archived_at": datetime.now(timezone.utc).isoformat(),
                    "files": moved,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "directory": archive.relative_to(plan.cwd).as_posix(),
            "manifest": manifest.relative_to(plan.cwd).as_posix(),
            "files": len(moved),
        }

    async def _terminate(
        self, process: asyncio.subprocess.Process, plan: ExecutionPlan | None = None
    ) -> None:
        try:
            if self.transport == "wsl2" and plan is not None:
                pid_path = plan.control_paths.get("pid")
                pid_text = (
                    pid_path.read_text(encoding="ascii").strip()
                    if pid_path and pid_path.is_file()
                    else ""
                )
                if re.fullmatch(r"[1-9][0-9]{0,9}", pid_text):
                    for signal_name in ("-TERM", "-KILL"):
                        killer = await asyncio.create_subprocess_exec(
                            self.launcher or "wsl.exe",
                            "--exec",
                            "/bin/kill",
                            signal_name,
                            "--",
                            f"-{pid_text}",
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await asyncio.wait_for(killer.wait(), timeout=10)
                        if signal_name == "-TERM":
                            try:
                                await asyncio.wait_for(process.wait(), timeout=8)
                                break
                            except asyncio.TimeoutError:
                                continue
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            elif os.name == "nt":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=10)
            else:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=8)
                except asyncio.TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
            if process.returncode is None:
                await process.wait()
        except (OSError, ProcessLookupError, asyncio.TimeoutError):
            if process.returncode is None:
                process.kill()
                await process.wait()


__all__ = [
    "NextflowBackend",
    "PIPELINES",
    "PROFILES",
    "collect_output_artifacts",
    "parse_trace",
    "pipeline_catalog",
    "to_wsl_path",
    "validate_samplesheet",
    "validate_request",
]
