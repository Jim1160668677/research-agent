# Research Agent desktop guide

## Install and launch

Research Agent supports Windows 10/11 x64. The packaged application includes Python, the API, and the built interface; Python and Node.js are only required for source development.

Run `ResearchAgent.exe` from the installed folder or from `dist\ResearchAgent`. `start_desktop.bat` launches the packaged version when present and otherwise validates the source environment.

The application opens a native WebView2 window. If WebView is unavailable, it opens the same local interface in the default browser. Only one instance runs per Windows profile.

## First launch

1. Enter an owner username, email, and password of at least eight characters.
2. The owner is signed in as the local administrator. This replaces the old hidden-console temporary password flow.
3. Open **AI 模型配置**, choose OpenAI, Anthropic, or Google, and save an API key.
4. Open **智能对话** to start a conversation. Without a valid model key, the assistant uses its local tool/rule fallback and clearly indicates the limitation.

Additional accounts can be created from the login screen. Their conversations, workflows, keys, reviews, and plugin installation versions are isolated from the owner and from one another.

## Main areas

- **工作台** — real counts, model readiness, recent sessions/runs, and quick actions.
- **科研工作台** — define a research objective, choose capabilities, upload materials, preview the execution DAG, start/cancel a background run, inspect evidence and review learning proposals.
- **智能对话** — persistent multi-turn sessions; select a session to resume it or delete it from the sidebar.
- **技能中心** — browse and execute registered scientific skills.
- **工作流** — create/edit validated DAGs, run them, inspect history, and cancel active work.
- **插件市场** — discover tools, inspect versions/dependencies/reviews, install a personal version, and verify external software.
- **NCBI** — PubMed, SRA, GenBank, BLAST, Gene, and Entrez operations (network required).
- **分子对接/结构工具** — use detected external docking and visualization applications.
- **AI 模型配置** — save, replace, test, or delete encrypted per-user keys.

Use `Ctrl+K` to focus the chat input and `Ctrl+N` to start a new chat where those shortcuts are displayed.

## Production pipelines

1. Open **生产流程** and choose nf-core/rnaseq 3.26.0 or nf-core/sarek 3.9.0. The revision is fixed by the allowlist and cannot be replaced with `latest`.
2. Upload or select a CSV samplesheet. RNA-seq requires the first four columns `sample,fastq_1,fastq_2,strandedness`; Sarek requires patient/sample plus a supported FASTQ, BAM, CRAM, or VCF input. The pinned input contract is validated before compute is allocated.
3. Select a runtime and optional managed reference artifacts. Unknown parameters are rejected. The adapter applies 8 CPUs and 32 GB memory by default; execution time is capped at 1–168 hours.
4. **保存并审阅计划** works even when Nextflow is absent. **预检并启动** requires an administrator and checks WSL2, minimum Nextflow version, selected runtime, free disk, and offline cache.
5. **取消** terminates the Linux process group. Failed, cancelled, or application-interrupted work can be explicitly resumed from the same Nextflow cache.
6. Completed runs expose trace status counts and downloadable report, timeline, DAG, logs, and a bounded result manifest. Physical paths are redacted from API data and log tails.

The desktop EXE does not bundle Nextflow, Java, container images, references, or nf-core pipelines. Install them in a trusted WSL2 environment. A saved plan is not evidence that execution prerequisites are ready.

## Research workspace

1. Describe the research object, intervention/exposure, comparison and desired outcome as concretely as possible.
2. Select literature, experimental design, data analysis, writing and/or integrity capabilities. Attaching a file automatically adds the multimodal intake step.
3. Add CSV/TSV, text, JSON, PDF or image materials. The app preserves the original, records SHA-256 and performs bounded extraction; it does not guess image semantics without a vision model.
4. Use **Preview plan** to inspect dependencies, resource units and human review gates. Disable network access when the run must remain offline; PubMed will then be explicitly blocked rather than silently attempted.
5. Start the task and inspect each step's state, confidence, warnings and output. A completed run may still contain evidence gaps.
6. Submit feedback after human review. A correction produces a pending proposal; it changes later planning only after you choose **Apply**.

The integrity checker is a preflight, not a plagiarism database, ethics committee or statistical sign-off. Experimental protocols and factual manuscript claims must be reviewed by qualified people.

## Workflows and plugins

Workflow nodes must have unique names and form an acyclic graph. Edges to unknown nodes and cyclic definitions are rejected before saving. Skill nodes execute registered contracts and persist progress/results.

Adding a marketplace item records a `selected` tool/version for the current user; it does not install software. The plugin view shows the complete lifecycle (`selected`, `deployed`, `verified`, `enabled`) and the capability source/Manifest digest. Generate a dry-run plan before deployment. Actual deployment, deep platform probes, verification, Bioconda synchronization, and managed-environment removal require an administrator.

Bioconda synchronization imports metadata only from the fixed official HTTPS index for explicitly named packages. It never selects or installs those packages. On Windows, consult the execution-capability panel: Linux-only packages require a configured WSL2, container, or remote execution backend.

A plugin workflow node still needs a validated executor adapter; otherwise the run fails with an actionable error.

Real deployment can invoke package managers or external installers. Review the generated dry-run plan first and use a trusted environment. Some tools require commercial licenses.

## Storage and logs

All writable state is under `%APPDATA%\ResearchAgent`. Back up that directory to preserve local users, conversations, workflows, encrypted model configuration, and preferences.

Do not share `.runtime_secret`. Restoring the database without the matching secret can make encrypted provider keys unreadable.

Diagnostics are in `%APPDATA%\ResearchAgent\logs`. Logs rotate automatically. When startup fails, check the newest `research_agent_YYYYMMDD.log` entry.

## Troubleshooting

**The window does not appear**

Check the system tray and logs. A second launch reuses the existing instance. Install the Microsoft Edge WebView2 runtime if the native renderer is unavailable; the browser fallback remains usable.

**Model chat fails**

Confirm the correct provider/key and network access. The provider error is shown in the chat/API response; keys are masked in the UI.

**NCBI fails**

Check internet access and NCBI service limits. Retry transient failures; large operations may take longer than local skills.

**Docking or structure tool is unavailable**

Install the external application, ensure its executable is on `PATH` or configured, then run installation verification in the plugin/tool view.

**Resetting a local installation**

Close Research Agent, back up `%APPDATA%\ResearchAgent`, and move that directory to a safe archive name. On the next launch the app creates a fresh profile. Deleting the directory is irreversible and also removes conversations and encrypted keys.

## Build from source

See the root `README.md`. The release command is `scripts\build_desktop.ps1`; pass `-InstallDependencies` for a new environment and `-CreateInstaller` only when Inno Setup is available.
