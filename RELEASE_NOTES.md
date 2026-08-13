# Unreleased recovery hardening

- Restored the complete local frontend dependencies, production assets, desktop build and distributable without modifying user data or model configuration.
- Added a formal pipeline preparation stage with pinned nf-core commit verification, Windows-side prefetch, LF-only worktrees, long-path support, per-file Git blob verification, atomic activation and recoverable backup behavior.
- Verified 259 source tests, packaged security and nine-stage research flows, deep WSL2/Nextflow/Docker readiness, and a complete 234-task `nf-core/rnaseq@3.26.0` run with zero failures.
- Preserved the prior distributables at `dist-pre-sync-backup-20260814` and `dist-restored-backup-20260814`; GitHub publication remains paused pending user confirmation.

See `docs/recovery_and_full_function_acceptance_20260814.md` for exact checksums, test cases, root causes and external prerequisites.

---

# Research Agent 1.3.0 release notes

Release date: 2026-08-13

## 1.3.0 — Co-Scientist discovery loop and reliable model synchronization

- Added current DeepSeek V4 Pro/Flash support through the official OpenAI-compatible contract, with explicit timeouts, bounded jittered retry, thinking parameters, normalized errors, health checks and latency/attempt telemetry.
- Added Agnes 2.0 Flash through the required CLI-first integration, including Node/CLI version diagnostics, argv-only subprocess execution, Windows `npx.cmd` compatibility, JSON validation and a real live smoke script.
- Added the persistent evidence → generation → reflection → ranking/debate → evolution → meta-review → experiment → writing → integrity scientific discovery loop inspired by the Nature Co-Scientist architecture.
- Added a process-wide runtime coordinator shared by model calls, research capabilities, workflow nodes and external execution, plus an authenticated runtime snapshot API.
- Added restart recovery for orphaned research and workflow runs and surfaced the `interrupted` state in the desktop UI.
- Unified per-user provider/model preferences across direct chat, ResearchAgent and LangGraph Coordinator; unconfigured providers cannot be selected as defaults.
- Rebuilt the model configuration desktop view around truthful local/live diagnostics and all five providers.
- Added ten model/synchronization/complete-flow tests, a real Agnes smoke, two benchmark scripts and a packaged P4 acceptance runner.

Acceptance: 256/256 Python tests passed; the production Vue build passed; Agnes live returned `pong` in one attempt from both source and the packaged EXE. The final executable SHA-256 is `9157021846D58ADD5F853C55DCE2166A1069111BCBD89A09013EA2CA5495F8A4`. DeepSeek live was not run because no credential was configured. Full evidence is in `docs/p4_co_scientist_model_sync_acceptance.md`.

---

# Research Agent 1.2.0 release notes

Release date: 2026-08-11

## Desktop release

Version 1.2.0 adds an evidence-first scientific task runtime on top of the repaired 1.1 desktop baseline. Multi-stage research work now has an explicit plan, capability policy, resource budget, persisted step history, source provenance, cancellation and human review gates.

The verified Windows onedir output is `dist\ResearchAgent\ResearchAgent.exe`. A clean-profile smoke test confirmed backend health, first-run auth status, SPA delivery, local database/secret creation, native WebView initialization, tray startup, and single-instance protection.

## User-facing improvements

- New **科研工作台** for objective definition, capability selection, material upload, plan preview, background execution and step-level results.
- Literature evidence tables, experimental-design contracts, table quality reports/preview plots, evidence-constrained writing and academic/ethics preflight.
- Explicit confidence, limitations, evidence gaps and review requirements instead of success-shaped placeholders.
- Feedback-backed learning proposals that require apply/reject/quarantine review.

- First-run owner setup, login, registration, and logout in the desktop window.
- Modern responsive shell, real dashboard, persistent chat sidebar, resume/delete actions, and keyboard shortcuts.
- User-isolated conversations, workflows, model keys, reviews, and plugin installation/version state.
- Workflow create/edit/run/history/cancel flow with DAG validation and truthful execution errors.
- OpenAI, Anthropic, and current Google Gen AI provider adapters.
- User-scoped plugin updates/upgrades and administrator-only catalog metadata/version publication.
- Clear external dependency and connectivity errors rather than placeholder success.
- Correct NCBI PubMed/SRA/GenBank/BLAST protocols with bounded rate limiting, retries, batching, structured records, and sequence format conversion.
- Recommendation results restricted to real registered skills, plugins, and visible workflows, with user-isolated history and explicit feedback.
- Typed workflow references, strict node contracts, bounded parallel branches, retry/timeout handling, and cancellation that interrupts active work across API engine instances.
- Admin-gated real plugin deployment into per-plugin conda prefixes or Python virtual environments using validated argument arrays instead of a command shell.
- Capability Manifest v1 with strict validation, canonical SHA-256 digests, fixed package versions, permissions, resources, and catalog provenance.
- Truthful per-user plugin lifecycle separating discovery, selection, deployment, verification, enablement, disablement, failure, and removal.
- Admin-only, read-only Bioconda catalog synchronization from fixed HTTPS repodata endpoints with ETag cache, atomic rollback, source digests, and no implicit installation.
- Desktop runtime-capability panel for Conda, containers, WSL2, Nextflow and Snakemake, plus bounded deletion of managed plugin environments.

