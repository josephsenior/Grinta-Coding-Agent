# Changelog

All notable changes to Grinta will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **CI:** `py-tests` required jobs on Linux and Windows now run the full
  `backend/tests/unit` corpus (aligned with `pytest.ini`), not a fixed
  nine-file slice. [docs/CI.md](docs/CI.md) documents the tiers.
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

- **`read_symbol_definition` tool restored** (tree-sitter-backed). Lets the
  agent fetch a single named symbol (`path:Symbol` or `path:Class.method`)
  or a whole file in one call, replacing the previous 2-3 call dance of
  `search_code` + `read_file`. Backed by the already-core
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
  - `scripts/smoke_install.sh` (Linux/macOS, accepts extras as positional
    args; prefers a local wheel from `$WHEEL_DIR=./dist`, falls back to PyPI).
  - `scripts/smoke_install.ps1` (Windows mirror; reports site-packages MB).
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
  better describe the behaviour ("confirm every action") and to avoid
  implying extra oversight features that don't exist. The string
  `supervised` is still accepted in config files and on the `/autonomy`
  slash command — it is silently rewritten to `conservative` and a
  one-time deprecation warning is logged. The alias will be removed in
  a future release; please update your configs.
- If you previously relied on **per-mode cost caps** (`$5` for
  supervised, `$10` for balanced, `$15` warn for full) being applied
  automatically by `PermissionsConfig.get_preset()`, set
  `max_cost_per_task` and `warn_at_cost` explicitly in your permissions
  config — they are no longer derived from the autonomy mode.

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
  (`search_code` via ripgrep, `symbol_editor` via tree-sitter,
  `lsp` via LSP, `read_file`) cover the same surface
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

- Open-source release on PyPI as `grinta-ai`, with Homebrew and Scoop manifests
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
- Consolidated editor tools — `str_replace_editor` is the primary editor;
  `ultimate_editor.py` and `universal_editor.py` are deprecated.
- Broke up `action_execution_server.py` (1944 → 4 focused modules),
  `conversation_memory.py` (1709 → 4 focused modules), and `config/utils.py`
  (43 KB → 4 focused modules).
- Rewrote `README.md` and the public docs set (`docs/INSTALL.md`,
  `docs/QUICK_START.md`, `docs/USER_GUIDE.md`, `docs/TROUBLESHOOTING.md`,
  `docs/ARCHITECTURE.md`, `docs/DEVELOPER.md`) for the CLI-only positioning.
- Repository home moved to `josephsenior/Grinta-Coding-Agent`; all release
  metadata, support links, and issue templates updated to match.

### Deprecated

- `ultimate_editor.py` — use `str_replace_editor` instead.
- `universal_editor.py` — use `str_replace_editor` or `atomic_refactor`
  instead.

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

[Unreleased]: https://github.com/josephsenior/Grinta-Coding-Agent/compare/v1.0.0-rc1...HEAD
[1.0.0-rc1]: https://github.com/josephsenior/Grinta-Coding-Agent/releases/tag/v1.0.0-rc1
[0.56.0]: https://github.com/josephsenior/Grinta-Coding-Agent/releases/tag/v0.56.0
[0.55.0]: https://github.com/josephsenior/Grinta-Coding-Agent/releases/tag/v0.55.0
