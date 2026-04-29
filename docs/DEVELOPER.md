# Grinta Developer Guide

Contributor reference for current internals.

Related docs:

- User documentation: `docs/USER_GUIDE.md`
- Architecture overview: `docs/ARCHITECTURE.md`
- Terminology contract: `docs/VOCABULARY.md`
- Historical rationale: `docs/journey/README.md`

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
  cli/            Terminal UI, entrypoint, interaction loop
  context/        Conversation memory and compaction
  core/           Config, constants, app paths, logging
  engine/         Prompt assembly and model interaction flow
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
  tools/          Tool interfaces and implementations
  validation/     Validation and completion guards
  tests/          Unit and integration tests
```

---

## Request Lifecycle

Canonical local flow:

```text
CLI input
  -> SessionOrchestrator step loop
    -> engine decides next action
      -> execution layer runs action
        -> observation emitted
          -> orchestrator updates state
            -> task validation gate controls completion
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
- `task_validation_service.py`

When adding new behavior, prefer extending an existing focused service first before creating new control-plane surfaces.

---

## Execution Surface

Execution internals live under `backend/execution/`.

Important entrypoints:

- CLI runtime usage through orchestrator
- runtime executor implementation in `backend.execution.action_execution_server`

---

## Config and Environment

### Default user config

`settings.json` is the default user-facing local config file in a source checkout. Installed CLI runs use `~/.grinta/settings.json`; `APP_ROOT` can intentionally override the settings root.
Template fields in `settings.template.json`:

- `llm_provider`
- `llm_model`
- `llm_api_key`
- `llm_base_url`

### Environment variables

Environment variables are supported and useful in CI/automation.
Common examples:

- `LLM_API_KEY`
- `LLM_MODEL`
- `APP_ROOT`

Runtime/session state is stored under `~/.grinta/workspaces/<id>/storage`, not under the repository tree.

### Security boundary

Grinta executes on local host permissions.
`hardened_local` adds policy constraints, but does not provide sandbox isolation.

---

## Testing and Validation

### Quick checks

```bash
uv run pytest backend/tests/unit/ --tb=short -q
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

If a change touches orchestration, run at least one focused orchestration suite and one end-to-end style test path when available.

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

For architecture decisions beyond implementation details, keep `docs/journey/` as the source of truth and use this document for current contributor operations.
