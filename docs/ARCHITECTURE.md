# Grinta Architecture

This document provides a high-level overview of Grinta's architecture for contributors and maintainers. For the build history, major pivots, and decision rationale behind the current shape, see [The Book of Grinta](journey/README.md).

## Canonical Vocabulary

Grinta is standardizing its architecture language. Historical code names still
appear in a few places, but the canonical Grinta vocabulary going forward is:

| Current code term | Canonical Grinta term |
| --- | --- |
| `AgentController` / bare `Controller` | session orchestrator |
| `Action` | operation |
| `Observation` | outcome |
| `Event` | record |
| `EventStream` | ledger |
| `EventStore` | ledger store |
| backend `Session` | run |
| `State` | run state |
| `Checkpoint` | snapshot |
| `Trajectory` | transcript |
| `ActionExecutor` | runtime executor |
| `PendingAction` | open operation |
| `Autonomy` | execution policy |
| `Condenser` | compactor |
| `ConversationMemory` / generic memory layer | context memory |
| `ToolInvocationPipeline` | operation pipeline |
| `Review` | governance |

Until the code migration lands, this document uses the canonical term first and
mentions current implementation names where needed. The full term map lives in
[VOCABULARY.md](VOCABULARY.md).

Runtime remains the canonical system term even where implementation package
paths still live under `backend/execution/`.

## System Overview

```text
┌─────────────────────────────────────────────────────┐
│           Web UI (React) + API clients               │
│  Browser SPA  ·  client (httpx + Socket.IO)          │
└──────────────┬──────────────────┬────────────────────┘
               │ REST (FastAPI)   │ WebSocket (Socket.IO)
┌──────────────▼──────────────────▼────────────────────┐
│                 Backend (Python 3.12)                 │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │   Gateway    │  │Session Orch. │  │   Ledger    │ │
│  │  (FastAPI)   │  │ (21 services)│  │ (records)   │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘ │
│         │                │                  │        │
│  ┌──────▼──────────────▼──────────────────▼──────┐ │
│  │          Core (Config, Schemas, Logging)        │ │
│  └──────┬──────────────┬──────────────────┬──────┘ │
│  ┌──────▼──────┐  ┌───▼────┐  ┌──────────▼─────┐  │
│  │Persistence  │  │Context  │  │    Runtime      │  │
│  │ (File/DB)   │  │ Memory  │  │(backend/execution)│
│  └─────────────┘  └────────┘  └────────────────┘  │
└───────────────────────────────────────────────────────┘
```

Runtime note: Grinta currently uses a local in-process runtime. The optional `hardened_local` profile adds stricter local execution policy, but it is not sandboxing or process isolation.

## Backend Architecture

### Orchestration (`backend/orchestration/`)

The session orchestrator (`SessionOrchestrator` in the current codebase, ~770 LOC)
is the central control-plane component. It delegates to 21 focused services,
each owning a narrow piece of the agent loop:

- **Lifecycle**: `LifecycleService` — init, reset, config binding
- **Execution**: `ActionExecutionService`, `ActionService`, `ObservationService`
- **Validation**: `TaskValidationService` — finish-action validation
- **Recovery**: `RecoveryService`, `RetryService`, `ExceptionHandlerService`
- **Safety and governance**: `AutonomyService`, `CircuitBreakerService`, `SafetyService`, `ConfirmationService`
- **Iteration control**: `IterationService`, `IterationGuardService`
- **State and stepping**: `StateTransitionService`, `StepDecisionService`, `StepGuardService`, `StepPrerequisiteService`
- **Coordination**: `EventRouterService`, `PendingActionService`
- **Detection**: `StuckDetectionService` — repetition and no-progress heuristics

For the decomposition story — how the orchestrator grew from a monolith into 21 services — see [The Architectural Gauntlet](journey/03-the-architectural-gauntlet.md). For how `TaskValidationService` prevents false finishes, see [The Verification Tax](journey/14-the-verification-tax.md).

### Ledger (`backend/ledger/`)

All records flow through the ledger (`EventStream` in the current codebase), which provides:

- **Backpressure**: Caps in-flight events, applies flow control
- **Persistence**: Records written to `FileStore` with write-ahead intent markers
- **Size limits**: 5 MB hard cap with intelligent field truncation
- **Subscriber model**: `EventStreamSubscriber` for decoupled consumption

