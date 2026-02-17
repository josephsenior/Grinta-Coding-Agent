# ============================================
# FORGE - Quick Start Script
# ============================================
# Run this script in PowerShell to start Forge
# Make sure you have internet access!

Write-Host "🚀 Starting Forge..." -ForegroundColor Cyan
Write-Host ""

# Add Poetry to PATH
$env:Path += ";$env:APPDATA\Python\Scripts"

# Change to project directory
Set-Location -Path $PSScriptRoot

# Step 0: Pre-flight checks & Auto-Configuration
Write-Host "🔍 Step 0: Pre-flight checks..." -ForegroundColor Yellow

# Check Python version
$pythonVersion = python --version 2>&1
if ($pythonVersion -match "Python 3\.(1[2-9]|[2-9][0-9])") {
    Write-Host "✅ Python version ok: $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "❌ Python 3.12+ required. Found: $pythonVersion" -ForegroundColor Red
    pause
    exit 1
}

# Check for config.toml
if (-not (Test-Path "config.toml")) {
    Write-Host "📝 Creating config.toml from template..." -ForegroundColor Cyan
    Copy-Item "config.template.toml" "config.toml"
}

# Step 1: Update lock file and install dependencies
Write-Host "📦 Step 1: Installing dependencies..." -ForegroundColor Yellow
poetry install

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
    Write-Host "Please check your internet connection and try again." -ForegroundColor Yellow
    pause
    exit 1
}

# Step 1.5: Auto-discover local models
Write-Host "🤖 Step 1.5: Discovering local models (Ollama/LM Studio/vLLM)..." -ForegroundColor Yellow
poetry run python -m backend.llm.discover_models aliases
Write-Host "✅ Model aliases updated in config.toml" -ForegroundColor Green

Write-Host "✅ Dependencies installed!" -ForegroundColor Green
Write-Host ""

# Wait for server to start
Start-Sleep -Seconds 2

# Step 2: Launch Unified Interface (Backend + TUI)
Write-Host "🚀 Step 2: Launching Unified Interface..." -ForegroundColor Yellow
Write-Host "   This runs the server in the background and TUI in the foreground." -ForegroundColor Cyan
Write-Host ""

poetry run forge all

Write-Host ""
Write-Host "✅ Forge session ended." -ForegroundColor Green
pause
