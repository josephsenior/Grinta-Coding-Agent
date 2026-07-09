# ============================================
# GRINTA - Dev bootstrap (source checkout)
# ============================================
# Syncs deps, runs init + doctor. Does NOT launch the TUI — cd to your project and run grinta.

$ErrorActionPreference = 'Stop'
$env:UV_SYSTEM_CERTS = "true"

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

    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $pythonVersion = & uv run python --version 2>&1 | Out-String
    $ErrorActionPreference = $prevEAP
    if ($pythonVersion -match 'Python 3\.(1[2-9]|[2-9][0-9])') {
        Write-Host "[OK] Python ok (via uv): $pythonVersion" -ForegroundColor Green
        return
    }

    Write-Host "[ERROR] Python 3.12+ required. uv reported: $pythonVersion" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

function Ensure-Ripgrep {
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        Write-Host "[OK] ripgrep found: $((Get-Command rg).Source)" -ForegroundColor Green
        return
    }

    Write-Host "ripgrep not found. Downloading prebuilt Windows binary..." -ForegroundColor Yellow
    $rgUrl = "https://github.com/BurntSushi/ripgrep/releases/download/14.1.0/ripgrep-14.1.0-x86_64-pc-windows-msvc.zip"
    $rgZip = Join-Path $env:TEMP "rg.zip"
    $rgExtract = Join-Path $env:TEMP "rg_extracted"
    
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $rgUrl -OutFile $rgZip
        Expand-Archive -Path $rgZip -DestinationPath $rgExtract -Force
        
        $localBin = Join-Path $env:USERPROFILE '.local\bin'
        if (-not (Test-Path $localBin)) { New-Item -ItemType Directory -Path $localBin -Force | Out-Null }
        
        $rgExeSource = Join-Path $rgExtract "ripgrep-14.1.0-x86_64-pc-windows-msvc\rg.exe"
        Copy-Item $rgExeSource -Destination (Join-Path $localBin "rg.exe") -Force
        
        Write-Host "[OK] ripgrep installed to $localBin." -ForegroundColor Green
    } catch {
        Write-Host "[WARN] Failed to install ripgrep automatically: $_" -ForegroundColor Yellow
        Write-Host "Please install ripgrep manually using: winget install BurntSushi.ripgrep.MSVC" -ForegroundColor Yellow
    }
}

Write-Host 'Starting Grinta bootstrap...' -ForegroundColor Cyan

# Change to repository root (this script lives in scripts/launch/)
Set-Location -Path (Resolve-Path (Join-Path $PSScriptRoot '..\..'))

Write-Host 'Step 0: Toolchain...' -ForegroundColor Yellow
Ensure-Uv
Ensure-Python
Ensure-Ripgrep

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

Write-Host 'Step 2: Running doctor...' -ForegroundColor Yellow
& uv run python -m backend.cli.entry doctor
if ($LASTEXITCODE -ne 0) {
    Write-Host '[ERROR] Doctor found problems. Fix settings/.env then re-run START_HERE.ps1' -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit $LASTEXITCODE
}

$repoRoot = (Get-Location).Path
Write-Host ''
Write-Host '[OK] Bootstrap complete.' -ForegroundColor Green
Write-Host "Settings: $repoRoot\settings.json" -ForegroundColor Cyan
Write-Host 'Logs: logs\workspaces\...' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Step 3: Installing Grinta CLI globally...' -ForegroundColor Yellow
& uv tool install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Host '[WARN] Failed to install Grinta globally. You can still run it via uv run.' -ForegroundColor Yellow
} else {
    Write-Host '[OK] Grinta CLI installed globally!' -ForegroundColor Green
}

Write-Host ''
Write-Host 'Next — open your project (not the Grinta repo):' -ForegroundColor Yellow
Write-Host '  cd "<project>"'
Write-Host "  grinta"
Write-Host ''
Write-Host 'Docs: docs\QUICK_START.md' -ForegroundColor Cyan
Write-Host ''
