# Grinta

![Grinta logo](logo.svg)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![mypy: checked](https://img.shields.io/badge/mypy-checked-2A6DB2.svg)](https://mypy-lang.org/)
[![code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> Autonomous coding that closes the loop: plan, execute, validate, finish.

Grinta is an open-source, local-first autonomous coding agent built for real repository work. It reads code, plans multi-step execution, performs changes and command runs, validates results, and only finishes when completion criteria are satisfied.

## Project Description

Grinta focuses on task completion integrity, not just code generation. The runtime combines orchestration safeguards, local execution policy checks, and durable session state so long-running tasks can recover, self-correct, and stay within clear operating boundaries.

## Core Topics

- Autonomous coding workflows and task completion gates
- Session orchestration, retries, stuck detection, and circuit breakers
- Local-first execution with policy-driven safety controls
- Model-agnostic provider routing (cloud and local)
- Context compaction and durable run-state recovery for long sessions

## Why Grinta

- Task completion, not just file edits.
- Local-first runtime with strong safety guardrails.
- Durable long-session behavior with event-oriented state and recovery.
- Model-agnostic inference with direct provider support and OpenAI-compatible routing.
- Strong stuck detection and circuit-breaker behavior to avoid silent runaway loops.

## Security Boundary

Grinta currently executes actions on the local host.

- `hardened_local` adds stricter local execution policy checks.
- `hardened_local` is not sandboxing and not process isolation.

Use Grinta for trusted local workflows and repositories.

## Architecture (High Level)

```mermaid
graph TB
    User([User]) --> CLI[CLI: backend.cli.entry]
    CLI --> Orch[SessionOrchestrator]
    Orch --> Engine[Engine\nplanning + tool intent]
    Orch --> Pipe[Operation pipeline\nsafety + validation]
    Pipe --> Runtime[RuntimeExecutor\nlocal execution]
    Runtime --> Obs[Observations]
    Obs --> Orch
    Orch --> Ledger[EventStream / durability]
    Orch --> FinishGate[Task validation\nbefore finish]
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for implementation details.

## Quick Start

### Windows (recommended)

```powershell
.\START_HERE.ps1
```

### Linux / macOS / manual

1. Install dependencies:

```bash
uv sync
```

1. Create local settings:

```bash
cp settings.template.json settings.json
```

1. Start the CLI:

```bash
uv run python -m backend.cli.entry
```

### Optional raw HTTP backend (API/OpenAPI tooling)

Windows:

```powershell
.\start_backend.ps1
```

Cross-platform:

```bash
uv run python -m backend.execution.action_execution_server 3000 --working-dir .
```

Main endpoints:

- [http://localhost:3000/openapi.json](http://localhost:3000/openapi.json)
- [http://localhost:3000/server_info](http://localhost:3000/server_info)

### Docker (optional)

```bash
./docker_start.sh
```

Windows:

```powershell
.\DOCKER_START.ps1
```

## LLM Setup (`settings.json`)

Minimal config:

```json
{
  "llm_provider": "openai",
  "llm_model": "openai/gpt-4o-mini",
  "llm_api_key": "sk-...",
  "llm_base_url": ""
}
```

Common model ids:

- `openai/gpt-4o-mini`
- `anthropic/claude-sonnet-4-20250514`
- `google/gemini-2.5-pro`
- `ollama/llama3.2`

## Core Concepts

### Full task loop

Plan -> execute -> observe -> validate -> finish.

### Context compaction

Grinta uses compactor strategies to keep long sessions coherent under context limits.

### Reliability controls

Stuck detection, retry/recovery flows, and circuit breakers are built into orchestration.

### Completion integrity

Task validation can block finish calls when tracked work is incomplete.

## Documentation

- [User Guide](docs/USER_GUIDE.md)
- [Quick Start](docs/QUICK_START.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Developer Guide](docs/DEVELOPER.md)
- [Vocabulary](docs/VOCABULARY.md)
- [The Book of Grinta](docs/journey/README.md)
- [API Reference](openapi.json)
- [Contributing](CONTRIBUTING.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
