# Changelog

All notable changes to Grinta will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

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

[Unreleased]: https://github.com/josephsenior/Grinta-Coding-Agent/compare/v0.55.0...HEAD
[0.55.0]: https://github.com/josephsenior/Grinta-Coding-Agent/releases/tag/v0.55.0
