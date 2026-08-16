"""Patch nextflow.py to fix spatial pipeline and add validation."""
from pathlib import Path

FILE = Path("src/research_agent/execution/nextflow.py")
lines = FILE.read_text().splitlines(keepends=True)

# Find the spatial block (lines 178-205 approximately) and replace it
# We'll do a line-by-line replacement
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    # Look for the start of the spatial block
    if '"nf-core/spatial": {' in line:
        # Skip until we find the closing "}," of the spatial block
        # The spatial block starts at this line and ends with "    }," (line 205)
        # Collect all lines until we hit the closing of the dict entry
        indent_count = 0
        started = False
        end_idx = i
        for j in range(i, len(lines)):
            l = lines[j].strip()
            if l.startswith('"nf-core/spatial": {'):
                started = True
                indent_count = 1
                continue
            if started:
                # Count braces (simplified: just look for the pattern)
                if '}, ' in l or l.rstrip() == '},':
                    end_idx = j + 1
                    break
        # Replace lines[i:end_idx] with new content
        new_spatial = [
            '    "nf-core/spatialvi": {\n',
            '        "title": "nf-core/spatialvi",\n',
            '        "description": "Spatially-resolved gene counts analysis: quality control, normalization, and downstream analysis for Visium data.",\n',
            '        "revision": "0.1.0",\n',
            '        "commit_sha": "94e6c049183f5caf5a1081f18957aaf9fb2ba2fa",\n',
            '        "minimum_nextflow": "23.04.0",\n',
            '        "source_url": "https://github.com/nf-core/spatialvi",\n',
            '        "artifact_parameters": {\n',
            '            "input": {"required": True, "suffixes": [".csv"]},\n',
            '            "bam": {"required": False, "suffixes": [".bam", ".cram"]},\n',
            '            "fastq": {"required": False, "suffixes": [".fastq.gz", ".fq.gz"]},\n',
            '        },\n',
            '        "parameters": {\n',
            '            "platform": {\n',
            '                "type": "enum",\n',
            '                "values": ["visium", "visium_hdf5"],\n',
            '            },\n',
            '            "min_genes": {"type": "integer", "minimum": 200, "maximum": 10000},\n',
            '            "min_cells": {"type": "integer", "minimum": 3, "maximum": 1000},\n',
            '            "max_cpus": {\n',
            '                "type": "integer",\n',
            '                "minimum": 1,\n',
            '                "maximum": 256,\n',
            '                "control": True,\n',
            '            },\n',
            '            "max_memory": {"type": "memory", "control": True},\n',
            '        },\n',
            '    },\n',
            '    "nf-core/spatialaxe": {\n',
            '        "title": "nf-core/spatialaxe",\n',
            '        "description": "Processing and quality control pipeline for Xenium and Artera spatial data.",\n',
            '        "revision": "1.0.1",\n',
            '        "commit_sha": "748d310ac01943c97a15bdbc27ec2525a3ee0a96",\n',
            '        "minimum_nextflow": "23.04.0",\n',
            '        "source_url": "https://github.com/nf-core/spatialaxe",\n',
            '        "artifact_parameters": {\n',
            '            "input": {"required": True, "suffixes": [".csv"]},\n',
            '            "image": {"required": False, "suffixes": [".tiff", ".tif", ".png", ".h5"]},\n',
            '        },\n',
            '        "parameters": {\n',
            '            "platform": {\n',
            '                "type": "enum",\n',
            '                "values": ["xenium", "artera"],\n',
            '            },\n',
            '            "max_cpus": {\n',
            '                "type": "integer",\n',
            '                "minimum": 1,\n',
            '                "maximum": 256,\n',
            '                "control": True,\n',
            '            },\n',
            '            "max_memory": {"type": "memory", "control": True},\n',
            '        },\n',
            '    },\n',
        ]
        new_lines.extend(new_spatial)
        i = end_idx
        continue
    new_lines.append(line)
    i += 1

FILE.write_text(''.join(new_lines))
print("Patched nextflow.py spatial pipeline")
