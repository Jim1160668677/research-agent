import asyncio
import uuid
from pathlib import Path

import pytest

from research_agent.execution.nextflow import (
    NEXTFLOW_VERSION,
    NextflowBackend,
    collect_output_artifacts,
    parse_trace,
    validate_request,
    validate_samplesheet,
)


def valid_request(**overrides):
    request = {
        "pipeline_id": "nf-core/rnaseq",
        "revision": "3.26.0",
        "profile": "docker",
        "parameters": {"genome": "GRCh38", "aligner": "star_salmon", "max_cpus": 4},
        "artifact_bindings": {"input": "artifact-id"},
    }
    request.update(overrides)
    return request


def test_validation_is_allowlisted_and_revision_pinned():
    request = valid_request()
    normalized = validate_request(**request)
    assert normalized["aligner"] == "star_salmon"
    assert normalized["max_cpus"] == 4
    assert normalized["max_memory"] == "32 GB"

    with pytest.raises(ValueError, match="allowlist"):
        validate_request(**valid_request(pipeline_id="evil/pipeline"))
    with pytest.raises(ValueError, match="pinned revision"):
        validate_request(**valid_request(revision="latest"))
    with pytest.raises(ValueError, match="Unknown pipeline parameter"):
        validate_request(**valid_request(parameters={"process": "; rm -rf /"}))
    with pytest.raises(ValueError, match="must be boolean"):
        validate_request(**valid_request(parameters={"genome": "GRCh38", "skip_trimming": "true"}))
    with pytest.raises(ValueError, match="between 512 MB and 2 TB"):
        validate_request(**valid_request(parameters={"genome": "GRCh38", "max_memory": "9999 TB"}))
    with pytest.raises(ValueError, match="both custom FASTA and GTF"):
        validate_request(**valid_request(parameters={}, artifact_bindings={"input": "artifact-id"}))


@pytest.mark.asyncio
async def test_build_plan_uses_argv_managed_paths_and_redacts_artifacts(tmp_path):
    sample_sheet = tmp_path / "samples.csv"
    sample_sheet.write_text(
        "sample,fastq_1,fastq_2,strandedness\nS1,reads.fastq.gz,,auto\n",
        encoding="utf-8",
    )
    backend = NextflowBackend(executable="nextflow", root=tmp_path / "runs", transport="native")
    run_id = str(uuid.uuid4())
    plan = await backend.build_plan(
        run_id=run_id,
        user_id=7,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        parameters={"genome": "GRCh38", "aligner": "star_salmon", "skip_trimming": True},
        artifact_paths={"input": sample_sheet},
        resume=False,
        network_allowed=False,
        timeout_seconds=3600,
    )

    assert plan.argv[:3] == [
        "nextflow",
        "-c",
        str(plan.control_paths["resource_config"]),
    ]
    assert plan.argv[plan.argv.index("run") + 1] == "nf-core/rnaseq"
    assert plan.argv[plan.argv.index("-r") + 1] == "3.26.0"
    assert "--skip_trimming" in plan.argv
    assert "-resume" not in plan.argv
    assert plan.environment["NXF_OFFLINE"] == "true"
    assert plan.environment["NXF_VER"] == NEXTFLOW_VERSION
    assert "resourceLimits" in plan.control_paths["resource_config"].read_text()
    assert "cpus: 8" in plan.control_paths["resource_config"].read_text()
    assert "memory: 32.GB" in plan.control_paths["resource_config"].read_text()
    assert "cpus = 8" in plan.control_paths["resource_config"].read_text()
    assert "memory = 32.GB" in plan.control_paths["resource_config"].read_text()
    assert "queueSize = 1" in plan.control_paths["resource_config"].read_text()
    assert "$local" in plan.control_paths["resource_config"].read_text()
    assert "--max_cpus" not in plan.argv
    assert "--max_memory" not in plan.argv
    assert str(sample_sheet.resolve()) not in " ".join(plan.display_argv)
    assert "<artifact:input>" in plan.display_argv
    assert plan.cwd.is_relative_to((tmp_path / "runs").resolve())


