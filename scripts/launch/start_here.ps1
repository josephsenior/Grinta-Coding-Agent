# ============================================
# GRINTA - Quick Start Script
# ============================================
# Run this script in PowerShell to start Grinta

Write-Host 'Starting Grinta...' -ForegroundColor Cyan

# Change to repository root (this script lives in scripts/launch/)
Set-Location -Path (Resolve-Path (Join-Path $PSScriptRoot '..\..'))

# Step 0: Pre-flight checks & Auto-Configuration
Write-Host 'Step 0: Pre-flight checks...' -ForegroundColor Yellow

# Check for uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "'uv' not found. Please install it: https://docs.astral.sh/uv/" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

# Check Python version
$pythonVersion = & uv run python --version 2>&1
if ($pythonVersion -match 'Python 3\.(1[2-9]|[2-9][0-9])') {
    Write-Host "[OK] Python version ok (via uv): $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Python 3.12+ required. Found: $pythonVersion" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Host 'Step 1: Syncing dependencies (dev-test profile)...' -ForegroundColor Yellow
& uv run python scripts/bootstrap_env.py dev-test

if ($LASTEXITCODE -ne 0) {
    Write-Host '[ERROR] Failed to sync dependencies' -ForegroundColor Red
    Write-Host "Please ensure you have 'uv' installed: https://docs.astral.sh/uv/" -ForegroundColor Yellow
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
