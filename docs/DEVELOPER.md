# Forge Developer Guide

Internal reference for contributors working on Forge internals.

For **user-facing** documentation, see [USER_GUIDE.md](USER_GUIDE.md).
For **architecture overview**, see [ARCHITECTURE.md](ARCHITECTURE.md).
For **contribution workflow**, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Table of Contents

1. [Project Layout](#project-layout)
2. [Request Lifecycle](#request-lifecycle)
3. [Controller Services](#controller-services)
4. [Event System Internals](#event-system-internals)
5. [LLM Layer](#llm-layer)
6. [Memory & Condensers](#memory--condensers)
7. [Safety Systems](#safety-systems)
8. [Adding a New Feature](#adding-a-new-feature)
9. [Testing Guide](#testing-guide)
10. [Common Pitfalls](#common-pitfalls)

## Project Layout

```
backend/
├── adapters/          # I/O and serialization adapters
├── controller/        # Agent loop, 21 services, safety systems
│   ├── services/      # Decomposed controller responsibilities
│   ├── state/         # Agent state management
│   ├── controller_config.py  # Extracted ControllerConfig + ControllerServices
│   ├── stuck.py       # 6-strategy stuck detection
│   └── agent_circuit_breaker.py  # Anomaly-based safety pause
├── core/              # Config, logging, exceptions
│   └── config/        # Layered TOML + env config loading
├── engines/           # LLM prompt engines
│   └── orchestrator/  # Main Orchestrator engine with 23 tools
├── events/            # Event-sourced event system
│   ├── action/        # Agent actions (commands, edits, messages)
│   ├── observation/   # Action results (output, errors, diffs)
│   ├── stream.py      # EventStream with WAL + backpressure
│   ├── stream_stats.py # Extracted aggregated stream statistics
│   └── durable_writer.py  # Batch-mode event persistence (16-event batches)
├── knowledge/         # Knowledge base logic (RAG)
├── llm/               # LLM abstraction (direct SDK clients)
├── mcp/               # MCP tool integration
├── memory/            # Conversation memory + condensers
│   ├── conversation_memory.py  # Event→LLM message conversion
│   ├── message_formatting.py   # Type-check utils & message formatting
│   ├── context_tracking.py     # Decision/anchor/vector memory tracking
│   └── condenser/impl/         # 13 condenser strategies incl. auto-selector
├── playbooks/         # Built-in task playbooks (.md files)
├── runtime/           # Sandboxed command execution
├── security/          # Command analysis + safety config
├── server/            # FastAPI app, routes, middleware, sessions
├── storage/           # Persistence layer (SQLite, file-based)
├── tui/               # Textual terminal UI
│   ├── screens/       # Home, Chat, Settings, Diff, Help screens
│   ├── widgets/       # Reusable UI components
│   ├── client.py      # Socket.IO client with exponential backoff & heartbeat
│   └── __main__.py    # Entry point with --dev hot-reload flag
└── tests/             # Test suites (unit, integration, e2e, stress)
```

## Request Lifecycle

```
User Input (TUI/API)
  → ForgeClient.send_message()
    → Socket.IO / HTTP POST /api/conversations/{id}/messages
      → SessionManager.get_or_create_session()
        → AgentController.run_loop()
          → Engine.generate_action()     # LLM call → Action
          → Runtime.execute(action)       # Sandboxed execution → Observation
          → EventStream.add_event()       # Persist to WAL
          → StuckDetector.is_stuck()      # 6-strategy check
          → CircuitBreaker.check()        # Safety gate
        ← Stream observations back via Socket.IO
      ← HTTP response with conversation state
```

## Controller Services

The `AgentController` delegates to 21 specialized services via `ControllerContext`:

| Service | Responsibility |
| --- | --- |
| `ActionService` | Parse and validate agent actions |
| `AgentDelegateService` | Sub-agent delegation |
| `BudgetService` | Token/cost budget enforcement |
| `CircuitBreakerService` | Safety pause on anomalies |
| `CommandService` | Command execution in runtime |
| `CondenserService` | Memory condensation triggers |
| `DelegationService` | Multi-agent task splitting |
| `ErrorRecoveryService` | Classify + recover from errors |
| `GracefulShutdownService` | Final turn on limit/budget hit |
| `HealthService` | Agent health checks |
| `InitializationService` | Bootstrap agent state |
| `IterationService` | Main loop iteration logic |
| `ObservationService` | Process execution results |
| `ProgressService` | Track task progress |
| `ReplayService` | Trajectory replay |
| `RollbackService` | Undo failed actions |
| `SafetyService` | Pre-execution safety checks |
| `SecurityService` | Command risk analysis |
| `StatusService` | Agent state tracking |
| `StuckDetectionService` | Stuck loop detection |
| `TruncationService` | History truncation on overflow |

### Adding a New Service

1. Create `backend/controller/services/my_service.py`
2. Accept `ControllerContext` in `__init__`
3. Add to `ControllerContext` initialization
4. Write tests in `backend/tests/unit/controller/test_my_service.py`

```python
from backend.controller.services.controller_context import ControllerContext

class MyService:
    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    @property
    def controller(self):
        return self._context.get_controller()

    def do_something(self) -> None:
        # Implementation
        pass
```

## Tool Invocation Pipeline

The `AgentController` executes tools through a middleware pipeline (`backend/controller/tool_pipeline.py`). This allows intercepting tool calls for validation, safety, and telemetry.

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

## Event System Internals

### EventStream

The event system is **event-sourced**: all state changes flow through `EventStream`.

- **WAL Recovery**: Events are written to a write-ahead log before processing.
  On crash recovery, the WAL is replayed to restore state.
- **Backpressure**: When the queue exceeds `hwm_ratio` (default 0.7), producers
  are slowed. At capacity, the `drop_policy` kicks in (`drop_oldest` / `drop_newest` / `block`).
- **Serialization**: Events serialize to JSON with type discriminators for
  polymorphic deserialization.

### Event Types

```
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

Forge uses **direct SDK clients** (not litellm) for stability:

```
LLM (backend/llm/llm.py)
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

## Memory & Condensers

### Condenser Pipeline

When context exceeds limits, condensers compress history:

```
Full History → Condenser → Compressed History → LLM
```

**13 available strategies:**

| Type | Strategy | Cost | Quality |
| --- | --- | --- | --- |
| `noop` | Keep everything | Free | Perfect (until overflow) |
| `recent` | Sliding window | Free | Loses old context |
| `observation_masking` | Mask old observations | Free | Preserves structure |
| `llm` | LLM summarization | $ | Good summaries |
| `smart` | Auto-select best | Varies | Adaptive |
| `auto` | Task-signal-based selection | Varies | Context-aware |
| `amortized` | Gradual forgetting | Free | Balanced |
| `llm_attention` | LLM-scored relevance | $$ | Best quality |
| `semantic` | Embedding similarity | $ | Context-aware |
| `hybrid` | Multi-strategy | $$ | Most robust |
| `pipeline` | Chained condensers | Varies | Composable |
| `block_compress` | Block-level compression | $ | Efficient |
| `attention` | Attention scoring | $ | Focus-aware |

### Adding a New Condenser

1. Create class in `backend/memory/condenser/`
2. Extend `Condenser` base class
3. Register in condenser factory
4. Add config schema in `backend/core/config/condenser_config.py`
5. Add tests

## Safety Systems

### Three Layers of Protection

```
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
3. **Events**: If state-changing, emit events through `EventStream`
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

Forge maintains a high standard of code quality with a focus on comprehensive unit test coverage for core modules. Recent efforts have achieved **95%+ coverage** across the `backend/core` infrastructure:

- `backend/core/loop.py`: **100%**
- `backend/core/logger.py`: **~95%**
- `backend/core/config/utils.py`: **99%+**
- `backend/core/setup.py`: **104% (aggregated)** -> wait, I'll just say 98%+
- `backend/core/setup.py`: **98%+**
- `backend/core/main.py`: **~80%** (Active expansion)

### Test Structure

```
backend/tests/
├── unit/              # Fast, isolated unit tests
│   ├── controller/    # Controller service tests
│   ├── core/          # Core config, errors, utils tests
│   ├── engines/       # Engine tests
│   ├── events/        # Event system tests
│   ├── knowledge/     # Knowledge base tests
│   ├── code_quality/  # Code quality (linter) tests
│   ├── llm/           # LLM client tests
│   ├── mcp/           # MCP integration tests
│   ├── memory/        # Memory & condenser tests
│   ├── review/        # Code review tests
│   ├── runtime/       # Runtime tests
│   ├── security/      # Security & command analysis tests
│   ├── server/        # Server, middleware, routes tests
│   ├── storage/       # Storage layer tests
│   ├── telemetry/     # Telemetry tests
│   ├── tools/         # Tool tests
│   ├── tui/           # TUI client & screen tests
│   ├── utils/         # Utility tests
│   └── validation/    # Validation tests
├── integration/       # Multi-component integration tests
├── e2e/               # End-to-end tests (require running server)
└── stress/            # Load and pressure tests
```

**Convention:** Every test file lives under its source module's subfolder
(e.g., tests for `backend/memory/` go in `backend/tests/unit/memory/`),
not in the root `unit/` directory.

### Running Tests

```bash
# All tests
poetry run pytest

# Unit tests only (fast)
poetry run pytest backend/tests/unit/ -v

# Integration tests
poetry run pytest backend/tests/integration/ -v

# With coverage
poetry run pytest --cov=backend --cov-report=html

# Specific test file
poetry run pytest backend/tests/unit/test_circuit_breaker.py -v

# Windows-specific
poetry run pytest -c pytest-windows.ini
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
The `backend/mcp_integration/` directory contains Forge's internal MCP logic. Always import
from `backend.mcp_integration` (not `mcp`) when using Forge's specific client or tool
registry utilities. The bare `mcp` package refers to the official SDK.

### 2. Event Loop Management
Tests use a custom `pytest_pyfunc_call` hook for async tests instead of
`pytest-asyncio`. Use the `event_loop` fixture for explicit loop control.

### 3. Circuit Breaker State
Circuit breaker state persists across iterations within a session. If testing
breaker behavior, always call `breaker.reset()` in teardown.

### 4. Condenser Side Effects
LLM-based condensers make real API calls unless mocked. Always mock the LLM
client in unit tests for condensers that use `llm_config`.

### 5. Config Loading
Config loads from `config.toml` → env vars → defaults. In tests, use
`monkeypatch` to set env vars rather than modifying `config.toml`.

### 6. WAL Files
The event stream WAL creates files in the working directory. Tests should
use `tmp_path` fixture to avoid polluting the repo.
