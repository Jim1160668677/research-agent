"""Fix test references for diaproteomics and metaboigniter pipelines."""
path = r"G:\智能体设计\科研agent\tests\test_execution_nextflow.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix all remaining old references
content = content.replace(
    "'metaboanalyst/profiler', '1.0.0', 'docker'",
    "'nf-core/metaboigniter', '2.0.1', 'docker'"
)
content = content.replace(
    "'metaboanalyst/profiler', '1.0.0', 'conda'",
    "'nf-core/metaboigniter', '2.0.1', 'conda'"
)
content = content.replace(
    "'peptideatlas/panorama360', '1.0.0'",
    "'nf-core/diaproteomics', '1.2.4'"
)
content = content.replace(
    "'metaboanalyst/profiler', '1.0.0'",
    "'nf-core/metaboigniter', '2.0.1'"
)
content = content.replace(
    "for pid in ('peptideatlas/panorama360', 'metaboanalyst/profiler'):",
    "for pid in ('nf-core/diaproteomics', 'nf-core/metaboigniter'):"
)

# Fix test bodies that reference old params
content = content.replace(
    "        {'database': 'uniprot', 'max_cpus': 8, 'max_memory': '16 GB'},\n    )\n    assert result['database'] == 'uniprot'",
    "        {'max_cpus': 8, 'max_memory': '16 GB'},\n    )\n    assert result['max_cpus'] == 8"
)
content = content.replace(
    "def test_diaproteomics_validate_request_no_database_param():",
    "def test_diaproteomics_validate_request_rejects_invalid_memory():"
)
content = content.replace(
    "            {'database': 'invalid_db'},",
    "            {'max_memory': 'not_memory'},",
)
content = content.replace(
    "        {'normalization': 'sum', 'max_cpus': 4, 'max_memory': '8 GB'},\n    )\n    assert result['normalization'] == 'sum'",
    "        {'max_cpus': 4, 'max_memory': '8 GB'},\n    )\n    assert result['max_cpus'] == 4"
)
content = content.replace(
    "def test_metaboigniter_validate_request_rejects_invalid_normalization():",
    "def test_metaboigniter_validate_request_rejects_invalid_memory():"
)
content = content.replace(
    "            {'normalization': 'invalid_norm'},",
    "            {'max_memory': 'bad'},",
)

# Update comments
content = content.replace(
    "    # panorama360 has a placeholder SHA - validate_request passes but",
    "    # nf-core/diaproteomics has a real SHA - validate_request and build_plan both work"
)
content = content.replace(
    "    # metabo profiler has a placeholder SHA - validate_request passes but",
    "    # nf-core/metaboigniter has a real SHA - validate_request and build_plan both work"
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Test file updated")
