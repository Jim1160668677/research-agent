# Research Agent architecture

## Design invariants

The architecture is derived from five requirements:

1. A desktop user must be able to install and launch one application without managing a server.
2. Scientific work, keys, and histories must survive restarts and remain isolated by user.
3. The interface must never claim that an operation succeeded when no operation ran.
4. A frozen executable must use only packaged resources and per-user writable storage.
5. Startup, shutdown, validation, and error behavior must be testable outside the GUI.

## Runtime shape

```text
ResearchAgent.exe
  ├─ DesktopApp lifecycle
  │   ├─ per-user environment and stable installation secret
  │   ├─ atomic single-instance lock and window state
  │   ├─ WebView2 window and optional system tray
  │   └─ deterministic shutdown
  └─ BackendManager thread
      └─ FastAPI + Uvicorn on a reserved 127.0.0.1 socket
          ├─ authentication and request tracing middleware
          ├─ versioned REST API
          ├─ Vue production assets
          └─ SQLAlchemy async sessions → per-user SQLite database
```

Uvicorn is embedded in a managed thread. A frozen PyInstaller executable is not a Python interpreter, so the previous `sys.executable -m uvicorn` subprocess design recursively relaunched the desktop executable. The one-process design removes that invalid boundary and makes shutdown deterministic.

## Application boundaries

| Boundary | Responsibility |
|---|---|
| `desktop_app.py` | Native lifecycle, resource discovery, loopback socket, WebView/tray, single instance, user storage |
| `core/app.py` | FastAPI factory, lifespan-owned database initialization, middleware, exception envelopes, SPA serving |
| `core/auth.py` and `core/api/auth.py` | JWT verification, first-run setup, user identity, role checks |
| `core/db.py` | Async engine/session ownership, test/profile rebinding, migrations, seeding, disposal |
| `agents/` and `llm/` | Lightweight chat routing, direct provider SDKs, conversation persistence, skills |
| `research/` | Explainable planning, capability policy, bounded scheduling, artifact processing, evidence and controlled learning |
| `workflows/` | DAG validation, ownership, execution records, progress, cancellation |
| `execution/` | External backend contract, Nextflow/nf-core planning, WSL2 transport, subprocess lifecycle, trace and artifact manifests |
| `plugins/` | Global catalog metadata plus per-user installation/version state |
| `frontend/src/state/session.js` | The single browser-side authentication state and Axios authorization boundary |

## Startup sequence

1. Resolve `%APPDATA%\ResearchAgent` and atomically create/reuse `.runtime_secret`.
2. Set database, JWT, crypto, desktop, and debug environment values before importing the API.
3. Acquire the PID/port lock. A second launch discovers the existing instance instead of creating another database/server.
4. Reserve a loopback socket and start Uvicorn in a managed thread.
5. FastAPI lifespan creates/migrates tables, seeds the plugin catalog, and initializes services.
6. Poll `/health`, publish the selected port in the lock, and create the WebView2 window.
7. On exit, stop the tray, request Uvicorn shutdown, join the backend thread, dispose database engines, save window state, and release the lock.

## Trust and data model

- The desktop server is loopback-only. Non-loopback host configuration is rejected.
- `/`, hashed assets, `/health`, setup, login, and registration are the only public desktop paths required to bootstrap the UI.
- Protected APIs require a signed access token. The Vue Axios interceptor is the only source of the browser authorization header.
- The first setup account is `admin`; later accounts are `researcher` unless changed by an administrative migration.
- Conversations, workflow definitions/runs, API keys, reviews, and plugin installation/version state carry the authenticated user identity.
- Marketplace definitions and version publications are global; global mutations require `admin`.
- API keys are encrypted using installation-specific material and are never returned unmasked.
- Research artifacts use a versioned AES-256-GCM envelope with installation-derived,
  domain-separated key material. The database stores plaintext and ciphertext SHA-256
  values but no raw-data previews; encrypted files are materialized only into bounded,
  short-lived paths for analysis or external execution and are deleted afterward.
- Sensitive artifact upload, download, and migration events are committed through an
  HMAC-SHA-256 hash chain. The admin security view verifies modified, reordered, or
  internally deleted rows; detecting tail truncation still requires an external signed
  or WORM anchor.
- Static file paths are resolved under the bundled frontend root and reject traversal.

## Work execution semantics

Built-in skills define an executable contract and can be used directly or in workflows. Workflow definitions are rejected when nodes are unnamed/duplicated, edges reference unknown nodes, or the graph contains a cycle. Runs persist progress and results and can be cancelled between nodes.

Marketplace entries primarily describe discovery, installation, and version metadata. A plugin workflow node without a validated executable adapter raises an explicit error. This prevents the former false-positive behavior that returned “executed” without running anything.

The research runtime is the primary path for multi-stage scientific work. It persists a validated DAG before execution, filters capabilities through a deny-unlisted/network/approval policy, runs dependency-ready steps under global and per-run concurrency limits, and records step-level confidence, warnings, evidence and timing. Runs execute outside the request lifecycle and can be cancelled. Artifacts are stored under a user-scoped root and API responses never expose physical paths.

Learning is proposal-only: explicit feedback may create a pending planning preference. Only a user decision applies it, and applied text remains an ordinary content constraint—it cannot add tools, enable network access or change policy.

## Production pipeline execution

Long-running bioinformatics pipelines use a separate persistent state machine. `ExecutionBackend` standardizes plans and results across future engines. The first backend pins nf-core/rnaseq 3.26.0 and nf-core/sarek 3.9.0, rejects unknown parameters, validates pinned samplesheet schemas, applies CPU/memory limits, and performs a deep Nextflow/runtime/disk preflight.

On Windows, execution crosses into WSL2 through an argv-only launcher and converts only managed Windows paths to `/mnt/...`; user text is never evaluated as shell code. Reports, published results and audit controls remain in the desktop data directory, while the Nextflow computation/work directory lives under the WSL user's private ext4 home. This split is required by tools such as STAR that create Linux FIFOs, which NTFS/DrvFs cannot provide. The resolved work path is recorded for recovery but redacted from public plans and log tails. A fixed runner owns a Linux process group so cancel, timeout, and desktop shutdown terminate the complete tree.

Pipeline records distinguish planned, queued, running, cancelling, terminal, and interrupted states. Unclean-start recovery marks orphaned work interrupted; explicit resume reuses the stable per-run ext4 work directory with Nextflow `-resume`. Reports, timeline, trace, DAG, logs, and a bounded result manifest are recorded with hashes where budget permits. API plans and log tails redact physical paths, while authenticated downloads resolve under the owning user's run root.

## Packaging

`ResearchAgent.spec` builds an onedir distribution and bundles `frontend/dist`. Only Windows pywebview backends are collected; mutually exclusive Qt/GTK/macOS backends and unrelated packages accidentally present in broad Conda environments are excluded. The Inno Setup definition consumes the same onedir tree.

Use a clean virtual environment for releases. The checked-in specification is defensive against environment pollution, but a clean environment gives a smaller and faster build.

## Error and observability model

- Validation errors and unhandled exceptions produce consistent JSON responses with request identifiers.
- Security headers are applied to API and SPA responses.
- Backend startup has a bounded health timeout and reports failures to rotating logs.
- Missing external binaries, invalid model keys, unsupported plugin execution, and workflow node failures are surfaced as errors rather than synthetic success.
- Logs rotate at 10 MB and retain seven days by default.
