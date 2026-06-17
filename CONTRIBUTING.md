# Contributing to Grinta

Thank you for your interest in contributing to Grinta! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.12+
- Git
- `uv` (for source development)

### Getting Started

```bash
# Clone
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git
cd Grinta-Coding-Agent

# Install dependencies
python scripts/bootstrap_env.py dev-test

# First-run LLM setup (interactive; writes settings.json + .env)
uv run python -m backend.cli.entry init

# Start the CLI
uv run python -m backend.cli.entry
```

On Windows PowerShell you can use the convenience wrapper instead:

```powershell
.\START_HERE.ps1
```

That script syncs `dev-test` dependencies, checks local model servers, runs `init`
when `settings.json` is missing, then launches the CLI.

### Repo hygiene

- Treat `dist/`, `logs/`, local cache directories, and one-off diagnostics as disposable output, not source.
- Historical narrative docs under `docs/journey/` are intentionally not the current spec; use `README.md`, `docs/USER_GUIDE.md`, `docs/ARCHITECTURE.md`, and `docs/DEVELOPER.md` for current behavior.
- Prefer the current helper surfaces for local work:
  - `make help`
  - `make run-cli`
  - `make test-unit`
  - `make reliability-gate`

### Local configuration (source checkout)

- **`settings.json`** at the repository root holds non-secret defaults (`llm_model`,
  `llm_provider`, `${LLM_API_KEY}` placeholder).
- **`.env`** beside `settings.json` stores the real `LLM_API_KEY` (copy from
  [`.env.template`](.env.template); never commit secrets).
- **`APP_ROOT`** overrides where `settings.json` is resolved when you need an
  isolated config directory (for example smoke tests or multiple profiles).
- Installed runs (`pipx`, Homebrew, Scoop) use `~/.grinta/settings.json` instead
  of the repo root unless `APP_ROOT` is set.

Launching `grinta` or `uv run python -m backend.cli.entry` without a configured
key runs the same shared setup wizard as `grinta init`. Prefer `init` for an
explicit first-time setup step.

See also [docs/QUICK_START.md](docs/QUICK_START.md) and [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

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

**Required** GitHub Actions jobs differ by platform ([docs/CI.md](docs/CI.md)):

- **Linux (`gates-on-linux`):** full `backend/tests` corpus with coverage — match locally with:

```bash
python scripts/bootstrap_env.py dev-test
PYTHONPATH=. uv run pytest --cov=backend --cov-fail-under=75 backend/tests
```

- **Windows (`gates-on-windows`):** `backend/tests/unit` only — match locally with:

```bash
python scripts/bootstrap_env.py dev-test
PYTHONPATH=. uv run pytest backend/tests/unit
```

For day-to-day edits, `pytest backend/tests/unit` is usually enough before you push. Run the full Linux corpus when your change touches integration, e2e, stress, or cross-cutting orchestration paths.

Optional: `uv run pytest backend/tests/unit -q` for quieter output.

A bare `pytest` or `PYTHONPATH=. uv run pytest` from the repository root discovers all of **`backend/tests`** (unit, integration, e2e, stress, and so on) per [`pytest.ini`](pytest.ini). That run is much slower and may need extra services; use it when your change spans those tiers or before a large release.

The scheduled **Heavy / Integration Tests** job runs a marker-filtered slice (`pytest backend/tests -m "heavy or integration or benchmark"`). See [docs/CI.md](docs/CI.md#heavy--integration--benchmark-tier).

If your change touches the CLI, REPL, or orchestration hot paths, also run the [CLI regression workflow](.github/workflows/e2e-tests.yml) locally when possible (it may also run on PRs when files under `backend/`, `launch/`, etc. change).

For bugfix PRs, prefer adding a **regression test** next to the code you fixed (see [docs/REGRESSION_TESTS.md](docs/REGRESSION_TESTS.md)).

Dependency profiles are centralized in `scripts/bootstrap_env.py` (for example: `base`, `browser`, `dev`, `dev-test`, `dev-test-browser`).

For a one-command onboarding sanity check on Unix-like systems:

```bash
bash scripts/check_contributor_bootstrap.sh
```

For packaging / onboarding smoke (wheel + source non-interactive checks):

```bash
uv build --wheel
WHEEL_DIR=./dist ./scripts/smoke_install.sh
./scripts/smoke_source_onboarding.sh
```

Maintainers: see [docs/FRESH_MACHINE_ONBOARDING.md](docs/FRESH_MACHINE_ONBOARDING.md) for the GA fresh-machine checklist.

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

## Where to start in the codebase

New contributors: read **[docs/CONTRIBUTOR_MAP.md](docs/CONTRIBUTOR_MAP.md)** first.
It lists task-oriented entry points (CLI, orchestration, inference, MCP, tests)
without reading the whole tree. Day-to-day reference: [docs/DEVELOPER.md](docs/DEVELOPER.md).

## Architecture Quick Reference

| Directory | Purpose |
| --- | --- |
| `backend/orchestration/` | Session orchestration (decomposed services) |
| `backend/orchestration/services/` | Service classes composing the orchestrator |
| `backend/cli/` | CLI entrypoint, REPL, init wizard, and session commands |
| `backend/ledger/` | Event sourcing, backpressure-aware stream, durable writer |
| `backend/persistence/` | File & DB storage implementations |
| `backend/inference/` | Provider registry, LLM clients, model catalogs |
| `backend/integrations/` | MCP adapters (external tools) |
| `backend/engine/` | Production agent engine package |
| `backend/context/` | Context memory, compactors, RAG, vector store |
| `backend/core/` | Config (Pydantic), exceptions, schemas, logging |
| `backend/security/` | Security analyzer, input validation |

### Orchestration Service Map

The `SessionOrchestrator` delegates work to these services (implementation split
across mixins under `backend/orchestration/session_orchestrator_mixins/`):

| Service | Responsibility |
| --- | --- |
| `LifecycleService` | Init, reset, config binding |
| `ActionExecutionService` | Get & execute next agent action |
| `ActionService` | Action intake, pending coordination |
| `RecoveryService` | Exception classification, retry orchestration |
| `TaskValidationService` | Optional completion-quality warning pipeline |
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
