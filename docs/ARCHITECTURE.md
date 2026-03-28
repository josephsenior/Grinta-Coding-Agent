# Forge Architecture

This document provides a high-level overview of Forge's architecture for contributors and maintainers.

## Canonical Vocabulary

Forge is standardizing its architecture language. Historical code names still
appear in a few places, but the canonical Forge vocabulary going forward is:

| Current code term | Canonical Forge term |
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
│  Browser SPA  ·  forge_client (httpx + Socket.IO)    │
└──────────────┬──────────────────┬────────────────────┘
               │ REST (FastAPI)   │ WebSocket (Socket.IO)
┌──────────────▼──────────────────▼────────────────────┐
│                 Backend (Python 3.12)                 │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │   Gateway    │  │Session Orch. │  │   Ledger    │ │
│  │  (FastAPI)   │  │ (22 services)│  │ (records)   │ │
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

Runtime note: Forge currently uses a local in-process runtime. The optional `hardened_local` profile adds stricter local execution policy, but it is not sandboxing or process isolation.

## Backend Architecture

### Orchestration (`backend/orchestration/`)

The session orchestrator (`SessionOrchestrator` in the current codebase, ~770 LOC)
is the central control-plane component. It delegates to 22 decomposed services,
each owning a single responsibility:

- **Lifecycle**: `LifecycleService` — init, reset, config binding
- **Execution**: `ActionExecutionService` — get & execute next action
- **Validation**: `TaskValidationService` — finish-action validation
- **Recovery**: `RecoveryService` — exception classification, retry
- **Safety**: `CircuitBreakerService`, `SafetyService`, `ConfirmationService`
- **Limits**: `IterationGuardService`, `BudgetGuardService`, `StepGuardService`
- **State**: `StateTransitionService`, `StepPrerequisiteService`
- **Detection**: `StuckDetectionService` (6 strategies)
- **Telemetry**: `TelemetryService`

### Ledger (`backend/ledger/`)

All records flow through the ledger (`EventStream` in the current codebase), which provides:

- **Backpressure**: Caps in-flight events, applies flow control
- **Persistence**: Records written to `FileStore` with write-ahead intent markers
- **Size limits**: 5 MB hard cap with intelligent field truncation
- **Subscriber model**: `EventStreamSubscriber` for decoupled consumption

### Context Memory (`backend/context/`)

Context memory is managed via the compactor system (`Condenser` in the current codebase):

- Configurable strategies (summarize, sliding window, hybrid)
- Bounded metadata storage (max 50 batches, oldest evicted)
- History size caps: 10,000 events AND 200 MB byte-size limit

### Runtime (`backend/execution/` in the current codebase)

Forge currently uses a local in-process runtime layer that:

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
2. **`settings.json`** in the Forge **app root** (directory from `FORGE_APP_ROOT`, or the process working directory when the server starts — not the per-folder workspace root)
3. Internal defaults

Provides safe merging.

- `ForgeConfig` — server-level: budget ($5 default), API keys
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
The Python package `forge_client` provides :class:`~forge_client.ForgeClient`
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

- `forge_event` — streamed records and outcomes delivered to clients
- `forge_action` / `forge_user_action` — incoming client operations
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
| Memory bounding | History: 10K events + 200MB, condenser: 50 batches |
| Event size cap | 5MB hard limit with field truncation |
