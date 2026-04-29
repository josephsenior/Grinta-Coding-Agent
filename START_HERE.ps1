# ============================================
# GRINTA - Quick Start Script
# ============================================
# Run this script in PowerShell to start Grinta

Write-Host 'Starting Grinta...' -ForegroundColor Cyan

# Change to project directory
Set-Location -Path $PSScriptRoot

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

# Check for settings.json
if (-not (Test-Path 'settings.json')) {
    Write-Host 'No settings.json found. Run uv run python -m backend.cli.entry init after dependencies sync if configuration is needed.' -ForegroundColor Cyan
}

Write-Host 'Step 1: Syncing dependencies with uv (project .venv + browser group)...' -ForegroundColor Yellow
& uv sync --group browser

if ($LASTEXITCODE -ne 0) {
    Write-Host '[ERROR] Failed to sync dependencies' -ForegroundColor Red
    Write-Host "Please ensure you have 'uv' installed: https://docs.astral.sh/uv/" -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'
    exit 1
}

# Step 1.5: Auto-discover local models
Write-Host 'Step 1.5: Discovering local models (Ollama/LM Studio/vLLM)...' -ForegroundColor Yellow
& uv run python -m backend.llm.discover_models aliases
Write-Host '[OK] Model aliases updated in settings.json' -ForegroundColor Green

Write-Host '[OK] Dependencies synced!' -ForegroundColor Green

# Step 2: Launch Grinta CLI
Write-Host 'Step 2: Starting Grinta CLI...' -ForegroundColor Yellow
Write-Host 'Runtime state will be stored under ~/.grinta/workspaces/<id>/storage.' -ForegroundColor Cyan

& uv run python -m backend.cli.entry

Write-Host ''
Write-Host '[OK] Grinta session ended.' -ForegroundColor Green
Read-Host 'Press Enter to exit'
