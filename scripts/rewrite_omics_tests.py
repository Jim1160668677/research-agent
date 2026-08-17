import re

path = r'tests\test_execution_nextflow.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace the entire omics test section
start_marker = '# ---- Proteomics and metabolomics pipeline integration tests ----'
end_pos = len(content)  # goes to end of file

# Find the start
start_idx = content.index(start_marker)
new_omics_tests = '''# ---- Proteomics and metabolomics pipeline integration tests ----


def test_panorama360_validate_request_accepts_valid_params():
    from research_agent.execution.nextflow import validate_request
    result = validate_request(
        'peptideatlas/panorama360', '1.0.0', 'docker',
        {'database': 'uniprot', 'max_cpus': 8, 'max_memory': '16.GB'},
        {'input': 'bound'},
    )
    assert result['pipeline_id'] == 'peptideatlas/panorama360'
    assert result['status'] == 'valid'


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
        {'normalization': 'sum', 'max_cpus': 4, 'max_memory': '8.GB'},
        {'input': 'bound'},
    )
    assert result['pipeline_id'] == 'metaboanalyst/profiler'
    assert result['status'] == 'valid'


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


@pytest.mark.asyncio
async def test_build_plan_panorama360(tmp_path):
    from research_agent.execution.nextflow import NextflowBackend
    backend = NextflowBackend(root=tmp_path / 'runs', transport='native')
    plan = await backend.build_plan(
        run_id=str(__import__('uuid').uuid4()),
        user_id=1,
        pipeline_id='peptideatlas/panorama360',
        revision='1.0.0',
        profile='docker',
        parameters={'database': 'neXtProt', 'max_cpus': 16, 'max_memory': '32.GB'},
        artifact_paths={'input': tmp_path / 'proteomics.csv'},
        resume=False,
        network_allowed=True,
        timeout_seconds=3600,
    )
    assert plan.pipeline_id == 'peptideatlas/panorama360'
    assert plan.profile == 'docker'


@pytest.mark.asyncio
async def test_build_plan_metabo_profiler(tmp_path):
    from research_agent.execution.nextflow import NextflowBackend
    backend = NextflowBackend(root=tmp_path / 'runs', transport='native')
    plan = await backend.build_plan(
        run_id=str(__import__('uuid').uuid4()),
        user_id=1,
        pipeline_id='metaboanalyst/profiler',
        revision='1.0.0',
        profile='conda',
        parameters={'normalization': 'median', 'max_cpus': 8, 'max_memory': '16.GB'},
        artifact_paths={'input': tmp_path / 'metabolites.csv'},
        resume=False,
        network_allowed=True,
        timeout_seconds=3600,
    )
    assert plan.pipeline_id == 'metaboanalyst/profiler'
    assert plan.profile == 'conda'


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
'''

content = content[:start_idx] + new_omics_tests
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
