# Grinta User Guide

This guide reflects the current CLI-first Grinta workflow.

Canonical startup:

- Installed CLI: `grinta`
- Source checkout: `uv run python -m backend.cli.entry`

## Table of Contents

1. Installation
2. Configuration (incl. pending actions, terminal, Stop/Cancel, Ctrl+C)
3. First Task
4. LLM Provider Setup
5. Safety and Runtime Model
6. Useful Commands

---

## Installation

### Prerequisites

- Python 3.12+
- uv
- Git

### Install

For a normal user install:

```bash
pipx install grinta-ai
grinta init
grinta
```

For source development:

```bash
uv sync
```

### Create local settings

```bash
uv run python -m backend.cli.entry init
```

On Windows PowerShell:

```powershell
uv run python -m backend.cli.entry init
```

---

## Configuration

Grinta supports layered configuration. Installed runs use `~/.grinta/settings.json`; source checkouts use the repository `settings.json`; `APP_ROOT` can intentionally override the settings root.

### Minimal settings.json

```json
{
  "llm_provider": "openai",
  "llm_model": "openai/gpt-4o-mini",
  "llm_api_key": "${LLM_API_KEY}",
  "llm_base_url": ""
}
```

Notes:

- `llm_provider` can be omitted when `llm_model` includes a provider prefix.
- `llm_base_url` is optional and useful for OpenAI-compatible proxies.
- Put the real key in a sibling `.env` file or your shell environment as `LLM_API_KEY`.
- Environment variables still work and can override advanced settings.

Common environment variables:

- `LLM_API_KEY`
- `LLM_MODEL`
- `APP_ROOT` (intentionally overrides where `settings.json` is resolved)

### Pending actions and the terminal manager

The default `pending_action_timeout` (in `settings.json`) is the base watchdog for
how long the orchestration waits for a tool’s observation. Interactive shell
commands (`cmd_run`) and `terminal_manager` (PTY) actions use a **higher built-in
floor** (aligned with long-running installs and slow PTY startup), so they are
less likely to hit a spurious “pending action” timeout at the default.

If you still see timeouts for other tools, or you need an even longer global
window, increase `pending_action_timeout` in `settings.json` (or set it to `0` to
disable the watchdog, which is not recommended for routine use).

### REPL: Ctrl+C

At the **input prompt**, Ctrl+C is ignored as an exit (use `/quit` or `exit` to
leave). **While the agent is running**, Ctrl+C is intended to cancel the run; on
Windows with some terminals, you may need to press it more than once for the
interrupt to register.

### Stop, Ctrl+C, and in-flight tool calls

If you press **Stop** or **Ctrl+C** while a tool call is still running, the
orchestration may show an error such as “Run cancelled … before this tool
finished.” That means **you interrupted the step**, not that the tool (or
`terminal_manager`) is broken. A separate message is used when the **runtime**
crashes or restarts without you cancelling.

Multi-step tools (for example `terminal_manager`: **open** → **read** / **input**)
need each step to complete unless you intend to cancel; stopping mid-sequence
leaves tasks incomplete and can show that message for the interrupted call.

---

## First Task

### Start the CLI

```bash
uv run python -m backend.cli.entry
```

### Ask for work

Example:

```text
Add tests for backend/inference/provider_resolver.py and run them.
```

The agent will plan, execute tools, validate progress, and only finish when completion checks pass.

### Runtime state

Session and runtime state are stored under:

- `~/.grinta/workspaces/<id>/storage`

---

## LLM Provider Setup

Grinta supports direct SDK routing plus OpenAI-compatible endpoints.

### Examples

OpenAI:

```json
{
  "llm_model": "openai/gpt-4o-mini",
  "llm_api_key": "${LLM_API_KEY}"
}
```

Anthropic:

```json
{
  "llm_model": "anthropic/claude-sonnet-4-20250514",
  "llm_api_key": "${LLM_API_KEY}"
}
```

Google:

```json
{
  "llm_model": "google/gemini-2.5-pro",
  "llm_api_key": "${LLM_API_KEY}"
}
```

Ollama local:

```json
{
  "llm_model": "ollama/llama3.2",
  "llm_api_key": ""
}
```

If you use local providers, start them first (for example `ollama serve`).

---

## Safety and Runtime Model

Grinta executes locally on your host machine.

- Default mode is local execution.
- `hardened_local` adds stricter policy checks.
- `hardened_local` is not sandboxing or process isolation.

Use Grinta in trusted repositories and environments.

### Modes (`/mode`)

Grinta has four interaction modes that change the conversational contract:

- **Chat** — talk freely, ask questions, discuss architecture. No execution pressure. Use this when you want to think out loud or explore without triggering tool calls.
- **Ask** — like Chat but explicitly signals a standalone question or clarification request. Uses the same read-only tool set as Chat.
- **Plan** — the agent thinks, clarifies requirements, and produces an actionable plan before any tool executes. Use this for complex or ambiguous tasks where you want to review the approach first.
- **Agent** — full task execution. The agent plans, runs tools, validates results, and finishes. This is the default mode when you give a direct task.

Switch between them at any time with `/mode chat`, `/mode ask`, `/mode plan`, or `/mode agent`. The current mode is visible in the HUD bar.

### Autonomy levels (`/autonomy`)

There are three stored levels: **conservative**, **balanced**, and **full**. They differ only in **when the agent asks you before running an action**; execution, retries, and prompts are otherwise the same.

- **Conservative** — confirm before every runnable action.
- **Balanced** (default) — confirm only for high-risk actions.
- **Full** — never prompt for confirmation; hard safety blocks (for example CRITICAL-classified commands) still apply.

Autonomy level is only meaningful in **Agent** mode. Chat and Plan modes have their own interaction contracts independent of autonomy.

See also [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md).

---

## Useful Commands

Install + run:

```bash
uv sync
uv run python -m backend.cli.entry
```

CLI help:

```bash
uv run python -m backend.cli.entry --help
```

---

For architecture internals, see `docs/ARCHITECTURE.md`.
For contributor-facing internals, see `docs/DEVELOPER.md`.
For debugging issues, see `docs/TROUBLESHOOTING.md`.