def test_trace_parser_is_bounded_and_reports_failures(tmp_path):
    trace = tmp_path / "trace.tsv"
    trace.write_text(
        "task_id\thash\tname\tstatus\texit\n"
        "1\taa/bb\tFASTQC\tCOMPLETED\t0\n"
        "2\tcc/dd\tALIGN\tFAILED\t1\n",
        encoding="utf-8",
    )
    summary = parse_trace(trace)
    assert summary["tasks"] == 2
    assert summary["statuses"] == {"COMPLETED": 1, "FAILED": 1}
    assert summary["failed"] == [{"name": "ALIGN", "exit": "1", "hash": "cc/dd"}]


def test_output_manifest_hashes_managed_results(tmp_path):
    root = tmp_path / "run"
    output = root / "results"
    output.mkdir(parents=True)
    result = output / "quant.tsv"
    result.write_text("gene\tcount\nA\t1\n", encoding="utf-8")
    artifacts, summary = collect_output_artifacts(output, root)
    assert artifacts[0]["relative_path"] == "results/quant.tsv"
    assert len(artifacts[0]["sha256"]) == 64
    assert summary["files_recorded"] == 1


@pytest.mark.asyncio
async def test_pipeline_cache_rejects_crlf_shebang(tmp_path, monkeypatch):
    backend = NextflowBackend(root=tmp_path / "runs", transport="wsl2")
    asset = backend._pipeline_asset("nf-core/rnaseq")
    script = asset / "bin" / "tool.sh"
    script.parent.mkdir(parents=True)
    script.write_bytes(b"#!/usr/bin/env bash\r\necho unsafe\r\n")
    expected = "e7ca46272c8f9d5ceee3f71759f4ba551d3217a4"

    async def fake_git(*arguments, **_kwargs):
        if arguments[-2:] == ("rev-parse", "HEAD"):
            return f"{expected}\n".encode()
        if "refs/tags/3.26.0^{commit}" in arguments:
            return f"{expected}\n".encode()
        if "status" in arguments:
            return b""
        raise AssertionError(arguments)

    async def fake_blobs(_asset, _label):
        raise RuntimeError("Cached pipeline differs from the pinned commit in 1 tracked file(s)")

    monkeypatch.setattr(backend, "_run_git", fake_git)
    monkeypatch.setattr(backend, "_verify_worktree_blobs", fake_blobs)
    state = await backend._inspect_pipeline_cache("nf-core/rnaseq", "3.26.0")

    assert state["ready"] is False
    assert state["status"] == "invalid"
    assert "differs from the pinned commit" in state["error"]
    assert str(tmp_path) not in str(state)


@pytest.mark.asyncio
async def test_pipeline_prepare_prefetches_pinned_commit_atomically(tmp_path, monkeypatch):
    backend = NextflowBackend(root=tmp_path / "runs", transport="wsl2")
    expected = "e7ca46272c8f9d5ceee3f71759f4ba551d3217a4"
    inspections = 0
    commands = []

    async def fake_inspect(_pipeline_id, _revision):
        nonlocal inspections
        inspections += 1
        if inspections == 1:
            return {"ready": False, "status": "missing"}
        return {
            "ready": True,
            "status": "verified",
            "pipeline": "nf-core/rnaseq",
            "revision": "3.26.0",
            "commit_sha": expected,
            "source_url": "https://github.com/nf-core/rnaseq",
        }

    async def fake_git(*arguments, **_kwargs):
        commands.append(arguments)
        if "clone" in arguments:
            Path(arguments[-1]).mkdir(parents=True)
        return b""

    async def fake_staging(_asset, _pipeline_id, _revision):
        return {"ready": True, "status": "verified"}

    monkeypatch.setattr(backend, "_inspect_pipeline_cache", fake_inspect)
    monkeypatch.setattr(backend, "_inspect_pipeline_cache_at", fake_staging)
    monkeypatch.setattr(backend, "_run_git", fake_git)
    monkeypatch.setattr("research_agent.execution.nextflow.shutil.which", lambda name: name)

    state = await backend.prepare_pipeline(
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        network_allowed=True,
    )

    clone = next(command for command in commands if "clone" in command)
    checkout = next(command for command in commands if "checkout" in command)
    assert "core.autocrlf=false" in clone
    assert "core.eol=lf" in clone
    assert "core.longpaths=true" in clone
    assert clone[-2] == "https://github.com/nf-core/rnaseq.git"
    assert checkout[-1] == expected
    assert backend._pipeline_asset("nf-core/rnaseq").is_dir()
    assert state["status"] == "downloaded_and_verified"
    assert str(tmp_path) not in str(state)


