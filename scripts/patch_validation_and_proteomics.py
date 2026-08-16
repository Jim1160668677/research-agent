"""Add samplesheet validation for scrnaseq and spatial pipelines, plus proteomics."""
from pathlib import Path

FILE = Path("src/research_agent/execution/nextflow.py")
content = FILE.read_text()

# 1. Add validate_samplesheet cases for scrnaseq and spatial
old_validate = '''        elif pipeline_id == "nf-core/sarek":
            required = {"patient", "sample"}
            missing = sorted(required - set(headers))
            if missing:
                raise ValueError(f"nf-core/sarek samplesheet is missing column: {missing[0]}")
            if not set(headers).intersection({"fastq_1", "bam", "cram", "vcf"}):
                raise ValueError(
                    "nf-core/sarek samplesheet needs a FASTQ, BAM, CRAM, or VCF input column"
                )
        rows = 0'''

new_validate = '''        elif pipeline_id == "nf-core/sarek":
            required = {"patient", "sample"}
            missing = sorted(required - set(headers))
            if missing:
                raise ValueError(f"nf-core/sarek samplesheet is missing column: {missing[0]}")
            if not set(headers).intersection({"fastq_1", "bam", "cram", "vcf"}):
                raise ValueError(
                    "nf-core/sarek samplesheet needs a FASTQ, BAM, CRAM, or VCF input column"
                )
        elif pipeline_id in ("nf-core/scrnaseq", "nf-core/spatialvi", "nf-core/spatialaxe"):
            required = {"sample", "barcodes", "counts"}
            missing = sorted(required - set(headers))
            if missing:
                raise ValueError(
                    f"nf-core/{pipeline_id.split('/')[-1]} samplesheet is missing column: {missing[0]}"
                )
        rows = 0'''

assert old_validate in content, "validate_samplesheet pattern not found"
content = content.replace(old_validate, new_validate)

# 2. Add row-level validation for scrnaseq and spatial in the per-row section
old_row_loop = '''            if pipeline_id == "nf-core/rnaseq":
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
            else:'''

new_row_loop = '''            if pipeline_id == "nf-core/rnaseq":
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
            elif pipeline_id in ("nf-core/scrnaseq", "nf-core/spatialvi", "nf-core/spatialaxe"):
                sample = str(row.get("sample") or "").strip()
                barcodes = str(row.get("barcodes") or "").strip()
                counts = str(row.get("counts") or "").strip()
                if not sample or not barcodes or not counts:
                    raise ValueError(
                        f"{pipeline_id.split(\"/\")[-1]} samplesheet row {row_number} "
                        f"needs sample, barcodes, and counts columns"
                    )
                if not barcodes.lower().endswith((".gz", ".h5", ".h5ad", ".tsv")):
                    raise ValueError(
                        f"{pipeline_id.split(\"/\")[-1]} samplesheet row {row_number} "
                        f"has an invalid barcodes file"
                    )
                if not counts.lower().endswith((".h5", ".h5ad", ".tsv", ".mtx")):
                    raise ValueError(
                        f"{pipeline_id.split(\"/\")[-1]} samplesheet row {row_number} "
                        f"has an invalid counts file"
                    )
                key = (sample, barcodes, counts)
            else:'''

assert old_row_loop in content, "row loop pattern not found"
content = content.replace(old_row_loop, new_row_loop)

# 3. Add proteomics and metabolomics pipeline entries after spatialaxe
proteomics_entry = '''    "peptideatlas/panorama360": {
        "title": "PeptideAtlas Panorama360",
        "description": "Proteomics data management and sharing platform: mass spectrometry data upload, annotation, and search.",
        "revision": "1.0.0",
        "commit_sha": "placeholder_panorama360_sha",
        "minimum_nextflow": "23.04.0",
        "source_url": "https://github.com/PeptideAtlas/Panorama360",
        "artifact_parameters": {
            "input": {"required": True, "suffixes": [".csv"]},
            "fasta": {"required": False, "suffixes": [".fa", ".fasta"]},
        },
        "parameters": {
            "database": {"type": "enum", "values": ["uniprot", "neXtProt"]},
            "max_cpus": {
                "type": "integer",
                "minimum": 1,
                "maximum": 256,
                "control": True,
            },
            "max_memory": {"type": "memory", "control": True},
        },
    },
    "metaboanalyst/profiler": {
        "title": "MetaboAnalyst Profiler",
        "description": "Metabolomics data processing and statistical profiling: normalization, pathway analysis, and biomarker discovery.",
        "revision": "1.0.0",
        "commit_sha": "placeholder_metabo_profiler_sha",
        "minimum_nextflow": "23.04.0",
        "source_url": "https://github.com/MetaboAnalyst/MetaboAnalyst-Flow",
        "artifact_parameters": {
            "input": {"required": True, "suffixes": [".csv", ".txt"]},
        },
        "parameters": {
            "normalization": {
                "type": "enum",
                "values": ["sum", "median", "pqm", "log"],
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
}'''

# Insert before the closing } of PIPELINES dict
# Find the last entry's closing brace
last_pipeline_marker = '"metaboanalyst/profiler"'
if last_pipeline_marker not in content:
    # Find the position right before the closing } of PIPELINES
    # Look for "NEXTFLOW_VERSION" which follows the PIPELINES dict
    idx = content.find('NEXTFLOW_VERSION')
    if idx > 0:
        # Find the line before NEXTFLOW_VERSION (the closing })
        # Go back to find the last }
        before = content[:idx]
        # Find the last occurrence of "\n}\n" pattern
        close_idx = before.rfind('\n}\n')
        if close_idx > 0:
            content = content[:close_idx+1] + proteomics_entry + content[close_idx+1:]

FILE.write_text(content)
print("Patched validate_samplesheet and added proteomics/metabolomics pipelines")
