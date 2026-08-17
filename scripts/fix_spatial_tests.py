import re

path = r'tests\test_execution_nextflow.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix spatialvi and spatialaxe tests: invalid platform is an enum violation, not unknown param
content = content.replace(
    'def test_spatialvi_rejects_invalid_platform():\n    from research_agent.execution.nextflow import validate_request\n    with pytest.raises(ValueError, match="Unknown pipeline parameter"):',
    'def test_spatialvi_rejects_invalid_platform():\n    from research_agent.execution.nextflow import validate_request\n    with pytest.raises(ValueError, match="is not an allowed value"):'
)
content = content.replace(
    'def test_spatialaxe_rejects_invalid_platform():\n    from research_agent.execution.nextflow import validate_request\n    with pytest.raises(ValueError, match="Unknown pipeline parameter"):',
    'def test_spatialaxe_rejects_invalid_platform():\n    from research_agent.execution.nextflow import validate_request\n    with pytest.raises(ValueError, match="is not an allowed value"):'
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