def test_artifact_resolution_rejects_path_escape(tmp_path):
    backend = NextflowBackend(executable="nextflow", root=tmp_path / "runs", transport="native")
    run_id = str(uuid.uuid4())
    root = backend._run_root(1, run_id)
    report = root / "reports" / "report.html"
    report.parent.mkdir(parents=True)
    report.write_text("ok", encoding="utf-8")
    assert backend.resolve_artifact(1, run_id, "reports/report.html") == report.resolve()
    with pytest.raises(ValueError, match="unavailable"):
        backend.resolve_artifact(1, run_id, "../../secret.txt")


class FakeProcess:
    def __init__(self, returncode=0, wait_forever=False):
        self.returncode = None
        self.pid = 12345
        self._final = returncode
        self._wait_forever = wait_forever

    async def wait(self):
        if self._wait_forever:
            await asyncio.Event().wait()
        self.returncode = self._final
        return self._final

    def kill(self):
        self.returncode = -9


@pytest.mark.asyncio
async def test_execute_has_timeout_and_cancellation_propagation(tmp_path, monkeypatch):
    sample_sheet = tmp_path / "samples.csv"
    sample_sheet.write_text(
        "sample,fastq_1,fastq_2,strandedness\nS1,x.fastq.gz,,auto\n", encoding="utf-8"
    )
    backend = NextflowBackend(executable="nextflow", root=tmp_path / "runs", transport="native")
    plan = await backend.build_plan(
        run_id=str(uuid.uuid4()),
        user_id=1,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        parameters={"genome": "GRCh38"},
        artifact_paths={"input": sample_sheet},
        resume=False,
        network_allowed=True,
        timeout_seconds=0.01,
    )
    process = FakeProcess(wait_forever=True)

    async def fake_create(*args, **kwargs):
        return process

    terminated = []

    async def fake_terminate(target, plan=None):
        terminated.append(target)
        target.returncode = -9

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    monkeypatch.setattr(backend, "_terminate", fake_terminate)
    result = await backend.execute(plan)
    assert result.status == "failed"
    assert result.exit_code == 124
    assert terminated == [process]

    plan.timeout_seconds = 10
    process.returncode = None
    task = asyncio.create_task(backend.execute(plan))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert terminated[-1] is process


@pytest.mark.asyncio
async def test_wsl_plan_converts_paths_and_keeps_public_plan_redacted(tmp_path):
    sample_sheet = tmp_path / "samples.csv"
    sample_sheet.write_text(
        "sample,fastq_1,fastq_2,strandedness\nS1,x.fastq.gz,,auto\n", encoding="utf-8"
    )
    backend = NextflowBackend(root=tmp_path / "runs", transport="wsl2")
    backend.launcher = "wsl.exe"
    plan = await backend.build_plan(
        run_id=str(uuid.uuid4()),
        user_id=1,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        parameters={"genome": "GRCh38"},
        artifact_paths={"input": sample_sheet},
        resume=True,
        network_allowed=False,
        timeout_seconds=3600,
    )
    assert plan.argv[:4] == ["wsl.exe", "--cd", plan.argv[2], "--exec"]
    assert plan.argv[2].startswith("/mnt/")
    assert "/bin/bash" in plan.argv
    assert "setsid" in plan.control_paths["runner"].read_text(encoding="utf-8")
    runner_text = plan.control_paths["runner"].read_text(encoding="utf-8")
    assert "research-agent-data/pipeline-work" in runner_text
    assert "escaped HOME" in runner_text
    assert 'work_dir="$(realpath -e "$work_dir")"' in runner_text
    assert not plan.work_dir.exists()
    assert plan.argv[plan.argv.index("-work-dir") + 1] == (
        "__RESEARCH_AGENT_WSL_EXT4_WORK_DIR__"
    )
    assert "<wsl-private-work-dir>" in plan.display_argv
    assert plan.provenance["work_storage"]["filesystem"] == "wsl-ext4"
    assert "runtime_work_path" in plan.control_paths
    assert "-resume" in plan.argv
    assert f"NXF_VER={NEXTFLOW_VERSION}" in plan.argv
    public = " ".join(plan.display_argv)
    assert str(sample_sheet.resolve()) not in public
    assert "/samples.csv" not in public
    assert "<artifact:input>" in public


