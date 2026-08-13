# Verification report

## 2026-08-14 recovery verification

After restoring the complete local desktop/runtime assets, the exact repaired source baseline completed **259 passed, 0 failed**. The standard `dist\ResearchAgent\ResearchAgent.exe` build passed fresh-profile security, complete nine-stage research-flow, and deep WSL2/Nextflow/Docker preflight checks. A real pinned `nf-core/rnaseq@3.26.0` `test,docker` execution completed 234 tasks with no failures and produced 967 result files. The repaired executable SHA-256 is `7F326E2C285681A47AF82EDAE6DA144CE235858E7E2E9EDE2B72BA51C25F9B30`.

The new pipeline-cache acceptance path pins the upstream commit, uses Windows Git for network prefetch, disables CRLF conversion, enables Windows long paths, compares every tracked worktree file with its raw Git blob, and only activates a verified candidate. Full evidence and the problem/fix matrix are in [the recovery and full-function acceptance report](recovery_and_full_function_acceptance_20260814.md).

Date: 2026-08-13

## P4 final verification — Research Agent 1.3.0

The final P4 source suite collected **256 tests** and completed with **256 passed, 0 failed in 244.57 seconds**. Ten new cases cover current DeepSeek/Agnes contracts, retry behavior, Agnes CLI version/argv/JSON behavior, process-wide synchronization, the Nature-inspired discovery DAG, authenticated provider configuration, startup recovery, and a complete nine-stage scientific business flow.

A real Agnes integration smoke returned exactly `pong` from `agnes-2.0-flash` in one attempt: 4,716 ms and 308 total tokens. This test found and closed a Windows-only CLI transport defect in which CR/LF characters passed through `npx.cmd` could terminate the batch command before `--json`. DeepSeek contract, retry, API and UI behavior passed; a live DeepSeek request was not executed because `DEEPSEEK_API_KEY` was not configured.

The production Vue build transformed 105 modules in 2.25 seconds and emitted `index-BS1ybbmK.css` (75.79 kB) and `index-D59fYViG.js` (245.11 kB). P4 benchmark and frozen-package evidence are recorded in [the dedicated acceptance report](p4_co_scientist_model_sync_acceptance.md).

The 1.3.0 PyInstaller build completed in 585.4 seconds. Its executable is 38,460,859 bytes with SHA-256 `9157021846D58ADD5F853C55DCE2166A1069111BCBD89A09013EA2CA5495F8A4`; the onedir distribution contains 1,388 files totaling 593,352,246 bytes. A fresh-profile frozen black-box run verified version 1.3.0, all five providers, an actual packaged Agnes call (CLI 0.1.0, 4,508 ms), the complete nine-stage discovery loop at 100%, and a drained global runtime. The raw isolated validation profile was deleted during the repository cleanup because it contained reproducible runtime databases, logs and session state; this report is the retained release record.

## Automated coverage

Final P3 result: **246 passed, 0 failed** in the complete Python suite (`238.32s`).

The suite covers:

- API health, authentication, skills, recommendations, plugins, workflows, security helpers, and user isolation;
- the research planner's dependency graph, cycle/registration validation, and artifact-triggered multimodal intake;
- deny-by-default tool policy, network/approval filtering, bounded concurrency, timeouts, retries, cancellation, and persisted run state;
- evidence normalization and DOI/PMID/title deduplication with source locators and explicit gaps;
- experimental-design contracts, ethics/review gates, writing scaffolds, claim-evidence matrices, and academic-integrity findings;
- CSV profiling, safe artifact paths, user-scoped upload APIs, PDF/image/table metadata, and generated visualization artifacts;
- proposal-only learning: feedback cannot silently change behavior, and preferences require an explicit apply/reject/quarantine decision;
- desktop configuration, atomic state, single-instance locks, embedded backend lifecycle, and fallbacks;
- LLM providers, encrypted key management, chat persistence, LangGraph orchestration, NCBI adapters, docking/structure adapters, plugin lifecycle, and workflow execution.
- NCBI JSON/XML protocol handling, batching, GenBank conversion, BLAST polling, retry/rate limiting, typed workflow references, active-node cancellation, recommendation feedback/isolation, and isolated plugin deployment RBAC.
- Capability Manifest v1 validation/digests/version pinning, append-only plugin lifecycle, truthful selection/deployment states, Bioconda fixed-source sync/cache/atomic rollback, platform probes, and bounded managed-environment removal.
- External execution contracts, pinned nf-core validation, RNA-seq/Sarek samplesheet contracts, WSL2 conversion, runtime/disk preflight, process-tree cancellation, attempt-numbered recovery/resume, native Nextflow resource limits, fixed-commit acceptance manifests, trace parsing, bounded result manifests, artifact containment, log redaction, RBAC, and user isolation.
- AES-256-GCM research-artifact envelopes, dual ciphertext/plaintext integrity verification, privacy-minimized metadata, temporary-plaintext cleanup and crash recovery, verified user-scoped downloads, legacy plaintext migration, and HMAC audit-chain tamper detection.

