# Changelog

All notable changes to Forge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Agent performance metrics service (`MetricsService`) with comprehensive task tracking
- `/api/v1/monitoring/agent-metrics` endpoint for aggregate performance metrics
- Audit logging middleware for sensitive operations (settings, secrets, conversations)
- Cursor-based conversation pagination with `page_id` and `next_page_id`
- `CHANGELOG.md` following keepachangelog.com format
- `ARCHITECTURE.md` with full system walkthrough for contributors
- Plugin authoring guide (`docs/PLUGIN_GUIDE.md`)
- MCP integration examples (`docs/MCP_EXAMPLES.md`)
- Session checkpoint/resume support via `SessionCheckpointManager`
- `LLMRateGovernor` — per-session token-rate throttling to prevent runaway loops
- Token-level and cost-acceleration loop detection in `StuckDetector`
- Real auto-recovery in `ErrorRecoveryStrategy` (network retry, context truncation, runtime restart)

### Changed

- **BREAKING**: All API endpoints migrated from `/api/*` to `/api/v1/*` for versioning
  - Update client code to use `/api/v1/` base URL (e.g., `/api/conversations` → `/api/v1/conversations`)
- Removed all cloud runtime dependencies (e2b, modal, runloop-api-client, daytona) for local-first architecture
- Renamed `get_remote_runtime_config` → `get_runtime_config` (function retrieves local runtime config)
- Deleted dead code: `service_circuit_breaker.py` (0 imports)
- Rewrote `README.md` with comparison table, architecture diagram, and feature showcase
- Broke up `action_execution_server.py` (1944→4 focused modules)
- Broke up `conversation_memory.py` (1709→4 focused modules)
- Broke up `config/utils.py` (43KB→4 focused modules)
- Trimmed base dependencies: moved `asyncpg`, `libtmux` to optional groups
- Replaced React frontend with Textual TUI (~14 Python files vs ~638 TypeScript files)
- Consolidated editor tools — `str_replace_editor` is the primary, others deprecated
- Improved CLI entry point with `forge init` command

### Deprecated

- `ultimate_editor.py` — use `str_replace_editor` instead
- `universal_editor.py` — use `str_replace_editor` or `atomic_refactor` instead

## [0.55.0] - 2026-02-12

### Added

- Event-sourced session resilience with WAL crash recovery
- 12 context condensers (smart, LLM, semantic, amortized, attention, observation masking, etc.)
- Anti-hallucination system with proactive tool-choice enforcement
- Circuit breaker with configurable thresholds (errors, stuck, high-risk actions)
- Stuck detector with 6 detection strategies (syntax loops, semantic loops, monologues, etc.)
- Error recovery with 9 error type classifications
- MCP (Model Context Protocol) client integration
- GitHub PR integration (create, update, address comments)
- Cost tracking and per-task budget limits
- 16 server middleware (rate limiting, cost quotas, security headers, compression, etc.)
- Playbook system with 19 built-in playbooks
- Tree-sitter structure-aware editing (45+ languages)
- Multi-LLM support (OpenAI, Anthropic, Google Gemini)
- PostgreSQL, file, and SQLite storage backends
- React frontend with Socket.IO real-time streaming
- Textual TUI replacement for React frontend
- Docker runtime environment with cross-platform shell abstraction

[Unreleased]: https://github.com/josephsenior/Forge/compare/v0.55.0...HEAD
[0.55.0]: https://github.com/josephsenior/Forge/releases/tag/v0.55.0
