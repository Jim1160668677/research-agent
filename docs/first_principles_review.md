# First-principles review and remediation record

## Fundamental user job

A researcher needs one dependable workspace in which they can ask questions, resume prior work, run validated scientific tools, organize repeatable workflows, and understand when an external dependency is missing. They should not need to reason about ports, backend processes, JWT plumbing, database initialization, or packaging layout.

That job yields four non-negotiable product properties: launchability, truthful execution, durable private state, and recoverable failure.

## Root-cause analysis

| Observed failure | Root cause | Implemented correction | Verification |
|---|---|---|---|
| Frozen desktop could not start its backend | It treated the frozen EXE as a Python interpreter | Embedded Uvicorn on a reserved loopback socket in one managed process | Packaged EXE health/UI smoke test |
| Production startup failed or used an unsafe secret | Desktop did not provision production security configuration | Stable random per-installation secret created before API imports | Fresh-profile EXE created secret and database |
| Protected APIs failed from the Vue app | Desktop and Vue held unrelated token state; requests lacked authorization | One persistent session module and Axios interceptors | Auth/API integration tests |
| The production UI itself returned 401 | Middleware protected `/` and static assets | Public bootstrap/static boundary; protected versioned APIs | Real-mode static-public/API-private test |
| First launch had no usable credentials | A random admin password was printed to a hidden console | Explicit first-run owner setup returning an authenticated session | Setup/idempotency tests and setup UI |
| App construction performed database I/O | Sync/event-loop work happened in the factory | Database init/seed/dispose moved to FastAPI lifespan | Isolated TestClient lifecycle tests |
| Chat history duplicated and every turn created a session | Persistence appended the same exchange twice and identity/session IDs were not propagated | One exchange append, resumable session ID, user-scoped CRUD | Exact message-count and isolation tests |
| Workflow list/run appeared empty or failed | New workflows lost their author and stayed incompatible with list/run rules | Authenticated owner, active status, DAG validation, run ownership/cancellation | Workflow API and cancellation tests |
| Plugin state leaked across users | Install/version state was stored on the global catalog record | Per-user installation/version/update/upgrade state | Two-user isolation test |
| Plugin workflow nodes reported success without executing | Placeholder implementation returned a success-shaped object | Explicit unsupported-executor failure | Workflow behavior and source review |
| Dashboard showed invented values | Frontend used static numbers | User-scoped `/system/overview` metrics and activity | Production API smoke and UI build |
| Packaging and installer disagreed | PyInstaller used onefile while Inno expected an onedir tree; spec paths were wrong | One onedir contract, corrected `SPECPATH`, package entry point, bundled SPA | Real PyInstaller build |
| Build depended on accidental Conda contents | Broad submodule collection pulled multiple Qt bindings and PyTorch/OpenMP | Windows-only WebView imports and explicit non-dependency exclusions | Clean successful build after reproduced failures |
| Gemini provider imported a removed SDK namespace | Dependency and implementation targeted `google.generativeai` while current environment supplies `google.genai` | Direct async `google.genai` client and updated dependency | Provider adapter test |
| “Multi-agent” reduced a complex request to one keyword branch | The graph routed once and had no explicit plan, dependencies, policy, budget or validation loop | Persistent research DAG, deny-unlisted capability policy, bounded scheduler and human review gates | Planner/policy/runtime tests |
| Literature and experimental design returned success-shaped placeholders | Skills did not require source content or a scientific output contract | Evidence records with locators/gaps; estimand, bias, sample-size, QC and ethics contract | Evidence/design tests |
| Agent work had no artifact or multimodal boundary | Attachments were not represented in the domain model | User-scoped hashed artifacts, bounded PDF/table/image intake, explicit degradation | Upload/path/profile tests |
| “Learning” had no governed lifecycle | User preferences had no evidence or review semantics | Feedback-backed pending proposals with apply/reject/quarantine; no live skill edits | Learning API lifecycle test |

