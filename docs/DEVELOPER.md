# Grinta Developer Guide

Internal reference for contributors working on Grinta internals.

For **user-facing** documentation, see [USER_GUIDE.md](USER_GUIDE.md).
For **architecture overview**, see [ARCHITECTURE.md](ARCHITECTURE.md).
For **contribution workflow**, see [CONTRIBUTING.md](CONTRIBUTING.md).
For **design history and decision rationale**, see [The Book of Grinta](journey/README.md).

## Table of Contents

1. [Project Layout](#project-layout)
2. [Request Lifecycle](#request-lifecycle)
3. [Orchestration Services](#orchestration-services)
4. [Ledger Internals](#ledger-internals)
5. [LLM Layer](#llm-layer)
6. [Context Memory & Compactors](#context-memory--compactors)
7. [Safety Systems](#safety-systems)
8. [Adding a New Feature](#adding-a-new-feature)
9. [Testing Guide](#testing-guide)
10. [Common Pitfalls](#common-pitfalls)

## Project Layout

```text
client/                # Python HTTP + Socket.IO client (GrintaClient) for tests/scripts
backend/
├── gateway/           # FastAPI app, routes, middleware, sessions, adapters
│   ├── adapters/      # I/O and serialization adapters
│   ├── cli/           # CLI entrypoints and helpers
│   └── integrations/  # External gateway integrations (including MCP)
├── orchestration/     # Session orchestrator, services, safety systems
│   ├── services/      # Decomposed orchestration responsibilities
│   ├── state/         # Run-state management
│   ├── orchestration_config.py  # Extracted OrchestrationConfig + OrchestrationServices
│   ├── stuck.py       # 6-strategy stuck detection
│   └── agent_circuit_breaker.py  # Anomaly-based safety pause
├── engine/            # Main Orchestrator engine with tool-facing helpers
├── ledger/            # Record ledger with WAL + backpressure
│   ├── action/        # Agent actions (commands, edits, messages)
│   ├── observation/   # Action results (output, errors, diffs)
│   ├── stream.py      # Ledger (`EventStream`) with WAL + backpressure
│   ├── stream_stats.py # Extracted aggregated stream statistics
│   └── durable_writer.py  # Batch-mode event persistence (16-event batches)
├── core/              # Config, logging, exceptions
│   └── config/        # Layered TOML + env config loading
├── context/           # Context memory + compactors
│   ├── conversation_memory.py  # Event→LLM message conversion
│   ├── message_formatting.py   # Type-check utils & message formatting
│   ├── context_tracking.py     # Decision/anchor/vector memory tracking
│   └── compactor/strategies/   # 8 compactor strategies incl. auto-selector
├── execution/         # Local command execution and runtime policy enforcement
├── inference/         # LLM abstraction (direct SDK clients)
├── knowledge/         # Knowledge base logic (RAG)
├── persistence/       # Persistence layer (SQLite, file-based)
├── playbooks/         # Built-in task playbooks (.md files)
├── security/          # Command analysis + safety config
├── validation/        # Validation and code-quality checks
└── tests/             # Test suites (unit, integration, e2e, stress)
```

## Request Lifecycle

```text
User Input (Web UI / client)
  → GrintaClient.send_message()
    → Socket.IO / HTTP POST /api/conversations/{id}/messages
      → SessionManager.get_or_create_session()
        → SessionOrchestrator.run_loop()
          → Engine.generate_action()     # LLM call → Action
          → Runtime.execute(action)       # Local execution + policy enforcement → Observation

Note: the current runtime is not sandboxed. `hardened_local` is a stricter policy profile for local execution, not isolation.
          → Ledger.add_record()           # Persist to WAL (`EventStream.add_event()` in code)
          → StuckDetector.is_stuck()      # 6-strategy check
          → CircuitBreaker.check()        # Safety gate
        ← Stream observations back via Socket.IO
      ← HTTP response with conversation state
```

## Orchestration Services

The `SessionOrchestrator` delegates to 21 specialized services via `OrchestrationContext`:

| Service | Responsibility |
| --- | --- |
| `ActionService` | Parse and validate agent actions |
| `AgentDelegateService` | Sub-agent delegation |
| `BudgetService` | Token/cost budget enforcement |
| `CircuitBreakerService` | Safety pause on anomalies |
| `CommandService` | Command execution in runtime |
| `CondenserService` | Context compaction triggers |
| `DelegationService` | Multi-agent task splitting |
| `ErrorRecoveryService` | Classify + recover from errors |
| `GracefulShutdownService` | Final turn on limit/budget hit |
| `HealthService` | Agent health checks |
| `InitializationService` | Bootstrap agent state |
| `IterationService` | Main loop iteration logic |
| `ObservationService` | Process execution results |
| `ProgressService` | Track task progress |
| `ReplayService` | Transcript replay |
| `RollbackService` | Undo failed actions |
| `SafetyService` | Pre-execution safety checks |
| `SecurityService` | Command risk analysis |
| `StatusService` | Agent state tracking |
| `StuckDetectionService` | Stuck loop detection |
| `TruncationService` | History truncation on overflow |

### Adding a New Service

1. Create `backend/orchestration/services/my_service.py`
2. Accept `OrchestrationContext` in `__init__`
3. Add to `OrchestrationContext` initialization
4. Write tests in `backend/tests/unit/orchestration/test_my_service.py`

```python
from backend.orchestration.services.orchestration_context import OrchestrationContext

class MyService:
    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    @property
    def controller(self):
        return self._context.get_controller()

    def do_something(self) -> None:
        # Implementation
        pass
```

## Operation Pipeline

The `SessionOrchestrator` executes tools through an operation pipeline (`backend/orchestration/tool_pipeline.py`, `ToolInvocationPipeline` in the current codebase). This allows intercepting tool calls for validation, safety, and telemetry.

### Middleware Chain

The pipeline runs in four stages: `plan` → `verify` → `execute` → `observe`.

| Middleware | Stage | Responsibility |
| --- | --- | --- |
| `PlanningMiddleware` | Plan | **Auto-Planning**: Injects a planning directive (`[AUTO-PLAN]`) if task complexity is high. |
| `SafetyValidatorMiddleware` | Verify | **Safety**: Checks actions against the safety policy (e.g., blocking `rm -rf`). |
| `ReflectionMiddleware` | Verify | **Sanity Check**: Verifies file edits (syntax) and commands (destructive patterns) before execution. |
| `ConflictDetectionMiddleware` | Verify | **State Integrity**: Blocks repeated file edits if the file hasn't been read/verified in between. |
| `CircuitBreakerMiddleware` | Execute/Observe | **Reliability**: Tracks error rates and trips the circuit breaker on failures. |
| `CostQuotaMiddleware` | Plan/Observe | **Budget**: Tracks token usage and enforces budget limits. |
| `ErrorPatternMiddleware` | Observe | **Self-Correction**: Auto-queries the `error_patterns` DB for known fixes when an error occurs. |
| `EditVerifyMiddleware` | Observe | **Verification**: Appends a hint to read file content after edits to ensure changes were applied correctly. |
| `TelemetryMiddleware` | All | **Observability**: Emits telemetry events for each stage. |
| `LoggingMiddleware` | All | **Debugging**: detailed logs. |

## Ledger Internals

### Ledger (`EventStream`)

The record system is event-sourced: all state changes flow through the ledger (`EventStream`).

- **WAL Recovery**: Events are written to a write-ahead log before processing.
  On crash recovery, the WAL is replayed to restore state.
- **Backpressure**: When the queue exceeds `hwm_ratio` (default 0.7), producers
  are slowed. At capacity, the `drop_policy` kicks in (`drop_oldest` / `drop_newest` / `block`).
- **Serialization**: Events serialize to JSON with type discriminators for
  polymorphic deserialization.

### Event Types

```text
Event
├── Action (agent → runtime)
│   ├── CmdRunAction        # Shell command execution
│   ├── FileEditAction      # File modification
│   ├── FileWriteAction     # File creation
│   ├── MessageAction       # Agent ↔ user messages
│   └── NullAction          # No-op
└── Observation (runtime → agent)
    ├── CmdOutputObservation # Command output + exit code
    ├── FileEditObservation  # Edit confirmation
    ├── ErrorObservation     # Error details
    └── AgentCondensationObservation  # Memory condensation marker
```

## LLM Layer

### Direct Client Architecture

Grinta uses **direct SDK clients** (not litellm) for stability. For the rationale behind this decision, see [The Model-Agnostic Reckoning](journey/10-model-agnostic-reckoning.md).

```text
LLM (backend/inference/llm.py)
├── RetryMixin          # Exponential backoff with jitter
├── DebugMixin          # Request/response logging
├── Metrics             # Token/cost tracking
└── DirectLLMClient
    ├── OpenAIClient    # OpenAI + OpenAI-compatible (Ollama, LM Studio, vLLM)
    ├── AnthropicClient # Claude models
    └── GeminiClient    # Google models
```

### Provider Routing

`get_direct_client()` routes based on model name:

- `"claude-*"` or `"anthropic/*"` → `AnthropicClient`
- `"gemini/*"` or `"google/*"` → `GeminiClient`
- `"grok*"` or `"xai/*"` → `OpenAIClient` with xAI base URL
- `"ollama/*"` → `OpenAIClient` with prefix stripping + Ollama base URL
- Everything else → `OpenAIClient` (default, handles custom `base_url`)

### Adding a New Provider

1. Create client class extending `DirectLLMClient` in `direct_clients.py`
2. Implement `completion()`, `acompletion()`, `astream()`
3. Add routing condition to `get_direct_client()`
4. Add model features to `model_features.py`

## Context Memory & Compactors

### Compactor Pipeline

When context exceeds limits, compactors compress history. For the full evolution story, see [The Context War](journey/04-the-context-war.md).

```text
Full History → Compactor → Compressed History → LLM
```

**8 available compactor strategies:**

| Type | Strategy | Cost | Quality |
| --- | --- | --- | --- |
| `noop` | Keep everything | Free | Perfect (until overflow) |
| `recent` | Sliding window | Free | Loses old context |
| `observation_masking` | Mask old observations | Free | Preserves structure |
| `smart` | Auto-select best | Varies | Adaptive |
| `auto` | Task-signal-based selection | Varies | Context-aware |
| `amortized` | Gradual pruning | Free | Balanced |
| `structured` | LLM structured summary | $$ | Best quality |
| `pipeline` | Chained compactors | Varies | Composable |

### Adding a New Compactor

1. Create class in `backend/context/compactor/`
2. Extend the `Compactor` base class
3. Register in the compactor factory
4. Add config schema in `backend/core/config/compactor_config.py`
5. Add tests

## Safety Systems

### Three Layers of Protection

For cross-platform execution challenges that shaped the security layer, see [The Console Wars](journey/11-the-console-wars.md).

```text
Layer 1: Pre-execution (CommandAnalyzer)
  → Analyzes commands before execution
  → Blocks critical: rm -rf /, dd, format, mkfs
  → Flags high-risk: sudo, chmod +s, curl|bash
  → Detects encoded/obfuscated commands

Layer 2: Runtime (CircuitBreaker)
  → Monitors error rates and patterns
  → Pauses on: 5 consecutive errors, 10 high-risk actions, 50% error rate
  → Stops on: 3 stuck detections
  → Exponential backoff on service failures

Layer 3: Detection (StuckDetector)
  → 6 pattern detection strategies
  → Semantic loop analysis (intent diversity + failure rate)
  → Token repetition detection
  → Cost acceleration monitoring
```

### Security Risk Levels

| Level | Examples | Behavior |
| --- | --- | --- |
| LOW | `ls`, `cat`, `echo`, `pip install` | Always allowed |
| MEDIUM | `eval $VAR`, `python -c "..."` | Allowed with logging |
| HIGH | `rm -rf`, `sudo bash`, `chmod +s` | Blocked or requires approval |
| CRITICAL | `dd if=/dev/zero`, `mkfs`, `:(){ :\|:& };:` | Always blocked |

## Adding a New Feature

### Checklist

1. **Config**: Add settings to `backend/core/config/` with defaults
2. **Implementation**: Follow existing patterns in the relevant module
3. **Records**: If state-changing, emit them through the ledger (`EventStream`)
4. **Safety**: If executing commands, integrate with `CommandAnalyzer`
5. **Tests**: Unit tests + integration tests
6. **Docs**: Update relevant README or guide

### Style Guidelines

- **Type hints** on all function signatures
- **Docstrings** on public functions (Google style)
- **Radon complexity** target: < 5 per function
- **No bare exceptions**: Always catch specific types
- **Async by default**: Use `async def` for I/O operations
- **Pydantic models** for config and data transfer

## Testing Guide

Grinta maintains a high standard of code quality with a focus on comprehensive unit test coverage for core modules. Recent efforts have achieved **95%+ coverage** across the `backend/core` infrastructure:

- `backend/core/loop.py`: **100%**
- `backend/core/logger.py`: **~95%**
- `backend/core/config/utils.py`: **99%+**
- `backend/core/bootstrap/setup.py`: **98%+**
- `backend/core/bootstrap/main.py`: **~80%** (Active expansion)

### Test Structure

```text
backend/tests/
├── unit/              # Fast, isolated unit tests
│   ├── orchestration/ # Session orchestrator and service tests
│   ├── core/          # Core config, errors, utils tests
│   ├── engine/        # Engine tests
│   ├── execution/     # Runtime execution tests
│   ├── gateway/       # FastAPI, routes, middleware, and session tests
│   ├── governance/    # Governance tests
│   ├── inference/     # LLM client tests
│   ├── ledger/        # Record ledger tests
│   ├── knowledge/     # Knowledge base tests
│   ├── context/       # Context memory and compactor tests
│   ├── persistence/   # Storage and persistence tests
│   ├── playbooks/     # Playbook tests
│   ├── security/      # Security & command analysis tests
│   ├── telemetry/     # Telemetry tests
│   ├── tools/         # Tool tests
│   ├── client/        # Tests for client.GrintaClient
│   ├── utils/         # Utility tests
│   └── validation/    # Validation and code-quality tests
├── integration/       # Multi-component integration tests
├── e2e/               # End-to-end tests (require running server)
└── stress/            # Load and pressure tests
```

**Convention:** Every test file lives under its source module's subfolder
(e.g., tests for `backend/context/` go in `backend/tests/unit/context/`),
not in the root `unit/` directory.

### Running Tests

```bash
# All tests
uv run pytest

# Unit tests only (fast)
uv run pytest backend/tests/unit/ -v

# Integration tests
uv run pytest backend/tests/integration/ -v

# With coverage
uv run pytest --cov=backend --cov-report=html

# Specific test file
uv run pytest backend/tests/unit/utils/test_circuit_breaker.py -v
```

### Writing Good Tests

```python
import pytest
from unittest.mock import MagicMock, AsyncMock

class TestMyFeature:
    """Group related tests in classes."""

    def test_basic_behavior(self):
        """Test the happy path."""
        result = my_function(valid_input)
        assert result.success is True

    def test_edge_case(self):
        """Test boundary conditions."""
        result = my_function(edge_input)
        assert result.handled_gracefully is True

    @pytest.mark.asyncio
    async def test_async_operation(self):
        """Test async code."""
        result = await my_async_function()
        assert result is not None

    @pytest.mark.parametrize("input,expected", [
        ("valid", True),
        ("invalid", False),
        ("", False),
    ])
    def test_parametrized(self, input, expected):
        """Test multiple inputs efficiently."""
        assert validate(input) == expected
```

## Common Pitfalls

### 1. Model Context Protocol (MCP)

Grinta's internal MCP logic lives under `backend/gateway/integrations/mcp/`. Always import
from Grinta's integration package (not the bare `mcp` SDK package) when using
Grinta-specific client or tool-registry utilities.

### 2. Event Loop Management

Async tests use `pytest-asyncio` in **STRICT mode** — every async test must be decorated with `@pytest.mark.asyncio`. The asyncio mode is set globally via `pytest.ini`; do not override it per-file.

### 3. Circuit Breaker State

Circuit breaker state persists across iterations within a session. If testing
breaker behavior, always call `breaker.reset()` in teardown.

### 4. Compactor Side Effects

LLM-based compactors make real API calls unless mocked. Always mock the LLM
client in unit tests for compactors that use the current `llm_config` compactor wiring.

### 5. Config Loading

Config loads from `config.toml` → env vars → defaults. In tests, use
`monkeypatch` to set env vars rather than modifying `config.toml`.

### 6. WAL Files

The event stream WAL creates files in the working directory. Tests should
use `tmp_path` fixture to avoid polluting the repo.

---

## Async Scheduling Rules

Grinta mixes synchronous callbacks, async coroutines, and background-thread
dispatch.  Getting the threading/loop boundary wrong is the single most
common source of "agent stuck" bugs.  **Every contributor must follow the
rules below.**

### The Problem

The ledger (`EventStream`) dispatches subscriber callbacks inside a `ThreadPoolExecutor`.
Those threads have **no running asyncio event loop**.  If a callback creates
a coroutine and tries to schedule it, there are only two safe options:

1. The thread already has a running loop (rare) → `asyncio.create_task()`.
2. The thread does **not** have a running loop (common) → the coroutine must
   be sent to a loop that **is** running somewhere else.

Creating a throw-away loop with `asyncio.new_event_loop()` +
`run_until_complete()` is **never safe** for background coroutines.  The
disposable loop is destroyed the moment `run_until_complete` returns; any
`await` that yields control inside the coroutine will never resume.

### The Solution: `run_or_schedule` and the Main Loop Registry

All background coroutine scheduling goes through one function:

```python
from backend.utils.async_utils import run_or_schedule

# Inside a ledger (`EventStream`) callback, runtime handler, context listener, etc.:
run_or_schedule(self._on_event(event))
```

`run_or_schedule` does the right thing automatically:

| Situation | What happens |
| --- | --- |
| Caller is in a running event loop | Creates a tracked task on that loop |
| Caller is in a background thread, main loop registered | Uses `call_soon_threadsafe` to schedule on the main loop |
| No loop anywhere (CLI fallback) | Creates a disposable loop + `run_until_complete` (blocking) |

The main loop is registered once at application startup:

```python
# backend/gateway/app.py — inside _lifespan():
from backend.utils.async_utils import set_main_event_loop
set_main_event_loop()  # captures asyncio.get_running_loop()
```

### Rules

1. **Never call `asyncio.new_event_loop()` to run a background coroutine.**
   Use `run_or_schedule()` instead.

2. **Never call `asyncio.create_task()` from a background thread.**
   There is no running loop in that thread.  Use `run_or_schedule()` or
   `loop.call_soon_threadsafe()` targeting the main loop.

3. **If you need the result of a coroutine from a sync context**, use
   `call_async_from_sync()` (which creates a proper loop in a thread-pool
   worker and blocks until completion).

4. **If you need to run sync/blocking code from an async context**, use
   `call_sync_from_async()` or `loop.run_in_executor()`.

5. **`step()` has its own scheduling path.**
  `SessionOrchestrator.step()` is called from ledger (`EventStream`) dispatch threads.
   It uses `self._main_loop.call_soon_threadsafe(self._create_step_task)` to
   schedule the step task directly on the main loop.  This predates the
   generalized `run_or_schedule` fix and is kept for clarity.

6. **Always test with the real event loop.**  Unit tests that mock
   `asyncio.get_running_loop()` or create isolated loops won't catch
   thread-boundary bugs.  The e2e test suite (`backend/tests/e2e/`) exercises
   the real dispatch chain.

### Diagram

```text
EventStream._dispatch_event()  # current implementation name
        │
        ▼
  ThreadPoolExecutor thread (no event loop)
        │
        ▼
    subscriber.on_event(event)          e.g. SessionOrchestrator.on_event
        │
        ▼
  run_or_schedule(coro)               backend/utils/async_utils.py
        │
        ├─ has running loop? ───────► create_tracked_task(coro)
        │
        ├─ main loop registered? ──► main_loop.call_soon_threadsafe(
        │                              _schedule_on_main_loop, coro)
        │
        └─ fallback ───────────────► new_event_loop().run_until_complete(coro)
                                      (blocking, only for CLI / tests)
```

---

## Windows Platform Notes

Grinta runs on Windows with `ProactorEventLoop` (Python 3.12 default).
Several areas need special attention:

### MCP stdio Servers

Stdio-based MCP servers are **disabled by default** on Windows due to
`ProactorEventLoop` limitations with subprocess pipes.  Set the environment
variable `APP_ENABLE_WINDOWS_MCP=1` to override.  When servers are
skipped, a warning is logged with their names.

### PowerShell Path Escaping

File-read commands generated by the orchestrator use PowerShell on Windows.
Paths are escaped via `_escape_ps_path()` which backtick-escapes `` ` ``,
`"`, and `$` — the characters special inside PowerShell double-quoted
strings.  Always use this function (or quote paths) when building shell
commands for Windows.

### Running the E2E Test Suite on Windows

```powershell
# Start the raw HTTP backend
.\start_backend.ps1

# In another terminal:
python -m pytest backend/tests/e2e/test_agent_loop_e2e.py -m integration -v
```
