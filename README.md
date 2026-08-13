# Research Agent 1.3

Research Agent is a local-first Windows desktop workspace for scientific AI assistance, NCBI research, reusable skills, workflow automation, plugin discovery, and molecular docking integrations.

The desktop build is a native WebView2 window backed by one embedded FastAPI/Uvicorn process. It does not require a separate terminal, browser, or backend process.

## What is included

- First-run owner setup, login, registration, JWT authentication, and role-aware administration.
- Persistent, user-isolated conversations with resumable sessions.
- A dedicated research workspace with explicit DAG planning, evidence provenance, bounded background execution, cancellation, confidence/limitations, and human review gates.
- User-isolated CSV/TSV/text/JSON/PDF/image artifacts with AES-256-GCM encryption at rest, dual integrity checks, bounded extraction, privacy-preserving table profiling, and encrypted visualization artifacts.
- DeepSeek V4, Agnes 2.0 Flash, OpenAI, Anthropic, and Google Gemini providers with encrypted per-user API keys, model health diagnostics, normalized failures, timeouts, and bounded retries.
- A Nature Co-Scientist-inspired discovery loop: evidence grounding, hypothesis generation, reflection, debate/ranking, evolution, meta-review, experiment design, writing, and integrity checks.
- Eighteen built-in research, evidence synthesis, writing, integrity, statistics, visualization, NCBI, docking, and structure skills.
- LangGraph-based specialist-agent orchestration.
- Validated DAG workflows with execution history, progress, ownership checks, and cancellation.
- A scientific capability market with Capability Manifest v1, truthful per-user lifecycle, fixed-version isolated deployment, Bioconda metadata sync/cache, platform probes, reviews, and dependency plans.
- A production pipeline workspace with a uniform execution-backend contract, revision-pinned nf-core/rnaseq 3.26.0 and nf-core/sarek 3.9.0, WSL2 transport, deep runtime preflight, cancellation/resume, Nextflow reports, and bounded result manifests.
- AutoDock Vina, Glide, GOLD, PyMOL, ChimeraX, and Swiss-PdbViewer adapters.
- A responsive Vue 3 desktop interface, dashboard, keyboard shortcuts, system tray, single-instance protection, persistent window state, and browser fallback.
- An administrator security center showing artifact encryption coverage, audit-chain integrity, and explicit migration of legacy plaintext artifacts.

External model calls require the corresponding API key. NCBI features require network access. Docking and structure operations require their separately licensed or installed command-line applications. Production nf-core execution on Windows requires an operational WSL2 distribution with a compatible Nextflow release and selected runtime inside WSL2.

## Run the built desktop application

The verified onedir build is:

```text
dist\ResearchAgent\ResearchAgent.exe
```

Double-click the executable or `start_desktop.bat`. On first launch, create the installation owner in the setup screen, then open **AI 模型配置** to add a model provider key.

Application data is stored under `%APPDATA%\ResearchAgent`:

- `research_agent.db` — users, conversations, workflows, and marketplace state;
- `.runtime_secret` — installation-specific JWT/encryption secret;
- `.enc_salt` and `artifacts\` — installation key salt and encrypted research artifacts;
- `logs\` — rotating diagnostic logs;
- `webview\` — native WebView2 profile;
- `window_state.json` and `config.json` — desktop preferences.

## Run from source

Use a clean Python environment. Python 3.10+ and Node.js are required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .

Set-Location frontend
npm.cmd ci
node .\node_modules\vite\bin\vite.js build
Set-Location ..

$env:PYTHONPATH = "src"
python -m research_agent.desktop_app
```

For frontend development, run `npm.cmd run dev` in `frontend` and start the API with `python -m research_agent.main`.

## Test and build

The latest source baseline and packaged checksum are recorded in the verification report. Run the commands below to reproduce the current result.

```powershell
Set-Location frontend
npm.cmd ci
node .\node_modules\vite\bin\vite.js build
Set-Location ..

python -m pytest -q

.\scripts\build_desktop.ps1
```

`frontend/dist` is intentionally excluded from Git because it is reproducible build output. Build the frontend before running the complete test suite on a fresh clone; source-only backend test selections do not require it.

If build dependencies are missing, use:

```powershell
.\scripts\build_desktop.ps1 -InstallDependencies
```

Add `-CreateInstaller` when Inno Setup's `ISCC.exe` is installed. The build is directory-based because `installer.iss` packages the complete `dist\ResearchAgent` runtime.

## Architecture and operations

- [First-principles review](docs/first_principles_review.md)
- [Architecture](docs/architecture.md)
- [Research runtime and OpenClaw design comparison](docs/research_runtime.md)
- [P2 scientific runtime acceptance](docs/p2_scientific_runtime_acceptance.md)
- [P3 data-security acceptance](docs/p3_data_security_acceptance.md)
- [P4 Co-Scientist/model synchronization acceptance](docs/p4_co_scientist_model_sync_acceptance.md)
- [Bioinformatics third-party integration assessment](docs/third_party_integration_assessment.md)
- [Desktop user guide](docs/user_manual.md)
- [LLM setup](docs/llm_setup.md)
- [Plugin market](docs/plugin_market.md)
- [Docking integration](docs/docking_integration.md)
- [Multi-agent design](docs/multi_agent.md)
- [Test report](docs/test_report.md)
- [Release notes](RELEASE_NOTES.md)

## Project layout

```text
src/research_agent/
  core/             FastAPI app, auth, database, API, schemas
  agents/           agent runtime, LangGraph coordinator, skills
  research/         plans, policies, scheduling, artifacts, evidence, learning proposals
  llm/              direct model providers, encrypted key store, chat
  workflows/        validated DAG execution and cancellation
  execution/        external backend contract, WSL2 Nextflow/nf-core execution and recovery
  plugins/          manifests, lifecycle, trusted catalogs, platform probes, dependencies, isolated deployment
  ncbi_skills/      NCBI integration
  desktop_app.py    native single-process desktop lifecycle
frontend/           Vue 3 desktop interface
tests/              unit, API, security, isolation, and lifecycle tests
scripts/            source launcher and reproducible Windows build
```

## Safety boundary

The desktop API binds to `127.0.0.1` only. Static UI and setup/login routes are public to the local window; application APIs require a valid bearer token. Data reads and mutations are scoped to the authenticated user where state is personal. Global marketplace metadata changes require the `admin` role.

Plugin catalog entries are discovery metadata, not installed software. Selection, deployment, verification and enablement are separate user-scoped states. A workflow must use a registered skill or a plugin with a validated executor adapter; otherwise execution fails explicitly instead of reporting a false success.

Scientific outputs are decision support. Literature results expose source locators and gaps; experimental-design and integrity steps require human review. Feedback never silently edits a live skill: it creates a pending proposal that the user must apply, reject, or quarantine.
