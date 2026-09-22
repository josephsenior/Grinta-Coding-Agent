# Changelog

All notable changes to Grinta will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **The browser tool works again, with no new dependency.** It now speaks the
  Chrome DevTools Protocol directly over `websockets` (already a Grinta
  dependency) and drives whichever Chromium-family browser is installed —
  Chrome, Edge, Chromium or Brave — so there is nothing to `pip install` and no
  bundled browser to download. `GRINTA_BROWSER_BINARY` overrides discovery. The
  tool is hidden when no such browser is found, replacing the old gate on the
  `browser_use` package (`is_browser_extra_available` is now
  `is_browser_available`). All 17 subcommands are covered end to end against a
  real browser in `backend/tests/integration/test_cdp_browser_integration.py`.

  The element index the agent clicks is produced by a page-side serializer that
  stores nodes on `window.__grinta_els`, so indices survive without any CDP node
  bookkeeping. It walks shadow DOM and same-origin iframes (translating click
  coordinates through the frame chain) and reports cross-origin frames as a
  single entry pointing at their `src`. Only in-viewport elements are indexed;
  the tool description now tells the agent to scroll and re-snapshot.

- **Repository launch surface:** a compact README hero, animated recovery
  preview, capability table, contributor call, and direct links to the
  strongest autonomous-run evidence.
- **Public showcase:** standardized case studies for the 4h 33m autonomous
  session, failure recovery, issue-tracker build, and Raft key-value store.
- **Shareable media:** a 1280 × 640 social-preview asset and a compressed,
  looping WebP excerpt that links to the full demo.

### Changed

- **Package discovery metadata:** expanded the package description, keywords,
  classifiers, and project URLs for package-index searchability.
- **Citation metadata:** credits maintainer Youssef Mejdi and records the
  public repository URL.
- **Dependency resolution restored:** the committed `uv.lock` was stale
  (missing `shadowgit`, pinned pre-bump `rich`/`requests`) and could not be
  regenerated while the `[browser]` extra was declared — `browser-use`
  0.13.x pins its entire transitive tree (`openai==2.16.0`, `mcp==1.26.0`,
  `rich==14.3.1`, `requests==2.33.0`, `aiohttp==3.13.4`, ...), which
  conflicts with Grinta's modern dependency floor and made `uv lock` /
  `uv run` fail for every contributor. Removed the extra so the lockfile
  resolves again; the adapter stays dormant and the extra can return when
  browser-use adopts sane pinning.

### Removed

- **`[rag]` and `[all]` extras removed; `search_history` is now on for every
  install.** The ChromaDB + fastembed semantic backend and the optional
  flashrank re-ranker are gone. History search is keyword (BM25) search on
  SQLite FTS5 from the standard library, which previously ran alongside the
  semantic backend but was only reachable when `chromadb` was installed — so
  base installs had no `search_history` at all. Agent history queries are
  mostly identifiers, file paths and error text, where keyword matching is
  strong; the embedding stack cost ~40 MB of wheels, a first-run model
  download and 28+ transitive packages. Recall stays scoped to the current
  session, as before. `enable_vector_memory` keeps its name and still toggles
  the feature (default on). `enable_hybrid_retrieval` is removed; existing
  settings files that set it still load, with a warning. `VectorBackend`
  remains a pluggable interface (`EnhancedVectorStore(backend=...)`) for
  experimenting with other retrieval strategies. The regenerated `uv.lock`
  also picks up pin bumps that recent dependency updates had left unlocked.

- **`[browser]` optional extra removed** (and with it `browser-use` from
  `[all]`). The adapter code in `backend/execution/browser/` remains with
  lazy imports and a clear runtime error; see the `Changed` entry above for
  the reasoning.

- **`read_symbol` tool removed after a brief trial.** Targeted discovery remains
  in `find_symbols`; file content is read through `read_file`. Removing the
  dedicated tool keeps the final public file surface at six tools.

- **`edit_symbol` tool removed.** The model was not using it; the schema
  was complex (six optional disambiguation fields plus `new_content`),
  and `replace_string` covers the same ground with a simpler schema the
  model already uses confidently. Symbol discovery stays in `find_symbols`;
  content reads stay in `read_file`.
- **`create(type="symbol")` mode removed.** `create` is now file-only.
  Insert new symbols via `replace_string` with an anchor line.
- **`multiedit` `edit_symbol` command removed.** `multiedit` now
  supports `replace_string` operations only. The `allOf`/`if-then`
  conditional schema is gone; the operation shape is just
  `path`, `old_string`, `new_string`, `replace_all`.

### Fixed

