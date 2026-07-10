# ============================================
# GRINTA - Quick Start (pipx / installed CLI)
# ============================================
# For users who installed with: pipx install grinta
# Mirrors scripts/launch/start_here.ps1 without uv or source checkout steps.

$ErrorActionPreference = 'Stop'

function Get-GrintaCommand {
    return Get-Command grinta -ErrorAction SilentlyContinue
}

function Get-GrintaPython {
    $grinta = Get-GrintaCommand
    if (-not $grinta) {
        return $null
    }
    $pythonExe = Join-Path (Split-Path $grinta.Source -Parent) 'python.exe'
    if (Test-Path $pythonExe) {
        return $pythonExe
    }
    return $null
}

function Get-GrintaSettingsPath {
    if ($env:APP_ROOT -and $env:APP_ROOT.Trim()) {
        return Join-Path $env:APP_ROOT 'settings.json'
    }
    return Join-Path $env:USERPROFILE '.grinta' 'settings.json'
}

Write-Host 'Starting Grinta (pipx install)...' -ForegroundColor Cyan

Write-Host 'Step 0: Pre-flight checks...' -ForegroundColor Yellow

$grintaCmd = Get-GrintaCommand
if (-not $grintaCmd) {
    Write-Host "'grinta' not found on PATH." -ForegroundColor Red
    Write-Host 'Install with: pipx install grinta' -ForegroundColor Yellow
    Write-Host 'Then reopen your terminal and run this script again.' -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'
    exit 1
}
Write-Host "[OK] grinta found: $($grintaCmd.Source)" -ForegroundColor Green

$pythonExe = Get-GrintaPython
if ($pythonExe) {
    $pythonVersion = & $pythonExe --version 2>&1
    if ($pythonVersion -match 'Python 3\.(1[2-9]|[2-9][0-9])') {
        Write-Host "[OK] Python version ok (pipx venv): $pythonVersion" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Expected Python 3.12+ in pipx venv. Found: $pythonVersion" -ForegroundColor Yellow
    }
} else {
    Write-Host '[WARN] Could not locate the pipx venv python; skipping version probe.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Note: Grinta bundles ripgrep. Git and language servers are optional' -ForegroundColor DarkGray
Write-Host 'machine tools (not Grinta dependencies) that unlock more workflow features.' -ForegroundColor DarkGray
Write-Host ''

Write-Host 'Step 1: Skipping dependency sync (managed by pipx).' -ForegroundColor Yellow
Write-Host '[OK] Using installed grinta package.' -ForegroundColor Green

Write-Host 'Step 1.5: Checking local model servers (Ollama/LM Studio/vLLM)...' -ForegroundColor Yellow
if ($pythonExe) {
    & $pythonExe -m backend.inference.discover_models status
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[WARN] Local model status check failed; continuing.' -ForegroundColor Yellow
        Write-Host '       grinta init will also probe local servers.' -ForegroundColor DarkGray
    }
} else {
    Write-Host '[WARN] Skipping local model status (pipx python not found).' -ForegroundColor Yellow
}

$settingsPath = Get-GrintaSettingsPath
if (-not (Test-Path $settingsPath)) {
    Write-Host 'Step 1.75: No settings.json found. Starting first-run wizard...' -ForegroundColor Yellow
    Write-Host "         Expected path: $settingsPath" -ForegroundColor DarkGray
    & grinta init
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[ERROR] Setup wizard did not complete. Fix settings, then rerun.' -ForegroundColor Red
        Read-Host 'Press Enter to exit'
        exit $LASTEXITCODE
    }
}

Write-Host 'Step 2: Starting Grinta CLI...' -ForegroundColor Yellow
Write-Host 'Runtime state will be stored under ~/.grinta/workspaces/<id>/storage.' -ForegroundColor Cyan

& grinta
$exitCode = $LASTEXITCODE

Write-Host ''
Write-Host '[OK] Grinta session ended.' -ForegroundColor Green
Read-Host 'Press Enter to exit'
exit $exitCode
