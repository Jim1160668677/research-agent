const fs = require('fs');
const tests = `

# ---- Single-cell and spatial transcriptomics pipeline integration tests ----

_SC_PIPELINES = [
    "nf-core/scrnaseq",
    "nf-core/spatialvi",
    "nf-core/spatialaxe",
]


def _sc_samplesheet():
    return "sample,barcodes,counts\\nS1,barcodes.gz,counts.h5ad\\n"


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
    with pytest.raises(ValueError, match="Unknown pipeline parameter"):
        validate_request(
            "nf-core/spatialvi", "0.1.0", "docker",
            {"platform": "invalid_platform"},
            {"input": "artifact-id"},
        )


def test_spatialaxe_rejects_invalid_platform():
    from research_agent.execution.nextflow import validate_request
    with pytest.raises(ValueError, match="Unknown pipeline parameter"):
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
    sheet.write_text("sample,other_column\\nS1,val\\n", encoding="utf-8")
    for pipeline_id in _SC_PIPELINES:
        with pytest.raises(ValueError, match="missing column"):
            validate_samplesheet(pipeline_id, sheet)


def test_sc_samplesheet_rejects_empty_cells(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "empty_cells.csv"
    sheet.write_text(
        "sample,barcodes,counts\\nS1,,counts.h5ad\\n", encoding="utf-8"
    )
    for pipeline_id in _SC_PIPELINES:
        with pytest.raises(ValueError, match="needs sample, barcodes, and counts"):
            validate_samplesheet(pipeline_id, sheet)


def test_sc_samplesheet_rejects_invalid_barcodes_extension(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "bad_barcodes.csv"
    sheet.write_text(
        "sample,barcodes,counts\\nS1,barcodes.txt,counts.h5ad\\n", encoding="utf-8"
    )
    for pipeline_id in _SC_PIPELINES:
        with pytest.raises(ValueError, match="invalid barcodes file"):
            validate_samplesheet(pipeline_id, sheet)


def test_sc_samplesheet_rejects_invalid_counts_extension(tmp_path):
    from research_agent.execution.nextflow import validate_samplesheet
    sheet = tmp_path / "bad_counts.csv"
    sheet.write_text(
        "sample,barcodes,counts\\nS1,barcodes.gz,counts.txt\\n", encoding="utf-8"
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
        sheet.write_text(f"sample,barcodes,counts\\nS1,{bcs},{cts}\\n", encoding="utf-8")
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
        "patient,sample,lane,fastq_1,fastq_2\\nP1,S1,L1,a.fq.gz,b.fq.gz\\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        validate_samplesheet("nf-core/scrnaseq", sarek_sheet)
`;
fs.appendFileSync('tests/test_execution_nextflow.py', tests, 'utf-8');
console.log('Appended', tests.split('\n').length, 'lines');
