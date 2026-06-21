# Grinta User Guide

This guide reflects the current terminal-first Grinta workflow.

Canonical startup:

- Installed CLI: `grinta`
- Source checkout: `uv run python -m backend.cli.entry`

## Table of Contents

1. Installation
2. Interface and configuration
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
python scripts/bootstrap_env.py dev-test
uv run python -m backend.cli.entry init
uv run python -m backend.cli.entry
```

`grinta init` and the first-run wizard shown when you launch `grinta` without
configuration use the same shared setup flow (provider picker, optional
connection check, `settings.json` + `.env`).

Interactive TTY sessions start the Textual app. If you pipe input into Grinta,
it uses the non-interactive runner so scripts can call it without a full-screen
terminal.

### Create or update local settings

```bash
uv run python -m backend.cli.entry init
```

On Windows PowerShell:

```powershell
uv run python -m backend.cli.entry init
```

---

## Interface and Configuration

### Terminal surfaces

Grinta has two runtime surfaces:

- **Interactive TTY:** `grinta` or `uv run python -m backend.cli.entry` opens the Textual terminal app with transcript cards, HUD, dialogs, and slash commands.
- **Non-interactive stdin:** piped input runs through `backend.cli.repl.noninteractive` and prints results without the Textual app.

The same orchestrator, safety checks, provider routing, and event stream back both surfaces.

## Configuration

Grinta supports layered configuration. Installed runs use `~/.grinta/settings.json`; source checkouts use the repository `settings.json`; `APP_ROOT` can intentionally override the settings root.

### Minimal settings.json

```json
{
  "llm_provider": "openai",
  "llm_model": "openai/gpt-5.1",
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

### Textual app: Ctrl+C and interruption

In the Textual app, Ctrl+C is bound to copy-or-interrupt behavior and Escape is
available for interrupting the active agent run. Use `/exit` to leave the app.
The prompt-toolkit fallback may handle Ctrl+C differently depending on terminal
and platform.

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

The agent will plan, execute tools, validate progress, and surface completion-quality signals before finishing. In the current release line, completion validation is advisory guidance rather than a hard finish blocker.

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
  "llm_model": "openai/gpt-5.1",
  "llm_api_key": "${LLM_API_KEY}"
}
```

Anthropic:

```json
{
  "llm_model": "anthropic/claude-sonnet-4.6",
  "llm_api_key": "${LLM_API_KEY}"
}
```

Google:

```json
{
  "llm_model": "google/gemini-3-flash",
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

From a source checkout, you can inspect local provider availability with:

```bash
uv run python -m backend.inference.discover_models
uv run python -m backend.inference.discover_models status
```

---

## Safety and Runtime Model

Grinta executes locally on your host machine.

- Default mode is local execution.
- `security.execution_profile="hardened_local"` adds stricter policy checks for command cwd, package installs, network-capable commands, background processes, and sensitive workspace paths.
- `security.execution_profile="sandboxed_local"` adds those same checks plus OS-native process isolation for non-interactive command execution.
- `hardened_local` is not sandboxing or process isolation. Interactive terminal sessions also bypass process isolation under `sandboxed_local`.

Use Grinta in trusted repositories and environments.

### Interaction modes

Grinta has three interaction modes that change the conversational contract:

- **Chat** — grounded Q&A and discussion. Use discovery tools (`grep`, `glob`, `find_symbols`, `read`, `lsp`, `analyze_project_structure`) and `ask_user` when needed. No edits or shell execution.
- **Plan** — read-only investigation plus structured planning. The agent clarifies requirements and produces an actionable plan before any execution. Use this for complex or ambiguous tasks where you want to review the approach first.
- **Agent** — full task execution. The agent plans, runs tools, validates results, and finishes. This is the default mode when you give a direct task.

In the Textual app, the current mode is visible and selectable in the HUD. The
mode is also stored on the active agent config for startup/default behavior. The
current slash-command registry does not expose a `/mode` command.

### Autonomy levels (`/autonomy`)

There are three stored levels: **conservative**, **balanced**, and **full**. They differ only in **when the agent asks you before running an action**; execution, retries, and prompts are otherwise the same.

- **Conservative** — confirm before every command, mutation, terminal/browser action, MCP call, or worker-coordination action in the confirmation flow.
- **Balanced** (default) — confirm for high-risk or high-impact actions, including declared `HIGH` risk, dangerous commands, file edits, browser actions, worker delegation, and blackboard writes.
- **Full** — never prompt for confirmation; hard safety blocks (for example CRITICAL-classified commands) still apply.

Autonomy level is only meaningful in **Agent** mode. Chat and Plan modes have their own interaction contracts independent of autonomy.

Autonomy is separate from `security.execution_profile`: autonomy controls prompts, while the execution profile controls runtime hardening.

See also [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md).

---

## Useful Commands

Install + run:

```bash
python scripts/bootstrap_env.py dev-test
uv run python -m backend.cli.entry
```

CLI help:

```bash
uv run python -m backend.cli.entry --help
```

Common slash commands:

| Command | Purpose |
| --- | --- |
| `/help [command|--all]` | Show commands and shortcuts |
| `/settings` | Open model, API key, and MCP settings |
| `/sessions` / `/resume <N|id>` | List or resume past sessions |
| `/model [provider/model]` | Show or switch the active model |
| `/autonomy [conservative|balanced|full]` | View or set confirmation behavior |
| `/status [verbose]` | Show HUD state and optional diagnostics |
| `/health` | Check debug adapters (e.g. debugpy), ripgrep, git, and model setup |
| `/diff [--stat|--name-only|--patch] [path]` | Show workspace git changes |
| `/checkpoint [label]` | Save a manual workspace checkpoint |
| `/compact` / `/retry` | Compact context or resend the last message |

---

For architecture internals, see `docs/ARCHITECTURE.md`.
For contributor-facing internals, see `docs/DEVELOPER.md`.
For debugging issues, see `docs/TROUBLESHOOTING.md`.