### Context Memory (`backend/context/`)

Context memory is managed via the compactor system. The codebase and persisted config both use `Compactor` terminology:

- Configurable strategies (summarize, sliding window, hybrid)
- Bounded metadata storage (max 50 batches, oldest evicted)
- History size caps: 10,000 events AND 200 MB byte-size limit

For the full history of how the compactor subsystem evolved from 2 strategies to 12+ and back down to 9, see [The Context War](journey/04-the-context-war.md).

### Runtime (`backend/execution/` in the current codebase)

Grinta currently uses a local in-process runtime layer that:

- Executes operations against the local workspace
- Applies policy enforcement and confirmation gates
- Supports stricter `hardened_local` controls without claiming sandbox isolation

### Run-State Persistence (`backend/orchestration/state/`)

- Run states serialized as versioned JSON (schema v1)
- **Snapshot system**: Timestamped state snapshots, last 3 retained
- **Crash recovery**: Falls back to newest valid snapshot if primary is corrupt
- Pickle fallback for legacy compatibility (read-only)

### Configuration (`backend/core/config/`)

Pydantic v2 Settings cascading dynamically from:

1. Environment variables (`.env`, `.env.local`)
2. **`settings.json`** in the app root (directory from `APP_ROOT`, or the process working directory when the server starts — not the per-folder workspace root)
3. Internal defaults

Provides safe merging.

- `AppConfig` — server-level: budget ($5 default), API keys
- `AgentConfig` — per-agent: circuit breaker (ON), graceful shutdown (ON)
- Startup warnings for insecure defaults (dev API key, unlimited budget)

### Persistence (`backend/persistence/`)

Abstract `FileStore` interface with implementations:

- Local filesystem
- In-memory (testing)
- S3
- Google Cloud Storage

## Clients

The React web app and automation/tests share the same REST + Socket.IO protocol.
The Python package `client` provides :class:`~client.GrintaClient`
(httpx + Socket.IO) for scripts and unit tests.

## API Surface

### REST Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health/live` | Kubernetes liveness probe |
| `GET /api/health/ready` | Kubernetes readiness probe |
| `GET /api/monitoring/health` | Detailed health snapshot |
| `GET /api/monitoring/metrics` | JSON system metrics |
| `GET /api/monitoring/cost-summary` | Per-session cost breakdown |
| `GET /api/monitoring/metrics-prom` | Prometheus-format metrics |
| `GET /api/options/models` | Available LLM models |
| `GET /api/options/agents` | Available agent types |
| `GET /api/options/config` | Current configuration |

### WebSocket Events

- `app_event` — streamed records and outcomes delivered to clients
- `app_action` / `app_user_action` — incoming client operations
- `connect` / `disconnect` / `reconnect` — Connection lifecycle

## Reliability Features

| Feature | Mechanism |
| --- | --- |
| Budget safety | $5 default cap, 50%/80%/90% warnings |
| Circuit breaker | Trips after consecutive errors |
| Stuck detection | 6 strategies (loop, action repeat, etc.) |
| Graceful shutdown | Configurable, ON by default |
| Run-state snapshots | Last 3 timestamped snapshots |
| Event write-ahead | `.pending` marker files for crash safety |
| Memory bounding | History: 10K events + 200MB, compactor metadata: 50 batches |
| Event size cap | 5MB hard limit with field truncation |

## Further Reading

Several subsystems have dedicated journey chapters that go deeper than this reference:

- **Playbooks** (`backend/playbooks/`): Runtime knowledge injection that replaced prompt bloat — [The Hidden Playbooks](journey/13-the-hidden-playbooks.md)
- **Prompt architecture** (`backend/engine/prompts/`): Why the system prompt is built in Python, not Jinja — [Prompts Are Programs](journey/15-prompts-are-programs.md)
- **Model-agnostic inference** (`backend/inference/`): The three-client architecture and catalog-driven overrides — [The Model-Agnostic Reckoning](journey/10-model-agnostic-reckoning.md)
- **Cross-platform execution** (`backend/execution/`): Terminal multiplexing, Windows edge cases, and the semantic execution layer — [The Console Wars](journey/11-the-console-wars.md)