Run:

```powershell
python -m pytest -q --tb=short
```

Static verification passed for the new P3 files:

```powershell
python -m compileall -q src scripts/validate_frozen_security.py
ruff check src/research_agent/audit_chain.py tests/test_data_security.py scripts/validate_frozen_security.py
```

The repository-wide Ruff run still reports pre-existing modernization and formatting debt in legacy modules. No automatic broad rewrite was applied because that would be unrelated to P3 and high-risk; the newly added files pass the configured rules without ignores.

## Performance baseline

The bounded local benchmark (`scripts/benchmark_research_runtime.py`) measured:

| Workload | Result |
|---|---:|
| Full-scope deterministic planning, 1,000 calls | 0.0306s total / 0.031ms per call |
| Evidence normalization, 200 records × 200 calls | 0.6532s total / 3.266ms per call |
| 50,000-row CSV profiling, 3 calls | 1.8291s total / 609.693ms per call |

These numbers are a regression baseline for this machine, not a cross-machine service-level guarantee. Network retrieval and external model latency are deliberately excluded.

## Frontend production build

```powershell
Set-Location frontend
node .\node_modules\vite\bin\vite.js build
```

The verified P3 source build transformed **105 modules** and emitted the hashed `index-B_8CywLJ.css` and `index-jgGz0vc-.js` production assets.

## Windows package verification

```powershell
.\scripts\build_desktop.ps1
```

The onedir PyInstaller build completed successfully and produced:

```text
dist\ResearchAgent\ResearchAgent.exe
```

The final P3 executable is **38,432,933 bytes** (SHA-256 `A28A63952212EB425C42DEB81C147C64D887F1B3DFCD6A5C7F48C309E70A913F`). The complete onedir distribution contains 1,388 files totaling 593,319,031 bytes. The production frontend is copied to `_internal\frontend\dist` with the verified P3 hashed assets.

A fresh, isolated `%APPDATA%` frozen-start smoke test directly observed:

- application version `1.2.0` starting from the packaged `_internal` resources;
- a new installation secret, SQLite database, log directory, and single-instance record;
- registration of all 18 built-in skills;
- the production frontend directory being mounted;
- the embedded API publishing a random loopback port and returning HTTP 200 to consecutive `/health` probes;
- native tray and WebView2 initialization.

The 2026-08-12 post-P0 frozen smoke used an isolated `%APPDATA%` profile and directly observed a random loopback port (`61760`), `healthy` from `/health`, HTTP 200 from the SPA root, and the expected `initialized: false` first-run auth state. It then created the isolated test owner, authenticated to the frozen API, verified Capability Manifest Schema `1.0`, observed the Windows platform capability response, and confirmed an injection-shaped Bioconda package name is rejected with HTTP 400 before network access. The exact smoke process (`PID 27516`) was then terminated.