## Reliability and security

- New research artifacts are encrypted at rest with a versioned AES-256-GCM envelope;
  plaintext/ciphertext SHA-256 and authenticated metadata detect data or record changes.
- Artifact inspection no longer persists raw text previews, column names, or sample values;
  external tools receive verified temporary plaintext only for the execution lifetime.
- Authenticated, user-scoped downloads verify integrity before returning bytes. An explicit
  migration flow upgrades legacy plaintext artifacts and removes the old file after commit.
- Upload, download, migration, and pipeline control events use a keyed audit hash chain;
  administrators can verify the chain and encryption coverage from the desktop security page.
- Stable installation-specific JWT/encryption secret; no hard-coded production fallback.
- Loopback-only embedded server, public bootstrap/static boundary, and protected application APIs.
- Unified Axios bearer-token path and automatic expired-session handling.
- FastAPI lifespan owns database initialization and disposal.
- Consistent validation/error responses, request identifiers, security headers, static traversal defense, and cache policy.
- Atomic state/config writes, PID/port single-instance record, bounded startup health polling, rotating logs, and deterministic backend shutdown.

## Packaging

- PyInstaller and Inno Setup now share an onedir contract.
- Fixed `SPECPATH`, package-context entry point, frozen resource lookup, and frontend asset collection.
- Windows-only WebView backend collection avoids incompatible Qt bindings.
- Removed unused LangChain provider wrappers and migrated Gemini from `google.generativeai` to `google.genai`.
- Build scripts do not install packages at application runtime.

## Compatibility notes

- Existing SQLite databases receive the lightweight `users.role` migration on startup.
- Existing generated-admin/bootstrap endpoints remain for compatibility, but the desktop UI uses explicit owner setup.
- API keys remain tied to the installation secret. Back up the entire `%APPDATA%\ResearchAgent` directory, not the database alone.
- Legacy plugin rows marked `installed` are migrated to `selected` unless they contain a recorded environment prefix; only the latter migrate to `deployed`.

## External requirements

Real model calls need network access and valid credentials. NCBI access needs network connectivity; an API key and contact email are recommended for sustained throughput. Docking and structure operations need the corresponding external binaries and licenses. The generated Windows executable is unsigned; production distribution should add organization code signing.

## P2 scientific runtime hardening

- Fixed Nextflow probes and executions to `25.10.2` and added a no-input
  nf-core/rnaseq `test,docker` acceptance mode.
- Moved CPU/memory controls out of invalid nf-core parameters into a run-scoped
  Nextflow configuration with a local executor pool, per-task resource caps,
  and a single execution slot that prevents aggregate budget overlap.
- Added attempt-numbered report/trace archival with SHA-256 manifests before
  resume, preventing stale traces from contaminating current task status.
- Added fixed-commit acceptance manifests for unstable GitHub Raw test-data
  routes, including provenance hashes for generated samplesheet and BBSplit
  inputs.
- Split Windows execution storage so Linux compute work runs on private WSL
  ext4 while reports and published results remain accessible to the desktop;
  this fixes STAR FIFO failures on NTFS/DrvFs without weakening isolation.
- Added a frozen-package acceptance script covering clean-profile startup,
  first-owner setup, bearer authentication, deep Nextflow/Docker capability
  probing, persisted pipeline planning, physical-path redaction, resolved
  executor limits, observed concurrency, report presence and SHA-256 evidence.
- Completed the official nf-core/rnaseq 3.26.0 `test,docker` golden run with
  exit code zero: 191 completed tasks, 43 cache hits, no failures or retries,
  complete reports, MultiQC output and a 1,044-file hashed result manifest.
- Replayed the official RNA-seq flow through the frozen EXE with 234 successful
  tasks, strict 4 CPU / 7 GB / one-slot scheduling, complete result manifest,
  and hashed Nextflow/MultiQC reports.
- Added a repeatable backend validation command and expanded the baseline to
  241 passing Python tests plus the Vue production build.
