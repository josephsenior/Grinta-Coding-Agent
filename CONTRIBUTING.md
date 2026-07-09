# Contributing to Grinta

Thank you for your interest in contributing to Grinta! This guide will help you get started.

## Development Setup

### Prerequisites

- **Git** (to clone and contribute)
- **No manual Python or `uv`** — `START_HERE.ps1` / `start_here.sh` install the toolchain when missing

### Getting Started

```bash
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git Grinta
cd Grinta
bash start_here.sh
```

Windows PowerShell:

```powershell
.\START_HERE.ps1
```

That installs `uv` and Python 3.12 if needed, natively downloads `ripgrep`, syncs `dev-test` dependencies, runs setup when `settings.json` is missing, and installs the `grinta` CLI globally via `uv tool install`.

Manual equivalent:

```bash
uv python install 3.12
uv run python scripts/bootstrap_env.py dev-test
uv tool install -e .
```

**Windows note:** `make` targets in the Makefile are aimed at macOS, Linux, and WSL.
On native Windows, use `START_HERE.ps1` for the same happy path, and run pytest directly:

```powershell
uv run python scripts/bootstrap_env.py dev-test
$env:PYTHONPATH = '.'
uv run pytest backend/tests/unit/ --tb=short -q
```

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
key runs the same setup wizard as `grinta init` on first interactive launch.
Use `grinta init` when you want to configure without the TUI, or for `--non-interactive` / CI.

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

- **Linux (`gates-on-linux`):** unit corpus with coverage — match locally with:

```bash
uv run python scripts/bootstrap_env.py dev-test
PYTHONPATH=. uv run pytest --cov=backend --cov-fail-under=75 backend/tests/unit
```

- **Windows (`gates-on-windows` + `gates-on-windows-extended`):** unit corpus, then integration/e2e/stress — match locally with:

```bash
uv run python scripts/bootstrap_env.py dev-test
PYTHONPATH=. uv run pytest backend/tests/unit
PYTHONPATH=. uv run pytest backend/tests/integration backend/tests/e2e backend/tests/stress
```

- **macOS (`gates-on-macos` + `gates-on-macos-extended`):** same extended tier as Windows.

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

Maintainers: see [docs/onboarding_reports/](docs/onboarding_reports/) for GA fresh-machine evidence.

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
across mixins under `backend/orchestration/mixins/`):

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
