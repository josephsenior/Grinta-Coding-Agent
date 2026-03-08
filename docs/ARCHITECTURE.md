# Forge Architecture

This document provides a high-level overview of Forge's architecture for contributors and maintainers.

## System Overview

```
┌─────────────────────────────────────────────────────┐
│                   TUI (Textual / Python)             │
│  ForgeClient ─── Screens ─── Widgets                 │
└──────────────┬──────────────────┬────────────────────┘
               │ REST (FastAPI)   │ WebSocket (Socket.IO)
┌──────────────▼──────────────────▼────────────────────┐
│                 Backend (Python 3.12)                 │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │   Server     │  │  Controller  │  │   Events    │ │
│  │  (FastAPI)   │  │ (22 services)│  │  (Stream)   │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘ │
│         │                │                  │        │
│  ┌──────▼──────────────▼──────────────────▼──────┐ │
│  │          Core (Config, Schemas, Logging)        │ │
│  └──────┬──────────────┬──────────────────┬──────┘ │
│  ┌──────▼──────┐  ┌───▼────┐  ┌──────────▼─────┐  │
│  │   Storage   │  │ Memory │  │    Runtime      │  │
│  │ (File/DB)   │  │(Cond.) │  │  (Runtime)      │  │
│  └─────────────┘  └────────┘  └────────────────┘  │
└───────────────────────────────────────────────────────┘
```

## Backend Architecture

### Controller (`backend/controller/`)

The `AgentController` (~770 LOC) is the central orchestrator. It delegates to
22 decomposed services, each owning a single responsibility:

- **Lifecycle**: `LifecycleService` — init, reset, config binding
- **Execution**: `ActionExecutionService` — get & execute next action
- **Validation**: `TaskValidationService` — finish-action validation
- **Recovery**: `RecoveryService` — exception classification, retry
- **Safety**: `CircuitBreakerService`, `SafetyService`, `ConfirmationService`
- **Limits**: `IterationGuardService`, `BudgetGuardService`, `StepGuardService`
- **State**: `StateTransitionService`, `StepPrerequisiteService`
- **Detection**: `StuckDetectionService` (6 strategies)
- **Telemetry**: `TelemetryService`

### Event System (`backend/events/`)

All agent actions and observations flow through `EventStream`, which provides:

- **Backpressure**: Caps in-flight events, applies flow control
- **Persistence**: Events written to `FileStore` with write-ahead intent markers
- **Size limits**: 5 MB hard cap with intelligent field truncation
- **Subscriber model**: `EventStreamSubscriber` for decoupled consumption

### Memory (`backend/memory/`)

Context window management via the **Condenser** system:

- Configurable strategies (summarize, sliding window, hybrid)
- Bounded metadata storage (max 50 batches, oldest evicted)
- History size caps: 10,000 events AND 200 MB byte-size limit

### State Persistence (`backend/controller/state/`)

- States serialized as versioned JSON (schema v1)
- **Checkpoint system**: Timestamped snapshots, last 3 retained
- **Crash recovery**: Falls back to newest valid checkpoint if primary is corrupt
- Pickle fallback for legacy compatibility (read-only)

### Configuration (`backend/core/config/`)

Pydantic v2 Settings cascading dynamically from:
1. Environment variables (`.env`, `.env.local`)
2. Local Project Settings (`<workspace_root>/settings.json`)
3. Global User Settings (`~/.forge/settings.json`)
4. Internal Defaults

Provides safe merging.
- `ForgeConfig` — server-level: budget ($5 default), API keys
- `AgentConfig` — per-agent: circuit breaker (ON), graceful shutdown (ON)
- Startup warnings for insecure defaults (dev API key, unlimited budget)

### Storage (`backend/storage/`)

Abstract `FileStore` interface with implementations:
- Local filesystem
- In-memory (testing)
- S3
- Google Cloud Storage

## TUI Architecture

The TUI is built with [Textual](https://textual.textualize.io/) and lives in `tui/`.
It communicates with the backend via the same REST + Socket.IO protocol.

### Key Components

- `ForgeClient` — Async HTTP (httpx) + WebSocket (Socket.IO) client
- `HomeScreen` — Conversation list and creation
- `ChatScreen` — Streaming agent interaction with event dispatch
- `SettingsScreen` — LLM, agent, and secret configuration
- `DiffScreen` — Workspace diff viewer

## API Surface

### REST Endpoints

| Endpoint | Purpose |
|---|---|
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

- `oh_event` — Agent actions/observations
- `oh_action` — User-initiated actions
- `connect` / `disconnect` / `reconnect` — Connection lifecycle

## Reliability Features

| Feature | Mechanism |
|---|---|
| Budget safety | $5 default cap, 50%/80%/90% warnings |
| Circuit breaker | Trips after consecutive errors |
| Stuck detection | 6 strategies (loop, action repeat, etc.) |
| Graceful shutdown | Configurable, ON by default |
| State checkpoints | Last 3 timestamped snapshots |
| Event write-ahead | `.pending` marker files for crash safety |
| Memory bounding | History: 10K events + 200MB, condenser: 50 batches |
| Event size cap | 5MB hard limit with field truncation |