- **CI was red across several independent causes: two dead CI shard paths,
  a compositor-stall bug in headless Chrome, and unreliable CDP timing on
  GitHub's macOS runners.** `backend/tests/unit/test_start_server.py` and
  `backend/tests/unit/knowledge` no longer exist but were still hardcoded
  into two Linux shard commands in `py-tests.yml`, failing with "file or
  directory not found"; removed. `--headless=new` shares headed Chrome's
  compositor path, which can stall `Runtime.evaluate`/`Page.captureScreenshot`
  indefinitely with no real frame to wait on; switched the CDP engine to
  classic `--headless`. Raised the engine's per-call timeouts
  (`evaluate`/`snapshot_text`/`page_text` 30s → 45s, `screenshot` now exposes
  its own 40s budget) and `BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC` (40s → 100s)
  so an outer wrapper can never cut off two sequential inner calls that are
  still genuinely progressing. None of that fully stabilized the CDP browser
  integration suite on GitHub's macOS runners specifically: Chrome-over-CDP
  is measurably slower/less predictable there than on Linux, Windows, or any
  local machine tested, evaluate calls stall well past generous budgets even
  fully isolated from other load, and the suite is fully verified correct by
  this same file on the Linux and Windows extended gates (hard requirements)
  plus local runs. The macOS extended gate now runs it best-effort
  (`continue-on-error`, capped at 15 minutes) rather than blocking CI on a
  runner-performance issue Linux and Windows don't share.
- **CI was red: `from mcp import McpError` no longer matches the resolved
  `mcp` package.** `pyproject.toml` pins `mcp>=2.2.0,<3`; that SDK renamed the
  exception to `MCPError` with no backward-compatible alias, breaking mypy,
  every test that imports `backend.integrations.mcp.client` or `.mcp_utils`
  transitively, and a real wheel install (`Smoke Install`, `CLI Regression
  Tests`). Fixed in both modules; verified against a wheel built from source
  and installed into a clean venv with the CI-resolved `mcp==2.2.0`, running
  the same stub CLI task Smoke Install runs. Also applied the
  `pyproject-fmt`/`ruff format` normalization a dependency bump had left
  failing (trailing-zero version pins, one long call split unnecessarily).
- **`_cancel_pending_tasks_bounded` could hang forever on Windows
  Proactor.** A background task that swallows `CancelledError` (as
  browser-style CDP tasks do) made `wait_for(gather(...))` never time
  out: the timeout cancels the waiting task, whose cancellation is
  delegated to the awaited gather and then into the stubborn child, so
  the waiting task is never woken. The bound is now enforced with
  `asyncio.wait(..., timeout=...)`, which releases its waiter via
  `call_later` regardless of child behaviour, keeping
  `call_async_from_sync` worker threads bounded as documented.
- **LSP reliability-machinery coverage:** three reliability modules are now
  exercised to the edges. `async_utils.py` **75.6% → 98.2%**
  (`test_async_utils_edges.py`), `lsp_session.py` **76.6% → 99.1%**
  (`test_lsp_session_edges.py`), and `lsp_client.py` **49.0% → 100%**
  (`test_lsp_client_edges.py` + `test_lsp_client_helpers.py`), covering
  one-shot subprocess fallbacks, response parsing, URI handling, session
  failure paths, and the Proactor cancellation regression. Aggregate unit-suite
  coverage rose **74.37% → 75.23%**, still above the CI gate.

### Changed

- **Packaging:** PDF/DOCX/PPTX/LaTeX parsers (`pypdf`, `python-docx`,
  `python-pptx`, `pylatexenc`) are included in the base install; the
  `[documents]` extra is removed. Optional extras are now `[rag]`, `[browser]`,
  and `[all]`.
- **Packaging:** `debugpy` is no longer bundled in the base wheel. Python
  debugging is auto-detected when `debugpy` is installed in the active
  environment (`pip install debugpy`), consistent with other DAP adapters and
  LSP servers. Contributor dev deps still include `debugpy`.
- **Model-facing file API:** `read` renamed to `read_file`, `create` renamed
  to `create_file`, and the old `read(type="symbols")` mode was retired. A
  dedicated `read_symbol` tool was tried and later removed. Final public tools:
  `read_file`, `find_symbols`, `create_file`, `replace_string`, `multiedit`,
  `undo_last_edit`.
- **CI:** `py-tests` required jobs on Linux and Windows run the full
  `backend/tests/unit` corpus (fast PR gates), not a fixed nine-file slice.
  [docs/CI.md](docs/CI.md) documents the tiers.
