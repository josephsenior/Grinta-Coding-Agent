# Contributing to Forge

Thank you for your interest in contributing to Forge! This guide will help you get started.

## Development Setup

### Prerequisites
- Python 3.12+
- Git
- (Optional) PostgreSQL 14+ for database-backed storage

### Getting Started

```bash
# Clone
git clone https://github.com/josephsenior/Forge.git
cd Forge

# Backend
poetry install
python start_server.py

# Web UI: start the server, then open http://localhost:3000
uv run forge serve
```

## How to Contribute

### Reporting Bugs
- Use the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md)
- Include: steps to reproduce, expected vs actual behavior, environment details
- Attach logs from `backend/` console output if applicable

### Suggesting Features
- Use the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md)
- Describe the use case, not just the solution

### Submitting Code

1. **Fork** the repository
2. **Branch** from `main`: `git checkout -b feature/your-feature`
3. **Implement** your change following existing patterns
4. **Test**: run `pytest` for backend
5. **Commit** with a clear message: `feat: add trajectory pagination`
6. **Push** and open a Pull Request

### Code Standards

**Backend (Python):**
- Type hints on all function signatures
- Docstrings on public functions (Google style)
- `async def` for I/O-bound operations
- Use `forge_logger` for logging (not `print()`)
- Follow existing service decomposition patterns

**Python API client (`forge_client`):**
- Keep `ForgeClient` as the single place for httpx + Socket.IO to the backend
- Prefer extending `ForgeClient` over ad hoc httpx/socketio in scripts or tests

### Commit Convention

```
type: short description

types: feat, fix, refactor, docs, test, chore, perf
```

## Architecture Quick Reference

| Directory | Purpose |
|---|---|
| `backend/controller/` | Agent loop orchestration (22 decomposed services) |
| `backend/controller/services/` | Service classes composing the controller |
| `backend/events/` | Event sourcing, backpressure-aware stream, durable writer |
| `backend/storage/` | File & DB storage implementations |
| `backend/api/` | FastAPI app, routes, middleware, Socket.IO |
| `backend/engines/` | Agent engines (orchestrator, echo, etc.) |
| `backend/memory/` | Context condensers, RAG, vector store |
| `backend/core/` | Config (Pydantic), exceptions, schemas, logging |
| `backend/security/` | Security analyzer, input validation |
| `forge_client/` | Python HTTP + Socket.IO client for tests and scripts |

### Controller Service Map

The `AgentController` (~770 LOC) delegates work to these services:

| Service | Responsibility |
|---|---|
| `LifecycleService` | Init, reset, config binding |
| `ActionExecutionService` | Get & execute next agent action |
| `ActionService` | Action intake, pending coordination |
| `RecoveryService` | Exception classification, retry orchestration |
| `TaskValidationService` | Finish-action validation pipeline |
| `CircuitBreakerService` | Circuit breaker pattern |
| `StuckDetectionService` | 6-strategy stuck/loop detection |
| `IterationGuardService` | Iteration limit control flags |
| `BudgetGuardService` | Budget limit sync |
| `StateTransitionService` | Agent state machine transitions |
| `StepGuardService` | Pre-step guard checks |
| `StepPrerequisiteService` | Can-step prerequisite checks |
| `PendingActionService` | Pending action get/set/timeout |
| `ConfirmationService` | User confirmation flow |
| `SafetyService` | Safety validation |
| `RetryService` | Retry count & backoff |
| `ObservationService` | Observation event handling |
| `TelemetryService` | Tool pipeline & telemetry init |
| `AutonomyService` | Autonomy controller init |
| `IterationService` | Iteration counting |
| `ControllerContext` | Shared facade for services |

### Key Patterns

- **Event sourcing**: All agent actions/observations go through `EventStream`
- **Backpressure**: `EventStream` caps in-flight events and applies backpressure
- **Condenser**: Memory management via `Condenser` with configurable strategies
- **State checkpoints**: Timestamped state snapshots (last 3 kept for crash recovery)
- **Circuit breaker**: Trips after consecutive errors/stuck detections
- **Safe defaults**: Budget capped at $5, circuit breaker ON, graceful shutdown ON

## Questions?

Open a [Discussion](https://github.com/josephsenior/Forge/discussions) or file an issue.
