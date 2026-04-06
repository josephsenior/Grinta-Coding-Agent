# Quick Start

## Prerequisites

- Python 3.12+
- `uv` (Recommended) or `pip`

## Option 1: Windows bootstrap script (Recommended)

From PowerShell in the repo root:

```powershell
.\START_HERE.ps1
```

This script handles everything:
- Checks for `uv` and Python versions
- Syncs dependencies
- Discover local models (Ollama/LM Studio)
- Starts the Grinta terminal CLI

## Option 2: Manual start

### 1) Sync dependencies

```powershell
uv sync
```

### 2) Start the CLI

```powershell
uv run python -m backend.cli.entry
```

This is the canonical local startup path.

If you need the raw HTTP backend for API/OpenAPI tooling, use [start_backend.ps1](../start_backend.ps1)
on Windows or run:

```powershell
uv run python -m backend.execution.action_execution_server 3000 --working-dir .
```

## Security profile

Grinta's default local runtime is not sandboxed. If you want a stricter local policy mode, set `security.execution_profile` to `hardened_local` in your configuration.

`hardened_local` blocks or constrains:
- commands that execute outside the workspace
- background processes by default
- network-capable commands unless explicitly allowed
- package installation commands unless explicitly allowed
- sensitive file access unless explicitly allowed
- interactive terminal sessions that drift outside the workspace

This is policy hardening, not host isolation.

## Optional HTTP Backend

If you start the raw backend, the OpenAPI spec is exposed at:

- OpenAPI JSON: http://localhost:3000/openapi.json
- Server info: http://localhost:3000/server_info

## Common issues

### uv not found

Install `uv` via the official installer:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Locally hosted models

Ensure **Ollama** or **LM Studio** is running. App auto-discovers them on startup.

### Port already in use

This only applies to the raw HTTP backend. Use `-Port` with [start_backend.ps1](../start_backend.ps1)
or change the positional port argument when launching
`backend.execution.action_execution_server` directly.

### Health and startup status

Use the readiness endpoint for the current startup snapshot and recovery diagnostics:

```text
http://localhost:3000/api/health/ready
```
