# ============================================
# FORGE - Quick Start Script
# ============================================
# Run this script in PowerShell to start Forge

Write-Host "🚀 Starting Forge..." -ForegroundColor Cyan
Write-Host ""

# Change to project directory
Set-Location -Path $PSScriptRoot

# Step 0: Pre-flight checks & Auto-Configuration
Write-Host "🔍 Step 0: Pre-flight checks..." -ForegroundColor Yellow

# Check for uv
if ($null -eq (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 'uv' not found. Please install it: https://docs.astral.sh/uv/" -ForegroundColor Red
    pause
    exit 1
}

# Check Python version
$pythonVersion = uv run python --version 2>&1
if ($pythonVersion -match "Python 3\.(1[2-9]|[2-9][0-9])") {
    Write-Host "✅ Python version ok (via uv): $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "❌ Python 3.12+ required. Found: $pythonVersion" -ForegroundColor Red
    pause
    exit 1
}

# Check for settings.json
if (-not (Test-Path "settings.json")) {
    Write-Host "📝 Creating settings.json from template..." -ForegroundColor Cyan
    Copy-Item "settings.template.json" "settings.json"
}

Write-Host "📦 Step 1: Syncing dependencies with uv..." -ForegroundColor Yellow
uv sync

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to sync dependencies" -ForegroundColor Red
    Write-Host "Please ensure you have 'uv' installed: https://docs.astral.sh/uv/" -ForegroundColor Yellow
    pause
    exit 1
}

# Step 1.5: Auto-discover local models
Write-Host "🤖 Step 1.5: Discovering local models (Ollama/LM Studio/vLLM)..." -ForegroundColor Yellow
uv run python -m backend.llm.discover_models aliases
Write-Host "✅ Model aliases updated in settings.json" -ForegroundColor Green

Write-Host "✅ Dependencies synced!" -ForegroundColor Green
Write-Host ""

# Wait for server to start
Start-Sleep -Seconds 2

# Step 2: Launch Unified Interface (Backend + TUI)
Write-Host "🚀 Step 2: Launching Unified Interface..." -ForegroundColor Yellow
Write-Host "   This runs the server in the background and TUI in the foreground." -ForegroundColor Cyan
Write-Host ""

uv run forge all

Write-Host ""
Write-Host "✅ Forge session ended." -ForegroundColor Green
pause
