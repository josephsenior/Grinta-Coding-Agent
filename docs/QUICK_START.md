# Quick Start

## Prerequisites

- Python 3.12+
- `uv` (required)

## Option 1: Direct source startup (recommended)

From the repo root:

```powershell
python scripts/bootstrap_env.py dev-test
uv run python -m backend.cli.entry init
uv run python -m backend.cli.entry
```

That is the canonical contributor path. It creates or updates the project-local
`.venv`, writes source-checkout settings to `settings.json`, and starts the
interactive terminal app. If stdin is not a TTY, Grinta uses the non-interactive
runner instead of the Textual app.

For a minimal runtime-only sync (no dev/test tools), use `python scripts/bootstrap_env.py base`.

## Option 2: Windows convenience script

From PowerShell in the repo root:

```powershell
.\START_HERE.ps1
```

This script is a convenience wrapper around dependency sync and startup:

- Checks for `uv` and Python versions
- Syncs dependencies with the `dev-test` profile
- Checks local model server status (`discover_models status`)
- Runs `grinta init` when `settings.json` is missing
- Starts the Grinta terminal app

## Optional: local model discovery

If you run Ollama, LM Studio, or vLLM locally, start the local server and run:

```powershell
uv run python -m backend.inference.discover_models
uv run python -m backend.inference.discover_models status
```

Then use a provider-qualified model id such as `ollama/llama3.2`,
`lm_studio/qwen2.5-coder`, or `vllm/mistral-small` in `settings.json` or
`/model`.

## Useful source commands

```powershell
uv run python -m backend.cli.entry
uv run python -m backend.cli.entry --help
uv run python -m backend.cli.entry sessions list
```

## Common issues

### uv not found

Install `uv` via the official installer:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Locally hosted models

Ensure **Ollama**, **LM Studio**, or **vLLM** is running, then use the discovery
commands above or choose the provider-qualified model id during setup.

### Port already in use

For the CLI itself, this usually points to another local tool, not Grinta.
