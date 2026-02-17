# Quick Start

## Prerequisites

- Python 3.12+
- `poetry`

## Option 1: Windows bootstrap script

From PowerShell in the repo root:

```powershell
.\START_HERE.ps1
```

This script installs dependencies and starts:

- Backend API on http://localhost:3000
- TUI in a new terminal window

## Option 2: Manual start

### 1) Backend

```powershell
poetry install
python start_server.py
```

### 2) TUI (new terminal)

```powershell
python -m backend.tui
```

Or using the script entry point:

```powershell
forge-tui --port 3000
```

## URLs

- Backend API: http://localhost:3000/api
- API docs: http://localhost:3000/docs

## Common issues

### Poetry not found

Add Poetry scripts dir to PATH for the current shell:

```powershell
$env:Path += ";$env:APPDATA\Python\Scripts"
```

### Lock/dependency drift

```powershell
poetry lock --no-update
poetry install --no-root
```

### Port already in use

Change the backend port via environment variable or `--port` flag on the TUI.
