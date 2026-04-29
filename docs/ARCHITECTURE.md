# Grinta Architecture

This document describes the current Grinta architecture for maintainers.
For design history and major pivots, see `docs/journey/README.md`.

## High-Level Shape

Grinta is a local-first autonomous coding agent with three core layers:

1. Orchestration: session loop, safeguards, retries, finish validation.
2. Execution: local runtime actions (commands, file ops, tool interaction).
3. Durability: event stream and persisted state for recovery/replay.

## Runtime Boundary

Grinta executes on the local host.

- Default runtime is in-process local execution.
- `hardened_local` applies stricter policy checks.
- `hardened_local` is not sandboxing or host isolation.

Use Grinta in trusted environments.

## System Overview

```text
User (CLI)
  -> backend.cli.entry
    -> SessionOrchestrator
      -> Engine (planning + tool intent)
      -> Operation pipeline and safety checks
      -> RuntimeExecutor (commands/files/tools)
      -> Observations
      -> EventStream (durable history)
      -> Task validation before finish
```

## Package Topology

```text
backend/
  cli/            CLI entrypoints and rendering
  context/        Memory and compaction
  core/           Config, constants, logging, shared utilities
  engine/         Agent reasoning and prompt assembly
  execution/      Local runtime, shell/session plumbing, and executor internals
  inference/      Provider routing and direct LLM clients
  integrations/   External integration adapters
  knowledge/      Optional retrieval and knowledge features
  ledger/         Event types, serialization, stream infrastructure
  orchestration/  Session orchestrator and focused services
  persistence/    Storage and state persistence
  playbooks/      Playbook definitions and helpers
  security/       Command risk analysis and policies
  telemetry/      Lightweight instrumentation
  tools/          Tool implementations and schemas
  validation/     Completion and quality validation
```

## Orchestration Layer

The orchestrator delegates to focused services under `backend/orchestration/services/`.
Current service modules include:

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

Design intent:

- split control-plane concerns into testable units
- classify errors into recoverable vs terminal paths
- prevent false completion with explicit task validation

## Execution Layer

Execution is implemented in `backend/execution/`.

Important components:

- `action_execution_server.py`: runtime executor implementation used by the local runtime
- `security_enforcement.py`: policy checks for command/path behavior
- `utils/`: command helpers, diffing, session handling, monitoring

## Durability Layer

Events flow through `backend/ledger/` and persistence modules.

Key properties:

- event-oriented state history
- replay-friendly serialization
- backpressure and stream controls
- persistence support for reliable recovery paths

## Configuration Model

Default local setup uses:

- installed `~/.grinta/settings.json`, or repository `settings.json` when running from source, for user-facing model/provider keys
- environment variables for automation and secret injection
- `~/.grinta/workspaces/<id>/storage` for runtime/session state

Minimal fields in `settings.template.json`:

- `llm_provider`
- `llm_model`
- `llm_api_key`
- `llm_base_url`

## Reliability and Safety

Core runtime protections include:

- retry and recovery services
- circuit breaker and stuck detection
- task validation before finish
- security policy checks in execution path

These controls are designed to reduce false-success runs and uncontrolled loops while keeping the local workflow fast.