The final post-P1 frozen smoke used another isolated `%APPDATA%` profile and observed loopback port `64040`, `healthy` from `/health`, SPA HTTP 200, `initialized: false`, and a newly created admin owner. The authenticated frozen API returned the `allowlisted-and-revision-pinned` policy, `nf-core/rnaseq@3.26.0`, `nf-core/sarek@3.9.0`, default transport `wsl2`, and truthful shallow capability state `available: false` / `probe_required: true`. The exact smoke process (`PID 22704`) was terminated after the checks.

The final P2 frozen execution used the isolated profile at `runtime-validation/frozen-p2-e2e-final-20260813-092536`. It observed a healthy loopback API, authenticated the isolated owner, matched the single-instance PID, and passed deep WSL2/Nextflow/Docker/FIFO/storage preflight with no issues. Run `5fafd00b-a363-49b0-9497-b9fd893c28ce` completed the official `nf-core/rnaseq@3.26.0` `test,docker` flow with exit code zero: 234 tasks, 223 cached, 11 completed, 0 failed/retried/aborted. The final result manifest recorded all 842 files, hashed 78,494,173 bytes, and reported no truncation or hash-budget exhaustion. Nextflow resolved the local executor to 4 CPUs, 7 GB, capacity 1 and reported `peakRunning=1`, `peakCpus=4`, `peakMemory=7 GB`; independent event accounting also observed submitted-task peak 1. The report, timeline, trace, DAG, Nextflow log and MultiQC report were non-empty and SHA-256 verified. Physical WSL work paths remained redacted, and the complete evidence is saved as `frozen-smoke-result.json`.

The final P3 frozen security validation used the clean isolated profile at `runtime-validation/frozen-p3-security-final-20260813-213631`. It completed first-owner setup, stored one sensitive CSV as an opaque `RAART001` envelope with no source plaintext in the file or API summary, downloaded identical bytes after integrity verification, restarted the packaged application and decrypted with the stable installation key, rejected one-bit ciphertext damage with HTTP 409, and retained a valid four-entry audit chain. The machine-readable evidence is `frozen-security-result.json` in that profile.

The authenticated research API closed loop and PDF extraction are covered by the source-environment API tests. The scientific runtime, authenticated planning, recovery and result-manifest path were additionally exercised through the frozen EXE as described above.

## Expected warnings and external paths

- Starlette's TestClient emits one upstream `httpx` deprecation warning.
- The synthetic GenBank fixture intentionally triggers one Biopython malformed-locus warning while exercising normalization.
- The workspace ACL prevents pytest from updating `.pytest_cache`; this does not affect test execution.
- PyInstaller reports optional/platform modules that are not used by the Windows runtime paths. The frozen startup smoke test is authoritative for the packaged startup path.
- Live model, commercial docking, plagiarism-database, and structure-application calls require credentials, network access, binaries, datasets, or licenses that are not part of the repository.
- The P2 host passes deep WSL2 preflight with Ubuntu 24.04, OpenJDK 21, Nextflow 25.10.2, and Docker Engine 29.1.3. Live RNA-seq validation exposed and repaired an NTFS/DrvFs incompatibility: STAR cannot create its FIFO scratch file on `/mnt/g`. The backend now keeps stable compute work in the WSL user's private ext4 home while publishing reports and results to the desktop run directory. The resumed official `nf-core/rnaseq@3.26.0` `test,docker` run (`8c5ca8d6-04af-476a-a1c8-d5b278108d69`) exited zero with 234 trace rows: 191 completed, 43 cached, 0 failed/aborted/retried. The bounded manifest recorded all 1,044 result files (86,994,074 bytes), hashed all of them, and reported no truncation or hash-budget exhaustion. The Nextflow report, timeline, trace, DAG and log were generated; the final MultiQC report is `results/multiqc/star_salmon/multiqc_report.html` (3,840,508 bytes, SHA-256 `109BE0CAD72E2F67EA422BB6E7AEA9594A221DAF5BC51330C630A68F2B414A74`).
- Live NCBI smoke calls succeeded for PubMed (`BRCA1`), SRA (`SRP000001`), GenBank (`NM_007294.4`), and BLAST Put/poll/Get. These are connectivity smokes rather than upstream service availability guarantees.
