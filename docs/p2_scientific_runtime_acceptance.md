# P2 scientific runtime acceptance

This document defines the supported Windows desktop execution path for real
nf-core work. It is an operational contract, not a promise that a detected
binary is usable.

## Supported runtime

- Windows host with WSL2 and an Ubuntu distribution.
- OpenJDK 21 inside WSL2.
- Nextflow `25.10.2`, forced for probes and executions through `NXF_VER`.
- Docker Engine inside the selected WSL2 distribution. A Docker Desktop
  installation alone does not satisfy preflight; `docker info` must return a
  server version from the same WSL transport used for execution.
- Pinned pipelines: nf-core/rnaseq `3.26.0` and nf-core/sarek `3.9.0`.

The application performs a deep preflight before allocation: WSL transport,
Nextflow version, selected container runtime, pinned pipeline compatibility,
network policy, cached revision requirements, and workspace capacity are
reported separately.

## Execution guarantees

1. User values are validated against a per-pipeline allowlist. Commands are
   argument arrays and never shell-concatenated.
2. `max_cpus` and `max_memory` are scheduler controls, not nf-core business
   parameters. The backend writes a run-scoped `resource-limits.config` using
   the local executor CPU/memory pool, `process.resourceLimits`, and a
   single-slot executor queue, then loads it with `nextflow -c`. The queue is
   deliberately serialized because mixed tasks can otherwise overlap at
   process boundaries and make aggregate declared resources exceed the
   desktop budget even when every individual task is capped.
3. Each run owns its output, work, report, PID and configuration paths. On
   Windows, compute work is placed in a stable private directory on WSL ext4;
   reports and published results remain in the desktop data directory. This is
   a functional requirement because STAR creates FIFO files that DrvFs/NTFS
   cannot represent. The runner records the resolved WSL path for recovery,
   while public plans and log tails redact it.
4. Cancellation targets the WSL process group recorded by the managed runner;
   it does not terminate the WSL distribution or Docker daemon globally.
5. Resume preserves the work/cache directory. Before `-resume`, previous
   report, trace and console files move to `attempts/attempt-NNN/`, with an
   `attempt.json` SHA-256 manifest. A resumed result parses only the new trace.
6. Reports and bounded result manifests include relative path, size and
   SHA-256 where the hashing budget permits.

The split storage model also avoids using the Windows project volume as a
container scratch disk. A failed or interrupted attempt does not delete either
side: report files are archived, and the stable ext4 work key allows a later
`-resume` to reuse valid task hashes.

## Official RNA-seq acceptance profile

The desktop exposes an explicit `test_profile` control for nf-core/rnaseq. It
requires network access and does not require a user samplesheet or reference.
The pipeline still runs with the official `test,docker` profiles.

The upstream profile contains GitHub Raw URLs, including nested URLs in its
samplesheet and BBSplit list. On networks where the Raw CDN has long TCP
retransmission stalls, the backend creates equivalent run-scoped manifests:

- general references: commit
  `626c8fab639062eade4b10747e919341cbf9b41a`;
- RNA-seq reads/reference branch snapshot:
  `e07c1b158d1c4c9ea7978959d31e651098bec581`;
- Kraken test database:
  `eb0cbf73c3f103f8aeda9878ba200e92b4d045d8`.

Only the transfer endpoint changes to jsDelivr's GitHub commit form. The
generated samplesheet and BBSplit list are hashed and their revisions and
SHA-256 values are stored in provenance. A moving branch or unversioned URL is
never recorded as sufficient evidence.

## Provisioning and verification

For a managed validation run:

```powershell
python scripts/validate_nextflow_runtime.py `
  --root runtime-validation `
  --run-id <uuid> `
  --resume `
  --max-cpus 4 `
  --max-memory "7 GB" `
  --timeout 7200
```

Before release, require all of the following:

- deep preflight `ready=true` and exact Nextflow version `25.10.2`;
- Docker server probe succeeds inside WSL2;
- the public plan contains `-profile test,docker`, `-c` and `-resume` when
  applicable, but contains no `--max_cpus` or `--max_memory`;
- the resolved local monitor reports the requested CPU/memory pool and
  `capacity=1`; submitted/completed event accounting observes no overlap;
- trace has task rows, no failed/aborted tasks, and the process exits zero;
- report, timeline, trace, DAG, Nextflow log and result artifacts are present;
- full Python tests, Ruff and the Vue production build pass;
- the packaged desktop repeats capability/preflight/API smoke tests in a clean
  application data directory.

The 2026-08-13 golden run satisfied these gates with exit code zero, 191
completed tasks, 43 cached tasks, no failures/aborts/retries, all four
Nextflow reports, a MultiQC report and a complete 1,044-file result manifest.

The final frozen-package replay used run
`5fafd00b-a363-49b0-9497-b9fd893c28ce`. It exited zero with 234 tasks (223
cached, 11 completed), no failures/retries/aborts, and a complete 842-file
result manifest. Nextflow reported `peakRunning=1`, `peakCpus=4` and
`peakMemory=7 GB`; the acceptance parser independently observed submitted-task
peak 1 and resolved `cpus=4; memory=7 GB; capacity=1`. Report, timeline, trace,
DAG, Nextflow log and MultiQC outputs were all hashed.

The frozen-package smoke is reproducible with:

```powershell
python scripts/validate_frozen_desktop.py `
  --exe dist/ResearchAgent/ResearchAgent.exe `
  --profile-root runtime-validation/frozen-p2-<timestamp> `
  --execute
```

## Known external constraints

- Container cold starts depend on registry throughput. Seqera Wave images can
  be substantially slower than Quay on some routes. Do not substitute an
  approximately equivalent image unless every required tool version is
  verified and the replacement digest is recorded.
- The current Docker Desktop release may require a newer Windows build than the
  host. In that case, use the WSL2 Docker Engine path; do not reset or mutate a
  user's Desktop installation merely to satisfy discovery.
- The application validates workflows and preserves evidence, but scientific
  interpretation remains subject to domain review and the pipeline's own
  limitations.
