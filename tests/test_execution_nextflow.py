import asyncio
import uuid

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