- **Testing:** [`pytest.ini`](pytest.ini) `testpaths` defaults to
  `backend/tests` (full tree for a bare `pytest`); use `pytest backend/tests/unit`
  to match the required gates locally.
- **Mutation testing:** Added `mutmut` to dev dependencies and CI workflow
  (`.github/workflows/mutation-testing.yml`). Targeted at reliability modules
  (`async_utils`, `lsp_client`, `lsp_session`, `response_processing`) to
  quantify test suite resilience against injected faults. Runs on Linux CI
  (mutmut does not support native Windows; see issue boxed/mutmut#397).
- **Docs:** [CONTRIBUTING.md](CONTRIBUTING.md) testing instructions match CI;
  added [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md),
  [docs/REGRESSION_TESTS.md](docs/REGRESSION_TESTS.md); user-facing autonomy
  naming is **conservative** / **balanced** / **full** only
  ([docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md),
  [docs/USER_GUIDE.md](docs/USER_GUIDE.md)).
- **OSS readiness:** added governance and ownership policy docs
  ([GOVERNANCE.md](GOVERNANCE.md), [MAINTAINERS.md](MAINTAINERS.md)),
  published [docs/SUPPORT_MATRIX.md](docs/SUPPORT_MATRIX.md), expanded
  [SUPPORT.md](SUPPORT.md) with response targets, and added
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Removed

- **`supervised` autonomy spelling:** Config, `/autonomy`, and
  `PermissionsConfig.get_preset()` no longer accept `supervised`; use
  `conservative` (same behaviour). A clear validation error points to
  `conservative` if old configs still say `supervised`.

## [1.0.0-rc1] - 2026-04-29

First release candidate. Includes everything in `0.56.0` plus the
pre-launch polish below. Tagged as `rc1` to invite community feedback
before the final `1.0.0` cut.

### Added

- **Symbol-aware reading restored** (tree-sitter-backed). Lets the
  agent fetch named symbols or a whole file through the public file API,
  replacing the previous multi-call dance of code search plus file reads.
  Backed by the already-core
  `backend.utils.treesitter_editor.TreeSitterEditor.find_symbol()`. Wired
  through `planner.py`, `function_calling.py`, and the CLI display layer.
- **README** rewritten with a multi-line pitch and an 11-row competitor
  comparison table (Grinta vs Aider, Claude Code, Codex CLI) covering
  install size, provider-agnosticism, local-first posture, LSP, DAP, HUD,
  stuck-detection, hardened_local profile, checkpoint/resume, Windows
  parity, and MCP support.
- **Demo material**: `docs/DEMO_SCRIPT.md` — a 60-second asciinema scenario
  (`demo_app/calc.py::average` `ZeroDivisionError`) plus an `agg` command
  for converting the cast into a GIF for the README.
- **Smoke-test scripts** for clean-box install verification:
  - `scripts/smoke/smoke_install.sh` (Linux/macOS, accepts extras as positional
    args; prefers a local wheel from `$WHEEL_DIR=./dist`, falls back to PyPI).
  - `scripts/smoke/smoke_install.ps1` (Windows mirror; reports site-packages MB).
  - `scripts/Dockerfile.smoke` (Python 3.12-slim base, ripgrep pre-installed,
    `EXTRAS` env var picks the optional extras to test).
  Each script runs `python -c "import backend"`, `--help`, and
  `verify_optional_imports.py` so a broken extras gate is caught before
  publishing to PyPI.
- **GitHub label catalog** at `.github/labels.yml` covering triage,
  type, severity, OS (`os: windows|linux|macos`), provider
  (`provider: openai|anthropic|google|openrouter|ollama|lmstudio`), area
  (`area: cli|engine|execution|lsp|dap|rag|mcp|safety|telemetry|packaging`),
  contributor onboarding, and release governance. Apply with
  `gh label sync -f .github/labels.yml`.

### Changed

- **Wheel size**: stable at ~1.4 MB on the base install (see `0.56.0`).
- **Issue template** version hint bumped to `1.0.0rc1`.
- **Autonomy is now a single-axis knob**. The three modes
  (`conservative` / `balanced` / `full`) share identical execution,
  prompting, and retry behaviour. The _only_ difference between them is
  _when_ the runtime stops to ask the user before running an action:
  conservative asks for every action, balanced asks only for high-risk
  actions, full never asks. The system prompt no longer branches on the
  mode (the previous "FULL AUTONOMOUS MODE" block has been replaced by a
  single mode-agnostic sentence so the prompt stays correct when the
  user toggles modes mid-session via `/autonomy`).
- **Cost caps and iteration limits decoupled from autonomy**.
  `max_cost_per_task`, `warn_at_cost`, `max_autonomous_iterations`, and
  `stuck_threshold_iterations` are now standalone config keys with
  global defaults; they apply universally regardless of autonomy mode.
  `PermissionsConfig.get_preset()` no longer pre-fills cost caps per
  mode, and the "this knob only applies in full autonomy" warning has
  been removed.

### Added

- **Per-session "always allow" memory** for the confirmation gate. The
  approval prompt now offers `[y/n/a=always]`; choosing `a` whitelists
  that exact action signature (e.g. the literal command string) for the
  remainder of the session so the agent does not re-ask for the same
  `pytest -q`, `git status`, or `ls` over and over. The whitelist is
  in-memory only and is cleared on process exit.

### Migration

- **`autonomy_level: supervised` is renamed to `conservative`** to
  better describe the behaviour ("confirm every action in the confirmation
  flow") and to avoid implying extra oversight features that don't exist.
  The string `supervised` is **rejected** in config files and on the
  `/autonomy` slash command; use `conservative` instead.
- Set `max_budget_per_task` explicitly in `settings.json` for per-task
  spend caps (see [docs/SETTINGS.md](docs/SETTINGS.md)).

## [0.56.0] - 2026-04-29

### Added

- **Auto-discovery of LSP servers**: `LspClient` now probes `PATH` for
  installed language servers (pylsp, typescript-language-server, rust-analyzer,
  gopls, clangd, jdtls, omnisharp, lua-language-server, bash-language-server,
  vscode-html-language-server, vscode-css-language-server, vscode-json-language-server,
  yaml-language-server, ruby-lsp, solargraph, intelephense, terraform-ls).
  No more pylsp-only gating.
- **Auto-discovery of DAP debug adapters**: `DAPDebugManager` now probes
  `PATH` for `dlv`, `codelldb`, `lldb-dap`, `netcoredbg`, `node`, etc. and
  falls back to a sensible adapter command when the model omits `adapter_command`.
  Python remains batteries-included via bundled `debugpy`.
- `detect_lsp_servers()` and `detect_debug_adapters()` discovery helpers
  exported for diagnostics / UI.
- Optional dependency extras: `[rag]` (chromadb + ONNX MiniLM-L6-v2),
  `[documents]` (PyPDF2 / python-docx / python-pptx / pylatexenc),
  `[browser]` (browser-use), and `[all]` (everything).

### Changed

- `enable_lsp_query` now defaults to **`True`** — the planner enables the
  `lsp` tool whenever any supported LSP server is on `PATH`.
- DAP `start` no longer requires the model to supply `adapter_command` for
  languages whose adapter is auto-discoverable.
- **Massive install slim-down**: base wheel dropped from ~1.6GB to ~1.4MB.
  Achieved by gating `chromadb` behind the `[rag]` extra, dropping the
  redundant `sentence-transformers` + `torch` + `transformers` stack in
  favour of chromadb's bundled ONNX `DefaultEmbeddingFunction` (384-dim,
  ~80MB) when `[rag]` is installed, and moving document parsers
  (`PyPDF2`, `python-docx`, `python-pptx`, `pylatexenc`) behind
  `[documents]`. `enable_vector_memory` and `enable_hybrid_retrieval`
  agent-config flags now default to `False`.
- `MemoryMonitor` migrated from `memory-profiler` to a `psutil`-based RSS
  sampler thread (no behaviour change for callers).

### Removed

- **GraphRAG** subsystem (`backend/context/graph_rag.py`,
  `graph_store.py`) and its dependent tools (`explore_tree_structure`,
  `read_symbol_definition`). The four remaining retrieval primitives
  (`grep` / `glob` via ripgrep, `find_symbols` / `read` via tree-sitter,
  `lsp` via LSP) cover the same surface
  without the index-maintenance cost.
- **`ReRanker`** class and the cross-encoder rerank step from
  `EnhancedVectorStore` — over-engineered for a CLI agent's recall
  workload. Hybrid retrieval now returns top-k candidates directly.
- Unused dependencies dropped from base install: `sentence-transformers`,
  `optimum`, `puremagic`, `memory-profiler`, plus the eager top-level
  imports of `python-docx` / `python-pptx` / `pylatexenc` / `PyPDF2` /
  `chromadb`.

## [0.55.0] - 2026-04-29

First public open-source release. Grinta is now a **CLI-only**, local-first
coding agent with no managed web UI, no hosted control plane, and no built-in
HTTP server.

### Added

- Open-source release on PyPI as `grinta`, with Homebrew and Scoop manifests
  in `packaging/` for native installs on macOS and Windows.
- `CHANGELOG.md` following [keepachangelog.com](https://keepachangelog.com)
  format and `SECURITY.md` describing reporting, threat model, and supported
  versions.
- `docs/SECURITY_CHECKLIST.md` documenting the trust boundary, built-in
  protections, and operator pre-flight checklist for untrusted repositories.
- `hardened_local` execution profile with workspace-scoped allowlists for git,
  package, and network-capable commands; CRITICAL refusal gate enforced in
  `safety_validator.py` regardless of profile or autonomy level.
- Session checkpoint and resume support via `SessionCheckpointManager`.
- `LLMRateGovernor` per-session token-rate throttling and cost-acceleration
  loop detection in `StuckDetector` to bound runaway agent loops.
- Real auto-recovery in `ErrorRecoveryStrategy` covering network retry,
  context truncation, and runtime restart.
- Canonical local-server startup planner shared by `start_server.py` and the
  embedded mode, with the resolved plan surfaced in health and settings
  output.
- Audit logging middleware for sensitive operations (settings, secrets,
  conversations) writing to `~/.grinta/workspaces/<id>/storage/<session>/audit/`.
- Plugin authoring guide (`docs/PLUGIN_GUIDE.md`) and MCP integration examples
  (`docs/MCP_EXAMPLES.md`).
- Cross-platform CI matrix on GitHub Actions: Ubuntu and Windows are required
  gates; macOS runs as advisory in both `py-tests.yml` and `e2e-tests.yml`.

### Changed

- Repositioned Grinta as a **CLI-only** coding agent. Removed the React web
  UI, Socket.IO surface, Textual TUI prototype, and the public
  `/api/v1/monitoring/*` HTTP endpoints. The CLI is the sole interactive
  surface.
- Removed all cloud runtime dependencies (`e2b`, `modal`,
  `runloop-api-client`, `daytona`) for a strictly local-first runtime.
- Renamed `get_remote_runtime_config` -> `get_runtime_config`.
- Hardened the local execution policy: interactive terminals, command cwd,
  uploads, and direct file access stay workspace-scoped under
  `security.execution_profile = "hardened_local"`.
- Crash recovery now fails closed more often, tracks restore provenance, and
  uses persisted control-event evidence to distinguish stale WAL from
  ambiguous recovery.
- Trimmed base dependencies: `asyncpg` and `libtmux` moved to optional
  groups; `python-socketio` removed from base runtime.
- Consolidated editor tools around a smaller public file API;
  older experimental editor modules are deprecated.
- Broke up `action_execution_server.py` (1944 → 4 focused modules),
  `conversation_memory.py` (1709 → 4 focused modules), and `config/utils.py`
  (43 KB → 4 focused modules).
- Rewrote `README.md` and the public docs set (`docs/INSTALL.md`,
  `docs/QUICK_START.md`, `docs/USER_GUIDE.md`, `docs/TROUBLESHOOTING.md`,
  `docs/ARCHITECTURE.md`, `docs/DEVELOPER.md`) for the CLI-only positioning.
- Repository home moved to `josephsenior/Grinta-Coding-Agent`; all release
  metadata, support links, and issue templates updated to match.

### Deprecated

- `ultimate_editor.py` — use the public file API instead.
- `universal_editor.py` — use the public file API or `atomic_refactor`
  internally instead.

### Removed

- React frontend, Socket.IO real-time streaming, Textual TUI replacement, and
  the `/api/v1/monitoring/agent-metrics` HTTP endpoint.
- `start_backend.ps1`, `openapi.json`, archival `client/` package, the dead
  `service_circuit_breaker.py`, and stale socket-era tests.

### Security

- New `SECURITY.md` documents reporting, supported versions, the threat
  model, and the trust boundary (Grinta runs as the operator’s OS user — it
  is **not** a sandbox).
- Secret masker strips known credential patterns from event-stream output,
  audit logs, and panel renders before display.
- Telemetry remains **off by default**; the only on-disk telemetry is the
  local `AuditLogger`. No outbound calls are made beyond configured LLM
  providers and explicitly enabled MCP servers.

[Unreleased]: https://github.com/josephsenior/Grinta-Coding-Agent/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/josephsenior/Grinta-Coding-Agent/releases/tag/v1.0.0
[1.0.0-rc1]: https://github.com/josephsenior/Grinta-Coding-Agent/releases/tag/v1.0.0-rc1
[0.56.0]: https://github.com/josephsenior/Grinta-Coding-Agent/releases/tag/v0.56.0
[0.55.0]: https://github.com/josephsenior/Grinta-Coding-Agent/releases/tag/v0.55.0