| NCBI endpoints returned empty or protocol-shaped data | ESearch was parsed as XML despite requesting JSON; SRA fetched records one by one; BLAST used an invalid service flow | One rate-limited/retrying adapter with JSON ESearch, batched XML EFetch, GenBank normalization/conversion, and official BLAST Put/poll/Get | Seven protocol tests plus live PubMed, SRA, GenBank, and BLAST smoke calls |
| Recommendations could leak or invent capabilities | History lacked a user boundary and candidates were static labels rather than registered capabilities | User-scoped recommendations and feedback, with candidates drawn only from the skill registry, plugin catalog, and visible workflows | API candidate, history, isolation, and feedback tests |
| Workflow runs were difficult to compose or stop reliably | References were string-only, unknown node types were tolerated, and cancellation was local to one engine object | Typed recursive references, strict node validation, concurrent DAG generations, retry/timeout policy, shared cancellation and interruption of active nodes | Workflow API, typed-reference, failure, and cross-engine cancellation tests |
| Plugin deployment could mutate shared environments | Catalog strings became shell-like commands and conda targeted a shared environment; real deployment had no role boundary | Typed deploy requests, admin-only execution/verification, argv-only subprocesses, validated specs/channels, per-plugin conda prefixes or Python virtual environments, timeout tree termination and rollback | Deployment-plan, injection, RBAC, history, and invalid-version tests |
| Marketplace selection falsely implied installation | Discovery, user intent, physical deployment and verification shared one boolean-like state | Capability Manifest v1 plus an append-only user lifecycle; simulation never advances state and dashboard counts only the current state | Manifest/lifecycle/API/user-isolation tests |
| Third-party discovery had no trusted synchronization boundary | Catalog growth depended on static seed data or would require arbitrary install URLs | Fixed-host Bioconda repodata adapter with package/subdir allowlists, atomic DB import, ETag cache, source digest and admin-only sync | Fresh/cache/failure/injection integration tests |
| Windows could not explain Linux-only execution limits | Availability was inferred only while building an install plan | Read-only host inventory for Conda, containers, WSL2 and workflow engines, with explicit backend and limitation reporting | Platform structure and UTF-16 WSL tests |

## Product enhancements delivered

- Native first-run/login experience and coherent desktop shell.
- Persistent conversation sidebar, resume/delete actions, typing/error states, and keyboard focus shortcut.
- Real dashboard metrics, readiness state, and recent activity.
- Workflow edit routing, persisted author/status, validation, history, and cancellation.
- User-scoped encrypted model configuration and three direct provider adapters.
- User-scoped plugin install/version behavior and admin-only catalog mutation.
- Static traversal protection, cache policy, security headers, request IDs, and normalized validation errors.
- Atomic configuration/state writes, rotating logs, stable per-user paths, single-instance discovery, and deterministic server shutdown.
- Reproducible Vue build, PyInstaller onedir build, and Inno Setup alignment.
- Dedicated research workspace for plan preview, artifacts, background execution, evidence, gaps, cancellation and feedback.
- PubMed batch retrieval, bounded local data profiling, evidence-constrained writing and academic/ethics preflight.
- Capability Manifest v1, truthful plugin states, Bioconda metadata synchronization, runtime capability panel, and safely removable managed environments.

## Deliberate boundaries

- OpenAI, Anthropic, and Gemini calls still require network access and user credentials. Their local adapters, schemas, key isolation, and mocked call shapes are tested.
- NCBI PubMed, SRA, GenBank, and BLAST were smoke-tested against the live services on 2026-08-12. An NCBI API key remains recommended for sustained production throughput, and upstream availability is outside the desktop application's control.
- AutoDock Vina, Glide, GOLD, PyMOL, ChimeraX, and Swiss-PdbViewer require separately installed software (and licenses where applicable). The app detects and reports their availability.
- Plugin catalog metadata is not arbitrary executable code. Manifest v1 now defines identity, runtime, permissions, resources and provenance, but a plugin still needs a reviewed executor adapter before workflow execution is enabled.
- Production distribution should add code signing and CI builds in a clean pinned environment. The local unsigned EXE has been built and smoke-tested.

## Validation evidence

- Full Python suite: see `docs/test_report.md`.
- Vue 3 production build: succeeds and emits hashed JS/CSS assets.
- PyInstaller: onedir build succeeds and includes the SPA under `_internal/frontend/dist`.
- Frozen EXE fresh-profile smoke: the rebuilt executable published an ephemeral loopback port; `/health` returned `healthy`; `/` returned 200 with the Vue mount; and auth status reported an uninitialized fresh profile as expected.
- P1 frozen smoke additionally verified the authenticated pinned nf-core catalog and truthful WSL2 capability state. Full nf-core golden-data execution remains conditional on an external WSL2/container/reference-data environment and is not represented as completed on this machine.
