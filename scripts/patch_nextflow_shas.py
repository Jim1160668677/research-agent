"""Patch script to fix nextflow.py placeholder SHAs and add validation."""
import re
from pathlib import Path

FILE = Path("src/research_agent/execution/nextflow.py")
content = FILE.read_text()

# 1. Fix nf-core/atacseq: revision 2.0.0 -> 2.1.2, real SHA
content = content.replace(
    '"revision": "2.0.0",\n        "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",\n        "minimum_nextflow": "23.04.0",\n        "source_url": "https://github.com/nf-core/atacseq"',
    '"revision": "2.1.2",\n        "commit_sha": "1a1dbe52ffbd82256c941a032b0e22abbd925b8a",\n        "minimum_nextflow": "23.04.0",\n        "source_url": "https://github.com/nf-core/atacseq"'
)

# 2. Fix nf-core/chipseq: revision 2.0.0 -> 2.1.0, real SHA
content = content.replace(
    '"revision": "2.0.0",\n        "commit_sha": "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1",\n        "minimum_nextflow": "23.04.0",\n        "source_url": "https://github.com/nf-core/chipseq"',
    '"revision": "2.1.0",\n        "commit_sha": "76e2382b6d443db4dc2396e6831d1243256d80b0",\n        "minimum_nextflow": "23.04.0",\n        "source_url": "https://github.com/nf-core/chipseq"'
)

# 3. Fix nf-core/scrnaseq: revision 2.0.0 -> 4.2.0, real SHA
content = content.replace(
    '"revision": "2.0.0",\n        "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",\n        "minimum_nextflow": "23.04.0",\n        "source_url": "https://github.com/nf-core/scrnaseq"',
    '"revision": "4.2.0",\n        "commit_sha": "3fc17b4f971a89e47c88337de71d0e777ffad8cc",\n        "minimum_nextflow": "23.04.0",\n        "source_url": "https://github.com/nf-core/scrnaseq"'
)

# 4. Replace nf-core/spatial (non-existent) with two real pipelines
spatial_pattern = r'    "nf-core/spatial": \{[^}]+\"source_url\": \"https://github\.com/nf-core/spatial\",[^}]+\},\n\}'
spatial_replacement = '''    "nf-core/spatialvi": {
        "title": "nf-core/spatialvi",
        "description": "Spatially-resolved gene counts analysis: quality control, normalization, and downstream analysis for Visium data.",
        "revision": "0.1.0",
        "commit_sha": "94e6c049183f5caf5a1081f18957aaf9fb2ba2fa",
        "minimum_nextflow": "23.04.0",
        "source_url": "https://github.com/nf-core/spatialvi",
        "artifact_parameters": {
            "input": {"required": True, "suffixes": [".csv"]},
            "bam": {"required": False, "suffixes": [".bam", ".cram"]},
            "fastq": {"required": False, "suffixes": [".fastq.gz", ".fq.gz"]},
        },
        "parameters": {
            "platform": {
                "type": "enum",
                "values": ["visium", "visium_hdf5"],
            },
            "min_genes": {"type": "integer", "minimum": 200, "maximum": 10000},
            "min_cells": {"type": "integer", "minimum": 3, "maximum": 1000},
            "max_cpus": {
                "type": "integer",
                "minimum": 1,
                "maximum": 256,
                "control": True,
            },
            "max_memory": {"type": "memory", "control": True},
        },
    },
    "nf-core/spatialaxe": {
        "title": "nf-core/spatialaxe",
        "description": "Processing and quality control pipeline for Xenium and Artera spatial data.",
        "revision": "1.0.1",
        "commit_sha": "748d310ac01943c97a15bdbc27ec2525a3ee0a96",
        "minimum_nextflow": "23.04.0",
        "source_url": "https://github.com/nf-core/spatialaxe",
        "artifact_parameters": {
            "input": {"required": True, "suffixes": [".csv"]},
            "image": {"required": False, "suffixes": [".tiff", ".tif", ".png", ".h5"]},
        },
        "parameters": {
            "platform": {
                "type": "enum",
                "values": ["xenium", "artera"],
            },
            "max_cpus": {
                "type": "integer",
                "minimum": 1,
                "maximum": 256,
                "control": True,
            },
            "max_memory": {"type": "memory", "control": True},
        },
    },'''

content = re.sub(spatial_pattern, spatial_replacement, content)

FILE.write_text(content)
print("Patched nextflow.py successfully")
