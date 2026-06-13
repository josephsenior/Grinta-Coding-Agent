# Grinta Architecture

This document describes the current Grinta architecture for maintainers.
For historical context and design rationale (not current spec), see `docs/journey/README.md`.

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
  engine/         Agent reasoning, prompt assembly, and tool implementations
  evaluation/     Agent eval pack and related evaluation helpers
  execution/      Local runtime, shell/session plumbing, and executor internals
  inference/      Provider routing and direct LLM clients
  integrations/   External integration adapters (MCP; see docs/INFERENCE_AND_INTEGRATIONS.md)
  knowledge/      Optional retrieval and knowledge features
  ledger/         Event types, serialization, stream infrastructure
  orchestration/  Session orchestrator and focused services
  persistence/    Storage and state persistence
  playbooks/      Playbook definitions and helpers
  security/       Command risk analysis and policies
  telemetry/      Lightweight instrumentation
  tools/          Repo maintenance utilities (not agent-facing tools)
  utils/          Shared helpers (imports, LSP, HTTP, etc.)
  validation/     Completion and quality validation
```

## Orchestration Layer

The orchestrator delegates to focused services under `backend/orchestration/services/`.
Current service modules include:

- `action_execution_service.py` - Executes agent actions via the runtime
- `action_service.py` - Action lifecycle management
- `autonomy_service.py` - Controls agent autonomy and delegation
- `circuit_breaker_service.py` - Prevents cascading failures
- `confirmation_service.py` - Handles user confirmation flows
- `event_router_service.py` - Routes events to appropriate handlers
- `exception_handler_service.py` - Centralized exception handling
- `guard_bus.py` - Pub/sub guard rail for system events
- `iteration_guard_service.py` - Prevents infinite loops
- `iteration_service.py` - Manages iteration counting and limits
- `lifecycle_service.py` - Manages agent lifecycle transitions
- `observation_service.py` - Processes observations from actions
- `pending_action_service.py` - Tracks in-flight actions
- `recovery_service.py` - Error recovery and retry logic
- `retry_service.py` - Handles retry policies
- `safety_service.py` - Validates actions against safety policies
- `state_transition_service.py` - Manages valid state transitions
- `step_decision_service.py` - Decides whether to continue or finish
- `step_guard_service.py` - Pre-step validation checks
- `step_prerequisite_service.py` - Ensures prerequisites are met
- `stuck_detection_service.py` - Detects stuck agents
- `task_validation_service.py` - Validates task completion

Design intent:

- split control-plane concerns into testable units
- classify errors into recoverable vs terminal paths
- prevent false completion with explicit task validation

### Middleware Pipeline

The orchestrator uses a middleware pipeline (defined in `session_orchestrator.py` lines 218-235) for cross-cutting concerns:

```python
middlewares = [
    SafetyValidatorMiddleware(self),      # Validate action safety
    BlackboardMiddleware(self),         # Track action context
    CircuitBreakerMiddleware(self),     # Prevent cascading failures  
    ProgressPolicyMiddleware(),            # Progress indicators
    CostQuotaMiddleware(self),          # Budget tracking
    ContextWindowMiddleware(self),       # Context window management
    RollbackMiddleware(),               # State rollback support
    DestructiveCommandMiddleware(),      # Block dangerous commands
    PreExecDiffMiddleware(),             # Generate diffs before edits
    AutoCheckMiddleware(),               # Post-execution validation
    LoggingMiddleware(self),            # Request/response logging
    TelemetryMiddleware(self),          # Metrics collection
    ToolResultValidator(),             # Validate tool outputs
]
```

Middleware execution order matters - safety checks run first, telemetry runs last.

### Key Flows

#### Step Execution Flow
1. `orchestrator.step()` called
2. Acquires `self._step_lock` (asyncio.Lock)
3. Calls `services.pending_action.set(action)`
4. Middleware pipeline processes action
5. Action executed via `services.action_execution`
6. Observation processed by `services.observation`
7. State updated via `state_tracker`
8. Releases lock, updates metrics

#### Error Recovery Flow
1. Exception occurs during step
2. `services.recovery.react_to_exception(e)` called
3. Error classified as recoverable or terminal
4. Recoverable: retry with backoff via `services.retry`
5. Terminal: emit error observation, transition to CLOSING

#### Lifecycle Transitions
- INITIALIZING → ACTIVE: After service initialization
- ACTIVE → CLOSING: On agent finish or error
- CLOSING → CLOSED: After cleanup and checkpoint

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

For detailed reliability patterns, see [RELIABILITY.md](RELIABILITY.md).
For performance considerations, see [PERFORMANCE.md](PERFORMANCE.md).
