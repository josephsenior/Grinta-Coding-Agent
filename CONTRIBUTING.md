# Contributing to Grinta

Thank you for your interest in contributing to Grinta! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.12+
- Git
- (Optional) PostgreSQL 14+ for database-backed storage

### Getting Started

```bash
# Clone
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git
cd Grinta-Coding-Agent

# Install dependencies
uv sync

# Start the CLI
uv run python -m backend.cli.entry
```

## How to Contribute

### Reporting Bugs

- Use the [Bug Report template](.github/ISSUE_TEMPLATE/bug_template.yml)
- Include: steps to reproduce, expected vs actual behavior, environment details
- Attach logs from `backend/` console output if applicable

### Suggesting Features

- Use the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md)
- Describe the use case, not just the solution

### Submitting Code

1. **Fork** the repository
2. **Branch** from `main`: `git checkout -b feature/your-feature`
3. **Implement** your change following existing patterns
4. **Test**: see [Testing before a pull request](#testing-before-a-pull-request)
5. **Commit** with a clear message: `feat: add trajectory pagination`
6. **Push** and open a Pull Request

### Testing before a pull request

**Required** GitHub Actions jobs on Linux and Windows run the full **unit** corpus only. Match that locally before you open a PR:

```bash
uv sync --group dev --group test --group runtime
PYTHONPATH=. uv run pytest backend/tests/unit
```

Optional: `uv run pytest backend/tests/unit -q` for quieter output.

A bare `pytest` or `PYTHONPATH=. uv run pytest` from the repository root discovers all of **`backend/tests`** (unit, integration, e2e, stress, and so on) per [`pytest.ini`](pytest.ini). That run is much slower and may need extra services; use it when your change spans those tiers or before a large release.

The scheduled **Heavy / Integration Tests** job runs a marker-filtered slice (`pytest backend/tests -m "heavy or integration or benchmark"`). See [docs/CI.md](docs/CI.md#heavy--integration--benchmark-tier).

If your change touches the CLI, REPL, or orchestration hot paths, also run the [CLI regression workflow](.github/workflows/e2e-tests.yml) locally when possible (it may also run on PRs when files under `backend/`, `launch/`, etc. change).

For bugfix PRs, prefer adding a **regression test** next to the code you fixed (see [docs/REGRESSION_TESTS.md](docs/REGRESSION_TESTS.md)).

For a one-command onboarding sanity check on Unix-like systems:

```bash
bash scripts/check_contributor_bootstrap.sh
```

### Code Standards

**Backend (Python):**

- Type hints on all function signatures
- Docstrings on public functions (Google style)
- `async def` for I/O-bound operations
- Use `app_logger` for logging (not `print()`)
- Follow existing service decomposition patterns

### Commit Convention

```text
type: short description

types: feat, fix, refactor, docs, test, chore, perf
```

## Architecture Quick Reference

| Directory | Purpose |
| --- | --- |
| `backend/orchestration/` | Session orchestration (21 decomposed services) |
| `backend/orchestration/services/` | Service classes composing the orchestrator |
| `backend/cli/` | CLI entrypoint, REPL, init wizard, and session commands |
| `backend/ledger/` | Event sourcing, backpressure-aware stream, durable writer |
| `backend/persistence/` | File & DB storage implementations |
| `backend/gateway/` | Internal transport and integration boundaries; not a supported public product surface |
| `backend/engine/` | Production agent engine package |
| `backend/context/` | Context memory, compactors, RAG, vector store |
| `backend/core/` | Config (Pydantic), exceptions, schemas, logging |
| `backend/security/` | Security analyzer, input validation |

### Orchestration Service Map

The `SessionOrchestrator` (1267 LOC) delegates work to these services:

| Service | Responsibility |
| --- | --- |
| `LifecycleService` | Init, reset, config binding |
| `ActionExecutionService` | Get & execute next agent action |
| `ActionService` | Action intake, pending coordination |
| `RecoveryService` | Exception classification, retry orchestration |
| `TaskValidationService` | Finish-action validation pipeline |
| `CircuitBreakerService` | Circuit breaker pattern |
| `StuckDetectionService` | 6-strategy stuck/loop detection |
| `IterationGuardService` | Iteration limit control flags |
| `StateTransitionService` | Agent state machine transitions |
| `StepGuardService` | Pre-step guard checks |
| `StepPrerequisiteService` | Can-step prerequisite checks |
| `PendingActionService` | Pending action get/set/timeout |
| `ConfirmationService` | User confirmation flow |
| `SafetyService` | Safety validation |
| `RetryService` | Retry count & backoff |
| `ObservationService` | Observation event handling |
| `AutonomyService` | Autonomy controller init |
| `IterationService` | Iteration counting |
| `OrchestrationContext` | Shared facade for services |

### Key Patterns

- **Event sourcing**: All agent actions/observations go through `EventStream`
- **Backpressure**: `EventStream` caps in-flight events and applies backpressure
- **Compactor**: Memory management via `Compactor` with configurable strategies
- **State checkpoints**: Timestamped state snapshots (last 3 kept for crash recovery)
- **Circuit breaker**: Trips after consecutive errors/stuck detections
- **Safe defaults**: Budget capped at $5, circuit breaker ON, graceful shutdown ON

## Questions?

Open an issue with the relevant template if you need help or want to discuss a change.
