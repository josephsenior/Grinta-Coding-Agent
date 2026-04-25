# Grinta

![Grinta logo](logo.svg)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Install: pipx](https://img.shields.io/badge/install-pipx-brightgreen)](docs/INSTALL.md)
[![mypy: checked](https://img.shields.io/badge/mypy-checked-2A6DB2.svg)](https://mypy-lang.org/)
[![code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Tests](https://github.com/josephsenior/Grinta-Agent/actions/workflows/py-tests.yml/badge.svg)](https://github.com/josephsenior/Grinta-Agent/actions/workflows/py-tests.yml)
[![Lint](https://github.com/josephsenior/Grinta-Agent/actions/workflows/lint.yml/badge.svg)](https://github.com/josephsenior/Grinta-Agent/actions/workflows/lint.yml)
[![E2E](https://github.com/josephsenior/Grinta-Agent/actions/workflows/e2e-tests.yml/badge.svg)](https://github.com/josephsenior/Grinta-Agent/actions/workflows/e2e-tests.yml)
[![Codecov](https://codecov.io/gh/josephsenior/Grinta-Agent/branch/main/graph/badge.svg)](https://codecov.io/gh/josephsenior/Grinta-Agent)

> Local-first autonomous coding agent. Plan → execute → validate → finish.

<!-- trunk-ignore(markdownlint/MD033) -->
<p align="center">
  <img alt="Grinta in action" src="docs/grinta-demo.gif" width="720">
</p>

## Install in 30 seconds

```bash
pipx install grinta-ai
grinta init          # one-time wizard: pick provider + paste key
grinta               # launch the REPL in the current directory
```

That is the whole setup. The `grinta init` wizard auto-detects local Ollama and LM Studio servers and writes a working `settings.json` for you. Other install paths (uv, Homebrew, Scoop, Docker) are in [docs/INSTALL.md](docs/INSTALL.md).

## What you get

- **Task completion, not just file edits.** Validation gates and stuck detection block premature "done".
- **Model-agnostic.** OpenAI, Anthropic, Google, OpenRouter, Ollama, LM Studio — same prompt surface, same tools.
- **Local-first.** Code, sessions, checkpoints, and audit log all live under `.grinta/` in your project.
- **Strong safety rails.** Risk-classified actions, CRITICAL refusal gate, secret masking, and a session-wide audit trail.
- **Durable long sessions.** Event-stream ledger, automatic compaction, manual `/checkpoint`, and revert.
- **Lean TUI.** Cost / tokens / latency / breaker state visible in the HUD; rich slash commands (`/help`).

## Common slash commands

| Command       | What it does                                               |
| ------------- | ---------------------------------------------------------- |
| `/help`       | Full slash-command reference                               |
| `/cost`       | Tokens, calls, USD spent this session                      |
| `/diff`       | Workspace git changes (`--stat`, `--name-only`, `--patch`) |
| `/sessions`   | Recent sessions, with optional limit (`/sessions list 10`) |
| `/think`      | Toggle the optional reasoning scratchpad                   |
| `/checkpoint` | Snapshot the workspace (revertable)                        |
| `/status`     | Full HUD snapshot                                          |
| `/compact`    | Force context compaction now                               |

## Security boundary

Grinta executes actions on the local host. `hardened_local` adds stricter policy checks but **is not** sandboxing or process isolation. Read [docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md) **before pointing Grinta at code you do not trust** — for hostile codebases, run inside a VM or container.

## Architecture (high level)

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

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the deep dive.

## The story behind Grinta

Grinta is a single-author project, written and rewritten in public. The journey — what was killed, what was wrong, what got rebuilt — lives in the **Book of Grinta**:

[`preface-why-this-story-matters.md`](preface-why-this-story-matters.md) → [`00-the-meaning-of-grinta.md`](00-the-meaning-of-grinta.md) → … → [`31-the-myth-of-the-committee.md`](31-the-myth-of-the-committee.md). Full index in [BOOK_OF_GRINTA.md](BOOK_OF_GRINTA.md).

## Quick start (from source)

### Windows (recommended)

```powershell
.\START_HERE.ps1
```

### Linux / macOS / manual

1. Install dependencies **in this repo’s environment only** (creates/updates `.venv/`; do not rely on a global `pip install` mixed with unrelated tools):

```bash
uv sync --group browser
```

Optional dev/test tools: `uv sync --group dev --group test --group browser`.

1. Create local settings:

```bash
cp settings.template.json settings.json
```

1. Start the CLI:

```bash
uv run python -m backend.cli.entry
```

If you previously installed `grinta-ai` with `pip` into a **global** interpreter, remove it (`pip uninstall grinta-ai`) and use `uv run` from this repository so dependencies stay isolated.

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