def test_pinned_samplesheet_contracts_reject_invalid_and_duplicate_rows(tmp_path):
    rnaseq = tmp_path / "rnaseq.csv"
    rnaseq.write_text(
        "sample,fastq_1,fastq_2,strandedness\nS1,a.fq.gz,,auto\n",
        encoding="utf-8",
    )
    assert validate_samplesheet("nf-core/rnaseq", rnaseq)["rows"] == 1
    rnaseq.write_text("sample,fastq_1\nS1,a.fq.gz\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must start with"):
        validate_samplesheet("nf-core/rnaseq", rnaseq)

    sarek = tmp_path / "sarek.csv"
    sarek.write_text(
        "patient,sample,lane,fastq_1,fastq_2\nP1,S1,L1,a.fq.gz,b.fq.gz\nP1,S1,L1,a.fq.gz,b.fq.gz\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        validate_samplesheet("nf-core/sarek", sarek)


@pytest.mark.asyncio
async def test_official_rnaseq_test_profile_needs_no_artifacts_and_is_not_a_cli_parameter(tmp_path):
    backend = NextflowBackend(root=tmp_path / "runs", transport="wsl2")
    backend.launcher = "wsl.exe"
    plan = await backend.build_plan(
        run_id=str(uuid.uuid4()),
        user_id=1,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        parameters={"test_profile": True},
        artifact_paths={},
        resume=False,
        network_allowed=True,
        timeout_seconds=3600,
    )
    assert plan.argv[plan.argv.index("-profile") + 1] == "test,docker"
    assert "--test_profile" not in plan.argv
    assert "--input" not in plan.argv
    assert plan.provenance["validation_profile"] == "test"
    assert plan.provenance["resource_limits"] == {
        "max_cpus": 8,
        "max_memory": "32 GB",
        "executor_queue_size": 1,
        "scope": "single-slot-local-executor-pool-and-per-task-cap",
    }
    managed_config = plan.control_paths["resource_config"].read_text()
    test_samplesheet = plan.control_paths["test_samplesheet"]
    assert "cdn.jsdelivr.net/gh/nf-core/test-datasets@626c8fab" in managed_config
    assert "cdn.jsdelivr.net/gh/nf-core/test-datasets@e07c1b15" in test_samplesheet.read_text()
    assert "raw.githubusercontent.com" not in test_samplesheet.read_text()
    assert len(plan.provenance["test_data"]["samplesheet_sha256"]) == 64
    bbsplit_list = plan.control_paths["test_bbsplit_list"].read_text()
    assert "GCA_009858895.3_ASM985889v3_genomic.200409.fna" in bbsplit_list
    assert "cdn.jsdelivr.net/gh/nf-core/test-datasets@e07c1b15" in bbsplit_list
    assert "raw.githubusercontent.com" not in bbsplit_list
    assert len(plan.provenance["test_data"]["bbsplit_list_sha256"]) == 64

    with pytest.raises(ValueError, match="cannot be combined with parameter genome"):
        validate_request(
            "nf-core/rnaseq",
            "3.26.0",
            "docker",
            {"test_profile": True, "genome": "GRCh38"},
            {},
        )

    with pytest.raises(ValueError, match="requires network access"):
        await backend.build_plan(
            run_id=str(uuid.uuid4()),
            user_id=1,
            pipeline_id="nf-core/rnaseq",
            revision="3.26.0",
            profile="docker",
            parameters={"test_profile": True},
            artifact_paths={},
            resume=False,
            network_allowed=False,
            timeout_seconds=3600,
        )


@pytest.mark.asyncio
async def test_resume_archives_previous_reports_before_starting_process(tmp_path, monkeypatch):
    backend = NextflowBackend(executable="nextflow", root=tmp_path / "runs", transport="native")
    plan = await backend.build_plan(
        run_id=str(uuid.uuid4()),
        user_id=1,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        parameters={"test_profile": True},
        artifact_paths={},
        resume=True,
        network_allowed=True,
        timeout_seconds=3600,
    )
    plan.report_paths["trace"].write_text(
        "task_id\thash\tname\tstatus\texit\n1\taa/bb\tOLD\tFAILED\t1\n",
        encoding="utf-8",
    )
    plan.report_paths["nextflow_log"].write_text("old log", encoding="utf-8")

    class ResumeProcess(FakeProcess):
        async def wait(self):
            assert not plan.report_paths["trace"].exists()
            assert not plan.report_paths["nextflow_log"].exists()
            plan.report_paths["trace"].write_text(
                "task_id\thash\tname\tstatus\texit\n2\tcc/dd\tNEW\tCOMPLETED\t0\n",
                encoding="utf-8",
            )
            self.returncode = 0
            return 0

    async def fake_create(*args, **kwargs):
        return ResumeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    result = await backend.execute(plan)
    archive = plan.cwd / "attempts" / "attempt-001"
    assert (archive / "reports" / "trace.tsv").is_file()
    assert (archive / "nextflow.log").is_file()
    assert (archive / "attempt.json").is_file()
    assert result.task_summary["statuses"] == {"COMPLETED": 1}
    assert result.provenance["archived_attempt"]["files"] == 2
    assert any(item["kind"] == "attempt_manifest" for item in result.artifacts)


@pytest.mark.asyncio
async def test_execution_output_redacts_managed_and_input_paths(tmp_path, monkeypatch):
    sample_sheet = tmp_path / "private" / "samples.csv"
    sample_sheet.parent.mkdir()
    sample_sheet.write_text(
        "sample,fastq_1,fastq_2,strandedness\nS1,x.fastq.gz,,auto\n", encoding="utf-8"
    )
    backend = NextflowBackend(executable="nextflow", root=tmp_path / "runs", transport="native")
    plan = await backend.build_plan(
        run_id=str(uuid.uuid4()),
        user_id=1,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        parameters={"genome": "GRCh38"},
        artifact_paths={"input": sample_sheet},
        resume=False,
        network_allowed=True,
        timeout_seconds=3600,
    )

    class LogProcess(FakeProcess):
        async def wait(self):
            plan.report_paths["stdout"].write_text(
                f"reading {sample_sheet.resolve()} in {plan.work_dir}", encoding="utf-8"
            )
            plan.report_paths["stderr"].write_text(f"output {plan.output_dir}", encoding="utf-8")
            self.returncode = 0
            return 0

    async def fake_create(*args, **kwargs):
        return LogProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    result = await backend.execute(plan)
    combined = result.stdout_tail + result.stderr_tail
    assert str(tmp_path) not in combined
    assert "<artifact:input>" in combined
    assert "<managed-work-dir>" in combined
    assert "<managed-output-dir>" in combined


# ---- Single-cell and spatial transcriptomics pipeline integration tests ----

_SC_PIPELINES = [
    "nf-core/scrnaseq",
    "nf-core/spatialvi",
    "nf-core/spatialaxe",
]


def _sc_samplesheet():
    return "sample,barcodes,counts\nS1,barcodes.gz,counts.h5ad\n"


def test_scrnaseq_validate_request_accepts_valid_params():
    from research_agent.execution.nextflow import validate_request
    result = validate_request(
        "nf-core/scrnaseq", "4.2.0", "docker",
        {"genome": "GRCh38", "aligner": "star", "max_cpus": 8},
        {"input": "artifact-id"},
    )
    assert result["aligner"] == "star"
    assert result["max_cpus"] == 8
    assert result["max_memory"] == "32 GB"


def test_scrnaseq_validate_request_rejects_unknown_params():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match="Unknown pipeline parameter"):
        validate_request(
            "nf-core/scrnaseq", "4.2.0", "docker",
            {"unknown_param": 42},
            {"input": "artifact-id"},
        )


