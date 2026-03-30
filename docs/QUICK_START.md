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
- Starts the App server (web UI at http://localhost:3000)

## Option 2: Manual start

### 1) Sync dependencies

```powershell
uv sync
```

### 2) Start the server

```powershell
uv run python start_server.py
```

This is the canonical local server path. `uv run app serve` now delegates to the same entrypoint.

Equivalent aliases:

```powershell
uv run app serve
uv run app all
uv run app start
```

Then open **http://localhost:3000** in a browser.

Startup now prints a preflight summary showing the resolved app root, settings path,
host, port, reload mode, and readiness URL.

## Security profile

App's default local runtime is not sandboxed. If you want a stricter local policy mode, set `security.execution_profile` to `hardened_local` in your configuration.

`hardened_local` blocks or constrains:
- commands that execute outside the workspace
- background processes by default
- network-capable commands unless explicitly allowed
- package installation commands unless explicitly allowed
- sensitive file access unless explicitly allowed
- interactive terminal sessions that drift outside the workspace

This is policy hardening, not host isolation.

## URLs

- Web UI: http://localhost:3000
- Backend API: http://localhost:3000/api
- API docs: http://localhost:3000/docs

## Common issues

### uv not found

Install `uv` via the official installer:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Locally hosted models

Ensure **Ollama** or **LM Studio** is running. App auto-discovers them on startup.

### Port already in use

Change the backend port via environment variable `APP_PORT`.

The canonical local server will also auto-select the next free port in a small range
and print the resolved port in the startup preflight.

### Health and startup status

Use the readiness endpoint for the current startup snapshot and recovery diagnostics:

```text
http://localhost:3000/api/health/ready
```
