import re

path = r'tests\test_execution_nextflow.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix validate_request calls in omics tests - they're missing artifact_bindings={}
# Pattern: validate_request(\n        'pipeline', 'rev', 'prof',\n        {params},\n    )
# Need to add , {} after the params dict

# Fix panorama360 calls
content = content.replace(
    "validate_request(\n        'peptideatlas/panorama360', '1.0.0', 'docker',\n        {'database': 'uniprot', 'max_cpus': 8, 'max_memory': '16.GB'},\n    )",
    "validate_request(\n        'peptideatlas/panorama360', '1.0.0', 'docker',\n        {'database': 'uniprot', 'max_cpus': 8, 'max_memory': '16.GB'},\n        {},\n    )"
)
content = content.replace(
    "validate_request(\n            'peptideatlas/panorama360', '1.0.0', 'docker',\n            {'unknown_param': 42},\n        )",
    "validate_request(\n            'peptideatlas/panorama360', '1.0.0', 'docker',\n            {'unknown_param': 42},\n            {},\n        )"
)
content = content.replace(
    "validate_request(\n            'peptideatlas/panorama360', '1.0.0', 'docker',\n            {'database': 'invalid_db'},\n        )",
    "validate_request(\n            'peptideatlas/panorama360', '1.0.0', 'docker',\n            {'database': 'invalid_db'},\n            {},\n        )"
)
content = content.replace(
    "validate_request(\n            'peptideatlas/panorama360', '1.0.0', 'docker',\n            {'max_cpus': 'eight'},\n        )",
    "validate_request(\n            'peptideatlas/panorama360', '1.0.0', 'docker',\n            {'max_cpus': 'eight'},\n            {},\n        )"
)
content = content.replace(
    "validate_request(\n            'peptideatlas/panorama360', '1.0.0', 'docker',\n            {'max_cpus': 999},\n        )",
    "validate_request(\n            'peptideatlas/panorama360', '1.0.0', 'docker',\n            {'max_cpus': 999},\n            {},\n        )"
)

# Fix metabo profiler calls
content = content.replace(
    "validate_request(\n        'metaboanalyst/profiler', '1.0.0', 'docker',\n        {'normalization': 'sum', 'max_cpus': 4, 'max_memory': '8.GB'},\n    )",
    "validate_request(\n        'metaboanalyst/profiler', '1.0.0', 'docker',\n        {'normalization': 'sum', 'max_cpus': 4, 'max_memory': '8.GB'},\n        {},\n    )"
)
content = content.replace(
    "validate_request(\n            'metaboanalyst/profiler', '1.0.0', 'docker',\n            {'unknown_param': 42},\n        )",
    "validate_request(\n            'metaboanalyst/profiler', '1.0.0', 'docker',\n            {'unknown_param': 42},\n            {},\n        )"
)
content = content.replace(
    "validate_request(\n            'metaboanalyst/profiler', '1.0.0', 'docker',\n            {'normalization': 'invalid_norm'},\n        )",
    "validate_request(\n            'metaboanalyst/profiler', '1.0.0', 'docker',\n            {'normalization': 'invalid_norm'},\n            {},\n        )"
)
content = content.replace(
    "validate_request(\n            'metaboanalyst/profiler', '1.0.0', 'docker',\n            {'max_cpus': 'four cores'},\n        )",
    "validate_request(\n            'metaboanalyst/profiler', '1.0.0', 'docker',\n            {'max_cpus': 'four cores'},\n            {},\n        )"
)
content = content.replace(
    "validate_request(\n            'metaboanalyst/profiler', '1.0.0', 'docker',\n            {'max_cpus': 0},\n        )",
    "validate_request(\n            'metaboanalyst/profiler', '1.0.0', 'docker',\n            {'max_cpus': 0},\n            {},\n        )"
)

# Fix the wrong revision calls (single-line)
content = content.replace(
    "validate_request('peptideatlas/panorama360', '9.9.9', 'docker', {})",
    "validate_request('peptideatlas/panorama360', '9.9.9', 'docker', {}, {})"
)
content = content.replace(
    "validate_request('metaboanalyst/profiler', '9.9.9', 'docker', {})",
    "validate_request('metaboanalyst/profiler', '9.9.9', 'docker', {}, {})"
)

# Fix the space before @ in second async test
content = content.replace('@ pytest.mark.asyncio', '@pytest.mark.asyncio')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
