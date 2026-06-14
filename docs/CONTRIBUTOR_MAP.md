# Contributor Map

Task-oriented entry points for navigating Grinta. Use this before diving into
184K+ lines of production code. For lifecycle and package layout, see
[DEVELOPER.md](DEVELOPER.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## Bootstrap (first 30 minutes)

```bash
python scripts/bootstrap_env.py dev-test
uv run python -m backend.cli.entry init   # optional: configure a model
PYTHONPATH=. uv run pytest backend/tests/unit -q
```

Install path for end users: `pipx install grinta-ai`. Contributors should use
`uv run` from a source checkout so dependencies stay isolated.

## Where to start by task

| If you are changing… | Start here | Tests nearby |
| --- | --- | --- |
| CLI commands, startup, slash commands | `launch/entry.py` → `backend/cli/entry.py` → `backend/cli/main.py`; shared slash-command code under `backend/cli/_repl/` | `backend/tests/unit/cli/` |
| TUI screens and rendering | `backend/cli/tui/app.py`, mixins under `backend/cli/tui/` | `backend/tests/unit/cli/tui/` |
| Agent step loop (core control plane) | `backend/orchestration/session_orchestrator.py` + mixins in `session_orchestrator_mixins/` | `backend/tests/unit/orchestration/` |
| Middleware (safety, cost, rollback) | `backend/orchestration/session_orchestrator.py` (pipeline list), files under `backend/orchestration/middleware/` | `backend/tests/unit/orchestration/test_*middleware*` |
| Tool execution (bash, edit, grep, browser) | `backend/execution/action_execution_server.py`, `backend/engine/tools/` | `backend/tests/unit/execution/`, `backend/tests/unit/engine/` |
| LLM provider routing and API calls | `backend/inference/registry.py`, `backend/inference/llm.py`, `backend/inference/direct_clients.py` | `backend/tests/unit/inference/` |
| Model catalogs | `backend/inference/catalogs/*.json` | `backend/tests/unit/inference/test_registry.py`, `test_catalog_integrity.py`, `backend/tests/integration/test_inference_model_listing_integration.py` |
| Context window and compaction | `backend/context/context_pipeline.py`, `backend/context/prompt_window.py` | `backend/tests/unit/context/` |
| Event stream and durability | `backend/ledger/stream.py`, `backend/ledger/durable_writer.py` | `backend/tests/unit/ledger/` |
| MCP external tools | `backend/integrations/mcp/`, bootstrap in `backend/execution/mcp/` | `backend/tests/unit/integrations/mcp/` |
| User settings and config | `backend/core/config/`, `settings.template.json` | `backend/tests/unit/core/` |
| Safety and command risk | `backend/security/command_analyzer.py`, `backend/orchestration/safety_validator.py` | `backend/tests/unit/security/` |

## One request, end to end

Typical user message through the stack:

```text
backend/cli/entry.py (startup)
  → backend/cli/main.py
  → backend/cli/tui/main.py or repl_noninteractive.py
  → SessionOrchestrator.step()          backend/orchestration/session_orchestrator.py
    → middleware pipeline               backend/orchestration/middleware/
    → engine plans next Action          backend/engine/
    → ActionExecutionService            backend/orchestration/services/action_execution_service.py
    → RuntimeExecutor                   backend/execution/action_execution_server.py
    → Observation                       backend/ledger/observation/
    → EventStream append                backend/ledger/stream.py
    → context compaction (if needed)    backend/context/
    → LLM call for next turn            backend/inference/llm.py
```

## Large modules (read before you refactor)

These files carry most of the complexity. Prefer extending existing services or
mixins over growing them further. Split work belongs in focused follow-up PRs.

| Module | ~LOC | Role |
| --- | ---: | --- |
| `backend/cli/tui/_app_renderer_event_processor.py` | 1,700+ | TUI event rendering |
| `backend/context/context_pipeline.py` | 1,350 | Compaction orchestration |
| `backend/inference/llm.py` | 1,215 | LLM call surface |
| `backend/engine/tools/_file_edits.py` | 1,175 | File edit tools |
| `backend/ledger/stream.py` | 1,160 | Durable event stream |
| `backend/context/prompt_window.py` | 1,100 | Prompt assembly / windowing |

## Inference vs integrations

| Layer | Package | Read first |
| --- | --- | --- |
| LLM providers | `backend/inference/` | [INFERENCE_AND_INTEGRATIONS.md](INFERENCE_AND_INTEGRATIONS.md) |
| MCP servers | `backend/integrations/mcp/` | [integrations/mcp/README.md](../backend/integrations/mcp/README.md) |
| Native agent tools | `backend/engine/tools/` + `backend/execution/` | [ARCHITECTURE.md](ARCHITECTURE.md) |

Do not confuse `backend/execution/utils/tool_registry.py` (host OS binaries)
with `backend/engine/tool_registry.py` (LLM tool name validation).

## Safe change checklist

1. Find the subsystem row in the table above.
2. Run the matching unit test directory before and after your edit.
3. For user-visible behavior, update `docs/USER_GUIDE.md` or `docs/TROUBLESHOOTING.md`.
4. For bugfixes, add a regression test per [REGRESSION_TESTS.md](REGRESSION_TESTS.md).
5. PR gates require `pytest backend/tests/unit` on Linux and Windows — see [CI.md](CI.md).

## Platform expectations

Linux and Windows are **required** CI platforms. macOS is **best effort** until
promoted — see [SUPPORT_MATRIX.md](SUPPORT_MATRIX.md#macos-platform-policy).