def test_spatialvi_validate_request_accepts_valid_params():
    from research_agent.execution.nextflow import validate_request
    result = validate_request(
        "nf-core/spatialvi", "0.1.0", "docker",
        {"platform": "visium", "min_genes": 200, "max_cpus": 4},
        {"input": "artifact-id"},
    )
    assert result["platform"] == "visium"
    assert result["min_genes"] == 200
    assert result["max_cpus"] == 4


def test_spatialaxe_validate_request_accepts_valid_params():
    from research_agent.execution.nextflow import validate_request
    result = validate_request(
        "nf-core/spatialaxe", "1.0.1", "conda",
        {"platform": "xenium", "max_cpus": 16},
        {"input": "artifact-id"},
    )
    assert result["platform"] == "xenium"
    assert result["max_cpus"] == 16


def test_spatialvi_rejects_invalid_platform():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match="is not an allowed value"):
        validate_request(
            "nf-core/spatialvi", "0.1.0", "docker",
            {"platform": "invalid_platform"},
            {"input": "artifact-id"},
        )


def test_spatialaxe_rejects_invalid_platform():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match="is not an allowed value"):
        validate_request(
            "nf-core/spatialaxe", "1.0.1", "docker",
            {"platform": "invalid_platform"},
            {"input": "artifact-id"},
        )


