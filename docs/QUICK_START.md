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
- Starts the Unified Interface (Backend + TUI)

## Option 2: Manual start

### 1) Sync dependencies

```powershell
uv sync
```

### 2) Start Unified Interface

```powershell
uv run forge all
```

Or start separately:

- **Backend:** `uv run python start_server.py`
- **TUI:** `uv run forge-tui`

## URLs

- Backend API: http://localhost:3000/api
- API docs: http://localhost:3000/docs

## Common issues

### uv not found

Install `uv` via the official installer:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Locally hosted models

Ensure **Ollama** or **LM Studio** is running. Forge auto-discovers them on startup.

### Port already in use

Change the backend port via environment variable `FORGE_PORT`.
