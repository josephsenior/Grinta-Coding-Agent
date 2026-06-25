# Grinta Developer Guide

Contributor reference for current internals.

Related docs:

- **Contributor map (start here):** `docs/CONTRIBUTOR_MAP.md`
- User documentation: `docs/USER_GUIDE.md`
- Architecture overview: `docs/ARCHITECTURE.md`
- CI tiers (what PRs gate): `docs/CI.md`
- Regression test placement: `docs/REGRESSION_TESTS.md`
- Terminology contract: `docs/VOCABULARY.md`
- Historical context (not current spec): `docs/journey/README.md`

## Table of Contents

1. Repository Layout
2. Request Lifecycle
3. Orchestration Services
4. Execution Surface
5. Config and Environment
6. Testing and Validation
7. Adding Features Safely

---

## Repository Layout

```text
backend/
  cli/            Console entrypoint, Textual TUI, non-interactive runner, slash commands
  context/        Conversation memory and compaction
  core/           Config, constants, app paths, logging
  engine/         Prompt assembly, model interaction flow, and agent tools
  evaluation/     Agent eval pack and related evaluation helpers
  execution/      Runtime executor, shell/session plumbing, policy enforcement
  inference/      Provider resolver and direct LLM clients
  integrations/   External integrations (including MCP plumbing)
  knowledge/      Retrieval and knowledge-related modules
  ledger/         Actions, observations, stream, serialization
  orchestration/  SessionOrchestrator and focused services
  persistence/    Durable storage and state persistence helpers
  playbooks/      Task playbook assets and loading logic
  security/       Safety analysis and execution policies
  telemetry/      Lightweight telemetry
  tools/          Repo maintenance utilities (e.g. trajectory sanitization)
  utils/          Shared helpers (imports, LSP client, retries, etc.)
  validation/     Validation and completion guards
  tests/          Unit and integration tests
```

---

## Request Lifecycle

Canonical local flow:

```text
Console script
  -> backend.cli.entry
    -> Textual TUI or non-interactive runner
      -> SessionOrchestrator step loop
        -> engine decides next action
          -> execution layer runs action
            -> observation emitted
              -> orchestrator updates state
                -> finish path applies step guards plus optional completion-quality validation
```

---

## Orchestration Services

The orchestrator uses service modules in `backend/orchestration/services/`.
Current service files:

- `action_execution_service.py`
- `action_service.py`
- `autonomy_service.py`
- `circuit_breaker_service.py`
- `confirmation_service.py`
- `event_router_service.py`
- `exception_handler_service.py`
- `guard_bus.py`
- `iteration_guard_service.py`
- `iteration_service.py`
- `lifecycle_service.py`
- `observation_service.py`
- `orchestration_context.py`
- `pending_action_service.py`
- `recovery_service.py`
- `retry_service.py`
- `safety_service.py`
- `state_transition_service.py`
- `step_decision_service.py`
- `step_guard_service.py`
- `step_prerequisite_service.py`
- `stuck_detection_service.py`
- `task_validation_service.py` (warning-only completion-quality checks when enabled)

When adding new behavior, prefer extending an existing focused service first before creating new control-plane surfaces.

---

## Execution Surface

Execution internals live under `backend/execution/`.

Important entrypoints:

- console runtime usage through orchestrator
- runtime executor implementation in `backend.execution.server.action_execution_server`
- native browser helpers in `backend.execution.browser`
- DAP/debugger helpers in `backend.execution.dap`
- MCP runtime/proxy helpers in `backend.execution.mcp`

---

## Config and Environment

### Default user config

`settings.json` is the default user-facing local config file in a source checkout. Installed CLI runs use `~/.grinta/settings.json`; `APP_ROOT` can intentionally override the settings root.

Copy [settings.template.json](../settings.template.json) or run `grinta init`. The template matches the init wizard output shape:

| Block | Purpose |
| --- | --- |
| `llm_provider`, `llm_model`, `llm_api_key`, `llm_base_url` | Model routing (see [SETTINGS.md](SETTINGS.md)) |
| `agent.Orchestrator.mode` | `chat`, `plan`, or `agent` |
| `agent.Orchestrator.autonomy_level` | `conservative`, `balanced`, or `full` |
| `security` | Execution profile and read-boundary policy |
| `mcp_config` | MCP servers (off by default) |

Full key reference: [SETTINGS.md](SETTINGS.md). Unknown keys are warned at load time; see `backend/core/config/agent_config.py` for optional agent keys.

### Environment variables

Environment variables are supported and useful in CI/automation.
Common examples:

- `LLM_API_KEY`
- `LLM_MODEL`
- `APP_ROOT`

Runtime/session state is stored under `~/.grinta/workspaces/<id>/storage`, not under the repository tree.

### Interface paths

- TTY startup path: `launch/entry.py` -> `backend/cli/entry.py` -> `backend/cli/main.py` -> `backend/cli/tui/main.py`.
- Non-interactive path: `backend/cli/main.py` -> `backend/cli/repl/noninteractive.py`.
- Slash-command handlers live in `backend/cli/repl/slash_command_*`; the Textual TUI is the interactive surface. Keep slash-command behavior consistent when changing shared handlers.

### Security boundary

Grinta executes on local host permissions.
`hardened_local` adds policy constraints, but does not provide sandbox isolation.

---

## Testing and Validation

### Quick checks

```bash
uv run pytest backend/tests/unit/ --tb=short -q
```

That is the fast local loop and matches the Linux **unit** coverage shards. On Linux, Windows, and macOS, CI also runs integration, e2e, and stress in the platform extended gates after unit tests pass. Local mirror for coverage:

```bash
PYTHONPATH=. uv run pytest --cov=backend --cov-fail-under=75 backend/tests/unit
```

A bare `pytest` or `uv run pytest` from the repository root follows [`pytest.ini`](../pytest.ini) and collects all of **`backend/tests`** (integration, e2e, stress, and so on)—expect a long run and possible extra services.

```bash
PYTHONPATH=. uv run pytest --tb=short -q
```

### Targeted checks

```bash
uv run pytest backend/tests/unit/orchestration -q
uv run pytest backend/tests/unit/execution -q
uv run pytest backend/tests/unit/inference -q
```

### Static quality

```bash
uv run ruff check backend launch scripts
uv run mypy --config-file mypy.ini
```

If a change touches orchestration, run at least one focused orchestration suite and one end-to-end style test path when available. Bugfixes should add a targeted regression test per `docs/REGRESSION_TESTS.md`; release QA follows `docs/RELEASE_CHECKLIST.md`.

---

## Adding Features Safely

1. Define behavior first in one subsystem (orchestration, execution, inference, etc.).
2. Keep interfaces explicit (typed models, clear action/observation boundaries).
3. Route state-changing behavior through existing durability and validation paths.
4. Add tests for happy path and one realistic failure path.
5. Update docs in `docs/` when behavior changes user-facing workflows.

### Checklist

- Config impact documented
- Safety impact reviewed
- Tests added/updated
- Docs updated
- No hidden startup dependency introduced

---

For current architecture and contracts, use `docs/ARCHITECTURE.md` and `docs/ADR.md`. The journey under `docs/journey/` contains historical narrative — use this document for day-to-day contributor operations.