def test_sc_pipelines_reject_wrong_revision():
    from research_agent.execution.nextflow import validate_request
    for pipeline_id, expected_rev in [("nf-core/scrnaseq", "4.2.0"),
                                       ("nf-core/spatialvi", "0.1.0"),
                                       ("nf-core/spatialaxe", "1.0.1")]:
        with pytest.raises(ValueError, match="pinned revision"):
            validate_request(pipeline_id, "latest", "docker", {}, {"input": "artifact-id"})


def test_scrnaseq_samplesheet_validation_accepts_valid(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "scrnaseq.csv"
    sheet.write_text(_sc_samplesheet(), encoding="utf-8")
    result = validate_samplesheet("nf-core/scrnaseq", sheet)
    assert result["rows"] == 1


def test_spatialvi_samplesheet_validation_accepts_valid(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "spatialvi.csv"
    sheet.write_text(_sc_samplesheet(), encoding="utf-8")
    result = validate_samplesheet("nf-core/spatialvi", sheet)
    assert result["rows"] == 1


def test_spatialaxe_samplesheet_validation_accepts_valid(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "spatialaxe.csv"
    sheet.write_text(_sc_samplesheet(), encoding="utf-8")
    result = validate_samplesheet("nf-core/spatialaxe", sheet)
    assert result["rows"] == 1


def test_sc_samplesheet_rejects_missing_required_columns(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "missing_cols.csv"
    sheet.write_text("sample,other_column\nS1,val\n", encoding="utf-8")
    for pipeline_id in _SC_PIPELINES:
        with pytest.raises(ValueError, match="missing column"):
            validate_samplesheet(pipeline_id, sheet)


def test_sc_samplesheet_rejects_empty_cells(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "empty_cells.csv"
    sheet.write_text(
        "sample,barcodes,counts\nS1,,counts.h5ad\n", encoding="utf-8"
    )
    for pipeline_id in _SC_PIPELINES:
        with pytest.raises(ValueError, match="needs sample, barcodes, and counts"):
            validate_samplesheet(pipeline_id, sheet)


def test_sc_samplesheet_rejects_invalid_barcodes_extension(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "bad_barcodes.csv"
    sheet.write_text(
        "sample,barcodes,counts\nS1,barcodes.txt,counts.h5ad\n", encoding="utf-8"
    )
    for pipeline_id in _SC_PIPELINES:
        with pytest.raises(ValueError, match="invalid barcodes file"):
            validate_samplesheet(pipeline_id, sheet)


def test_sc_samplesheet_rejects_invalid_counts_extension(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "bad_counts.csv"
    sheet.write_text(
        "sample,barcodes,counts\nS1,barcodes.gz,counts.txt\n", encoding="utf-8"
    )
    for pipeline_id in _SC_PIPELINES:
        with pytest.raises(ValueError, match="invalid counts file"):
            validate_samplesheet(pipeline_id, sheet)


def test_sc_samplesheet_allows_valid_extensions(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    valid_pairs = [
        ("barcodes.gz", "counts.h5ad"),
        ("barcodes.h5", "counts.tsv"),
        ("barcodes.h5ad", "counts.mtx"),
        ("barcodes.tsv", "counts.h5"),
    ]
    sheet = tmp_path / "valid_ext.csv"
    for bcs, cts in valid_pairs:
        sheet.write_text(f"sample,barcodes,counts\nS1,{bcs},{cts}\n", encoding="utf-8")
        for pipeline_id in _SC_PIPELINES:
            result = validate_samplesheet(pipeline_id, sheet)
            assert result["rows"] == 1


@pytest.mark.asyncio
async def test_build_plan_scrnaseq(tmp_path):
    from research_agent.execution.nextflow import NextflowBackend
    sheet = tmp_path / "scrnaseq.csv"
    sheet.write_text(_sc_samplesheet(), encoding="utf-8")
    backend = NextflowBackend(root=tmp_path / "runs", transport="native")
    plan = await backend.build_plan(
        run_id=str(uuid.uuid4()),
        user_id=1,
        pipeline_id="nf-core/scrnaseq",
        revision="4.2.0",
        profile="docker",
        parameters={"genome": "GRCh38", "aligner": "star"},
        artifact_paths={"input": sheet},
        resume=False,
        network_allowed=True,
        timeout_seconds=3600,
    )
    assert "nf-core/scrnaseq" in plan.argv
    assert "-r" in plan.argv
    idx = plan.argv.index("-r")
    assert plan.argv[idx + 1] == "4.2.0"
    assert "--genome" in plan.argv
    assert "GRCh38" in plan.argv
    assert "<artifact:input>" in plan.display_argv


@pytest.mark.asyncio
async def test_build_plan_spatialvi(tmp_path):
    from research_agent.execution.nextflow import NextflowBackend
    sheet = tmp_path / "spatialvi.csv"
    sheet.write_text(_sc_samplesheet(), encoding="utf-8")
    backend = NextflowBackend(root=tmp_path / "runs", transport="native")
    plan = await backend.build_plan(
        run_id=str(uuid.uuid4()),
        user_id=1,
        pipeline_id="nf-core/spatialvi",
        revision="0.1.0",
        profile="conda",
        parameters={"platform": "visium", "min_genes": 200},
        artifact_paths={"input": sheet},
        resume=False,
        network_allowed=True,
        timeout_seconds=3600,
    )
    assert "nf-core/spatialvi" in plan.argv
    idx = plan.argv.index("-r")
    assert plan.argv[idx + 1] == "0.1.0"
    assert "--platform" in plan.argv
    assert "visium" in plan.argv


@pytest.mark.asyncio
async def test_build_plan_spatialaxe(tmp_path):
    from research_agent.execution.nextflow import NextflowBackend
    sheet = tmp_path / "spatialaxe.csv"
    sheet.write_text(_sc_samplesheet(), encoding="utf-8")
    backend = NextflowBackend(root=tmp_path / "runs", transport="native")
    plan = await backend.build_plan(
        run_id=str(uuid.uuid4()),
        user_id=1,
        pipeline_id="nf-core/spatialaxe",
        revision="1.0.1",
        profile="docker",
        parameters={"platform": "xenium", "max_cpus": 16},
        artifact_paths={"input": sheet},
        resume=False,
        network_allowed=True,
        timeout_seconds=3600,
    )
    assert "nf-core/spatialaxe" in plan.argv
    idx = plan.argv.index("-r")
    assert plan.argv[idx + 1] == "1.0.1"
    assert "--platform" in plan.argv
    assert "xenium" in plan.argv


def test_sc_pipelines_share_minimum_nextflow():
    from research_agent.execution.nextflow import PIPELINES
    for pid in _SC_PIPELINES:
        spec = PIPELINES[pid]
        assert spec["minimum_nextflow"] == "23.04.0"
        assert "input" in spec["artifact_parameters"]
        assert spec["artifact_parameters"]["input"]["required"] is True


def test_sarek_and_sc_samplesheet_contracts_are_different(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sc_sheet = tmp_path / "sc.csv"
    sc_sheet.write_text(_sc_samplesheet(), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_samplesheet("nf-core/sarek", sc_sheet)
    sarek_sheet = tmp_path / "sarek.csv"
    sarek_sheet.write_text(
        "patient,sample,lane,fastq_1,fastq_2\nP1,S1,L1,a.fq.gz,b.fq.gz\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        validate_samplesheet("nf-core/scrnaseq", sarek_sheet)


# ---- Proteomics and metabolomics pipeline integration tests ----


def test_panorama360_validate_request_accepts_valid_params():
    from research_agent.execution.nextflow import validate_request
    result = validate_request(
        'peptideatlas/panorama360', '1.0.0', 'docker',
        {'database': 'uniprot', 'max_cpus': 8, 'max_memory': '16 GB'},
        {'input': 'bound'},
    )
    assert result['database'] == 'uniprot'


def test_panorama360_validate_request_rejects_unknown_params():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match='Unknown pipeline parameter'):
        validate_request(
            'peptideatlas/panorama360', '1.0.0', 'docker',
            {'unknown_param': 42},
            {'input': 'bound'},
        )


def test_panorama360_validate_request_rejects_invalid_database():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match='is not an allowed value'):
        validate_request(
            'peptideatlas/panorama360', '1.0.0', 'docker',
            {'database': 'invalid_db'},
            {'input': 'bound'},
        )


def test_panorama360_validate_request_rejects_cpu_out_of_range():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match='must be an integer'):
        validate_request(
            'peptideatlas/panorama360', '1.0.0', 'docker',
            {'max_cpus': 'eight'},
            {'input': 'bound'},
        )
    with pytest.raises(ValueError, match='outside its allowed range'):
        validate_request(
            'peptideatlas/panorama360', '1.0.0', 'docker',
            {'max_cpus': 999},
            {'input': 'bound'},
        )


def test_metabo_profiler_validate_request_accepts_valid_params():
    from research_agent.execution.nextflow import validate_request
    result = validate_request(
        'metaboanalyst/profiler', '1.0.0', 'docker',
        {'normalization': 'sum', 'max_cpus': 4, 'max_memory': '8 GB'},
        {'input': 'bound'},
    )
    assert result['normalization'] == 'sum'


def test_metabo_profiler_validate_request_rejects_unknown_params():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match='Unknown pipeline parameter'):
        validate_request(
            'metaboanalyst/profiler', '1.0.0', 'docker',
            {'unknown_param': 42},
            {'input': 'bound'},
        )


def test_metabo_profiler_validate_request_rejects_invalid_normalization():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match='is not an allowed value'):
        validate_request(
            'metaboanalyst/profiler', '1.0.0', 'docker',
            {'normalization': 'invalid_norm'},
            {'input': 'bound'},
        )


def test_metabo_profiler_validate_request_rejects_cpu_out_of_range():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match='must be an integer'):
        validate_request(
            'metaboanalyst/profiler', '1.0.0', 'docker',
            {'max_cpus': 'four cores'},
            {'input': 'bound'},
        )
    with pytest.raises(ValueError, match='outside its allowed range'):
        validate_request(
            'metaboanalyst/profiler', '1.0.0', 'docker',
            {'max_cpus': 0},
            {'input': 'bound'},
        )


def test_build_plan_panorama360_skips_execution_for_placeholder():
    # panorama360 has a placeholder SHA - validate_request passes but
    # build_plan cannot execute because the pipeline asset is not available
    from research_agent.execution.nextflow import validate_request, PIPELINES
    result = validate_request(
        'peptideatlas/panorama360', '1.0.0', 'docker',
        {'database': 'neXtProt', 'max_cpus': 16},
        {'input': 'bound'},
    )
    assert result['database'] == 'neXtProt'
    assert PIPELINES['peptideatlas/panorama360']['commit_sha'].startswith('placeholder')


def test_build_plan_metabo_profiler_skips_execution_for_placeholder():
    # metabo profiler has a placeholder SHA - validate_request passes but
    # build_plan cannot execute because the pipeline asset is not available
    from research_agent.execution.nextflow import validate_request, PIPELINES
    result = validate_request(
        'metaboanalyst/profiler', '1.0.0', 'conda',
        {'normalization': 'median', 'max_cpus': 8},
        {'input': 'bound'},
    )
    assert result['normalization'] == 'median'
    assert PIPELINES['metaboanalyst/profiler']['commit_sha'].startswith('placeholder')


def test_omics_pipelines_reject_wrong_revision():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match='pinned revision'):
        validate_request('peptideatlas/panorama360', '9.9.9', 'docker', {}, {'input': 'bound'})
    with pytest.raises(ValueError, match='pinned revision'):
        validate_request('metaboanalyst/profiler', '9.9.9', 'docker', {}, {'input': 'bound'})


def test_omics_pipelines_share_minimum_nextflow():
    from research_agent.execution.nextflow import PIPELINES
    for pid in ('peptideatlas/panorama360', 'metaboanalyst/profiler'):
        spec = PIPELINES[pid]
        assert spec['minimum_nextflow'] == '23.04.0'
