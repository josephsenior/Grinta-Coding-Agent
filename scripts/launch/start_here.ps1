# ============================================
# GRINTA - Quick Start Script (source checkout)
# ============================================
# Run this script in PowerShell to start Grinta

$ErrorActionPreference = 'Stop'

function Refresh-UvPath {
    $localBin = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path $localBin) {
        $env:Path = "$localBin;$env:Path"
    }
}

function Ensure-Uv {
    Refresh-UvPath
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Host "[OK] uv found: $((Get-Command uv).Source)" -ForegroundColor Green
        return
    }

    Write-Host "uv not found. Installing via Astral installer..." -ForegroundColor Yellow
    try {
        irm https://astral.sh/uv/install.ps1 | iex
    } catch {
        Write-Host "[ERROR] Failed to install uv: $_" -ForegroundColor Red
        Write-Host 'Manual install: https://docs.astral.sh/uv/' -ForegroundColor Yellow
        Read-Host 'Press Enter to exit'
        exit 1
    }

    Refresh-UvPath
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] uv install finished but 'uv' is still not on PATH." -ForegroundColor Red
        Write-Host 'Add %USERPROFILE%\.local\bin to PATH, open a new terminal, and rerun START_HERE.ps1' -ForegroundColor Yellow
        Read-Host 'Press Enter to exit'
        exit 1
    }
    Write-Host '[OK] uv installed.' -ForegroundColor Green
}

function Ensure-Python {
    Write-Host 'Ensuring Python 3.12 via uv (no system Python required)...' -ForegroundColor Yellow
    & uv python install 3.12
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[ERROR] Failed to install Python 3.12 with uv.' -ForegroundColor Red
        Write-Host 'Try manually: uv python install 3.12' -ForegroundColor Yellow
        Write-Host 'Docs: https://docs.astral.sh/uv/guides/install-python/' -ForegroundColor Yellow
        Read-Host 'Press Enter to exit'
        exit 1
    }

    $pythonVersion = & uv run python --version 2>&1
    if ($pythonVersion -match 'Python 3\.(1[2-9]|[2-9][0-9])') {
        Write-Host "[OK] Python ok (via uv): $pythonVersion" -ForegroundColor Green
        return
    }

    Write-Host "[ERROR] Python 3.12+ required. uv reported: $pythonVersion" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Host 'Starting Grinta...' -ForegroundColor Cyan

# Change to repository root (this script lives in scripts/launch/)
Set-Location -Path (Resolve-Path (Join-Path $PSScriptRoot '..\..'))

Write-Host 'Step 0: Toolchain...' -ForegroundColor Yellow
Ensure-Uv
Ensure-Python

Write-Host 'Step 1: Syncing dependencies (dev-test profile)...' -ForegroundColor Yellow
& uv run python scripts/bootstrap_env.py dev-test

if ($LASTEXITCODE -ne 0) {
    Write-Host '[ERROR] Failed to sync dependencies' -ForegroundColor Red
    Write-Host 'Ensure network access, then retry. Docs: https://docs.astral.sh/uv/' -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Host '[OK] Dependencies synced!' -ForegroundColor Green

# Step 1.5: Report local model provider status (optional; does not modify settings)
Write-Host 'Step 1.5: Checking local model servers (Ollama/LM Studio/vLLM)...' -ForegroundColor Yellow
& uv run python -m backend.inference.discover_models status
if ($LASTEXITCODE -ne 0) {
    Write-Host '[WARN] Local model status check failed; continuing.' -ForegroundColor Yellow
}

# Step 1.75: First-run configuration
if (-not (Test-Path 'settings.json')) {
    Write-Host 'Step 1.75: No settings.json found. Starting first-run wizard...' -ForegroundColor Yellow
    & uv run python -m backend.cli.entry init
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[ERROR] Setup wizard did not complete. Fix settings.json, then rerun this script.' -ForegroundColor Red
        Read-Host 'Press Enter to exit'
        exit $LASTEXITCODE
    }
}

# Step 2: Launch Grinta CLI
Write-Host 'Step 2: Starting Grinta CLI...' -ForegroundColor Yellow
Write-Host 'Settings for this source checkout: settings.json in the repository root.' -ForegroundColor Cyan
Write-Host 'Session runtime state: ~/.grinta/workspaces/<id>/storage (pipx installs use ~/.grinta/settings.json).' -ForegroundColor Cyan

& uv run python -m backend.cli.entry

Write-Host ''
Write-Host '[OK] Grinta session ended.' -ForegroundColor Green
Read-Host 'Press Enter to exit'
