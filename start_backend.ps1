# Start Forge Backend Server
# Sets PYTHONPATH correctly so forge module can be found

param(
    [int]$Port = 3000
)

function Get-ListeningPidsForPort {
    param([int]$TargetPort)
    try {
        return Get-NetTCPConnection -State Listen -LocalPort $TargetPort -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique
    }
    catch {
        return @()
    }
}

function Is-ForgePythonProcess {
    param([int]$ProcessId)
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
        if ($null -eq $proc) {
            return $false
        }
        $name = [string]$proc.Name
        $cmd = [string]$proc.CommandLine
        if (-not $name.ToLower().Contains("python")) {
            return $false
        }
        return (
            $cmd -match "start_server\.py" -or
            $cmd -match "backend\.api\.listen:app" -or
            $cmd -match "uvicorn"
        )
    }
    catch {
        return $false
    }
}

function Find-AvailablePort {
    param(
        [int]$StartPort,
        [int]$MaxOffset = 20
    )

    for ($offset = 0; $offset -le $MaxOffset; $offset++) {
        $candidate = $StartPort + $offset
        $listeners = Get-ListeningPidsForPort -TargetPort $candidate
        if (-not $listeners -or $listeners.Count -eq 0) {
            return $candidate
        }
    }

    return $null
}

function Test-ForgeAlive {
    param(
        [int]$TargetPort,
        [int]$TimeoutSeconds = 2
    )

    try {
        $uri = "http://127.0.0.1:$TargetPort/alive"
        $resp = Invoke-RestMethod -Uri $uri -TimeoutSec $TimeoutSeconds -ErrorAction Stop
        return $resp.status -eq "ok"
    }
    catch {
        return $false
    }
}

Write-Host "🚀 Starting Forge Backend Server..." -ForegroundColor Cyan

# Change to project directory
Set-Location -Path $PSScriptRoot

# Set Python path to include project root (critical!)
$env:PYTHONPATH = "$PSScriptRoot"

# Force local-dev defaults for clean startup behavior
$env:FORGE_ENV = "development"
Remove-Item Env:FORGE_STRICT -ErrorAction SilentlyContinue

Write-Host "`n📁 Project root: $PSScriptRoot" -ForegroundColor Gray
Write-Host "📁 Backend path: $PSScriptRoot\backend" -ForegroundColor Gray
Write-Host "🐍 Python path: $env:PYTHONPATH" -ForegroundColor Gray

# Verify backend module
Write-Host "`n🔍 Verifying backend module..." -ForegroundColor Yellow
uv run python -c "import sys; sys.path.insert(0, r'$PSScriptRoot'); import backend; print('✅ Backend module found')" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Backend module not found!" -ForegroundColor Red
    Write-Host "Trying to install package..." -ForegroundColor Yellow
    uv sync
}

# Resolve port conflicts safely:
# - stop stale Forge Python listeners on the target port
# - if a non-Forge process owns the port, choose next free port
$resolvedPort = $Port

if (Test-ForgeAlive -TargetPort $Port) {
    Write-Host "`n✅ Forge backend already running at http://127.0.0.1:$Port" -ForegroundColor Green
    Write-Host "No new backend started to avoid duplicate/conflicting instances." -ForegroundColor Yellow
    exit 0
}

$listeners = Get-ListeningPidsForPort -TargetPort $Port
if ($listeners -and $listeners.Count -gt 0) {
    $forgePids = @()
    $nonForgePids = @()

    foreach ($listenerPid in $listeners) {
        if (Is-ForgePythonProcess -ProcessId $listenerPid) {
            $forgePids += $listenerPid
        }
        else {
            $nonForgePids += $listenerPid
        }
    }

    if ($forgePids.Count -gt 0) {
        Write-Host "`n🧹 Found stale Forge listener(s) on port ${Port}: $($forgePids -join ', ')" -ForegroundColor Yellow
        Stop-Process -Id $forgePids -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 400
    }

    $stillOccupied = Get-ListeningPidsForPort -TargetPort $Port
    if ($stillOccupied -and $stillOccupied.Count -gt 0) {
        $nextPort = Find-AvailablePort -StartPort ($Port + 1)
        if ($null -eq $nextPort) {
            Write-Host "❌ No free port found in range $Port-$($Port + 21)." -ForegroundColor Red
            exit 1
        }

        $resolvedPort = $nextPort
        Write-Host "`n⚠️  Port ${Port} is still occupied by non-Forge process(es): $($stillOccupied -join ', ')" -ForegroundColor Yellow
        Write-Host "➡️  Using fallback port $resolvedPort" -ForegroundColor Yellow
    }
}

if (Test-ForgeAlive -TargetPort $resolvedPort) {
    Write-Host "`n✅ Forge backend already running at http://127.0.0.1:$resolvedPort" -ForegroundColor Green
    Write-Host "No new backend started to avoid duplicate/conflicting instances." -ForegroundColor Yellow
    exit 0
}

Write-Host "`n🚀 Starting server on http://127.0.0.1:$resolvedPort" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop`n" -ForegroundColor Yellow

# Start server with PYTHONPATH set
$env:PYTHONPATH = "$PSScriptRoot"
$env:PORT = "$resolvedPort"
$env:FORGE_ENABLE_WINDOWS_MCP = "1"
$env:PYTHONUTF8 = "1"
uv run python start_server.py
