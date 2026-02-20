<#!
.SYNOPSIS
  Starts the shadcn-ui MCP proxy (SuperGateway) and then launches Forge serve.
.DESCRIPTION
  1. Ensures shadcn-ui MCP server dependencies are installed & built.
  2. Starts SuperGateway exposing http://localhost:8090/sse.
  3. Waits for the SSE endpoint to respond.
  4. Launches Forge (uvx Forge serve) in the foreground after proxy is up.
.PARAMETER Port
  Port for SuperGateway (default 8090).
.PARAMETER Framework
  shadcn-ui framework (react|svelte|vue) default react.
.PARAMETER GitHubToken
  Optional GitHub token for rate limit increase.
.PARAMETER SkipBuild
  Skip rebuilding the MCP server even if build output missing.
.PARAMETER NoServe
  Start proxy only (do not start Forge serve).
#>
param(
  [int]$Port = 8090,
  [ValidateSet('react','svelte','vue')] [string]$Framework = 'react',
  [string]$GitHubToken,
  [switch]$SkipBuild,
  [switch]$NoServe
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$serverDir = Join-Path $repoRoot 'external/shadcn-ui-mcp-server'
if (-not (Test-Path $serverDir)) { Write-Error "Missing MCP server repo at $serverDir"; exit 1 }

Write-Host "[1/5] Preparing shadcn-ui MCP server..." -ForegroundColor Cyan
Push-Location $serverDir
try {
  if (-not (Test-Path 'node_modules')) { Write-Host '[npm] install' -ForegroundColor DarkCyan; npm install --no-audit --no-fund | Out-Null }
  if (-not $SkipBuild -and -not (Test-Path 'build/index.js')) { Write-Host '[build] building' -ForegroundColor DarkCyan; npm run -s build | Out-Null }
}
finally { Pop-Location }

<# Optional .env.local loader for GITHUB_PERSONAL_ACCESS_TOKEN (robust, no complex regex) #>
$dotenv = Join-Path $repoRoot '.env.local'
if (Test-Path $dotenv) {
  if (-not $env:GITHUB_PERSONAL_ACCESS_TOKEN) {
    $line = (Get-Content $dotenv | Where-Object { $_ -match 'GITHUB_PERSONAL_ACCESS_TOKEN' } | Select-Object -First 1)
    if ($line) {
      $parts = $line -split '=',2
      if ($parts.Count -eq 2) {
        $val = $parts[1].Trim().Trim('"').Trim("'")
        if ($val) { $env:GITHUB_PERSONAL_ACCESS_TOKEN = $val; Write-Host '[env] Loaded GitHub token from .env.local' -ForegroundColor DarkCyan }
      }
    }
  }
}
if ($GitHubToken) { $env:GITHUB_PERSONAL_ACCESS_TOKEN = $GitHubToken }
if (-not $env:GITHUB_PERSONAL_ACCESS_TOKEN) {
  Write-Host '[info] No GitHub token provided; using unauthenticated rate limit (60/hr).' -ForegroundColor Yellow
}

Write-Host "[2/5] Starting SuperGateway (port $Port)..." -ForegroundColor Cyan
# Build command segments explicitly; run via Start-Process (jobs on some PS versions + npx can vanish)
$innerCmd = "npx @jpisnice/shadcn-ui-mcp-server --framework $Framework"
$proxyArgs = @('supergateway','--stdio',"$innerCmd",'--port',"$Port")
$displayCmd = "npx supergateway --stdio '$innerCmd' --port $Port"
Write-Host "[cmd] $displayCmd" -ForegroundColor DarkGray

$logDir = Join-Path $repoRoot 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$proxyLog = Join-Path $logDir 'shadcn-supergateway.log'
if (Test-Path $proxyLog) { Remove-Item $proxyLog -Force }

$psi = New-Object System.Diagnostics.ProcessStartInfo
if ($env:OS -eq 'Windows_NT') {
  # Use cmd.exe /c so .cmd resolution works with redirection capture
  $psi.FileName = 'cmd.exe'
  $psi.Arguments = '/c npx ' + ($proxyArgs -join ' ')
} else {
  $psi.FileName = 'npx'
  $psi.Arguments = ($proxyArgs -join ' ')
}
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $psi
$null = $process.Start()

# Async readers writing to log
$outWriter = [System.IO.StreamWriter]::new($proxyLog, $true)
$stdOutTask = $process.StandardOutput.BaseStream.BeginRead((New-Object byte[] 4096),0,4096,$null,$null)
$stdErrTask = $process.StandardError.BaseStream.BeginRead((New-Object byte[] 4096),0,4096,$null,$null)

function Write-RemainingBuffer($proc, $streamName) {
  try {
    while(-not $proc.HasExited) { Start-Sleep -Milliseconds 200 }
  } catch {}
}

# We will tail the file during readiness loop
$lastSize = 0

# --- New non-stream readiness probe ---
$ProgressPreference = 'SilentlyContinue'
Write-Host "[3/5] Waiting for SuperGateway port $Port to listen..." -ForegroundColor Cyan
$maxSeconds = 30
$readyPort = $false
for ($i=0; $i -lt $maxSeconds; $i++) {
  if ($process.HasExited) {
    Write-Host '[proxy] process exited early; dumping logs:' -ForegroundColor Red
    if (Test-Path $proxyLog) { Get-Content $proxyLog | ForEach-Object { Write-Host "[proxy] $_" -ForegroundColor DarkGray } }
    Write-Error "SuperGateway exited with code $($process.ExitCode) while waiting for port."; exit 1
  }
  $tcp = Test-NetConnection -ComputerName localhost -Port $Port -WarningAction SilentlyContinue
  if ($tcp.TcpTestSucceeded) { $readyPort = $true; break }
  Start-Sleep -Seconds 1
}
if (-not $readyPort) {
  Write-Warning "Port $Port not listening after $maxSeconds seconds; continuing (inspect $proxyLog)."
} else {
  Write-Host "[ok] Port $Port is listening. Probing HTTP endpoints..." -ForegroundColor Green
  $candidatePaths = @('/sse','/mcp','/mcp/sse','/')
  $probeSuccess = $false
  foreach ($p in $candidatePaths) {
    $url = "http://localhost:$Port$p"
    try {
      $resp = Invoke-WebRequest -Uri $url -Method Head -TimeoutSec 2 -ErrorAction Stop
      if ($resp.StatusCode -in 200,204) { Write-Host "[ok] Endpoint responds (HEAD): $url" -ForegroundColor Green; $probeSuccess=$true; break }
    } catch {
      try {
        $resp2 = Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 2 -ErrorAction Stop
        if ($resp2.StatusCode -in 200,204) { Write-Host "[ok] Endpoint responds (GET): $url" -ForegroundColor Green; $probeSuccess=$true; break }
      } catch {}
    }
  }
  if (-not $probeSuccess) { Write-Warning "No quick HTTP probe succeeded; proceeding anyway (SSE may be streaming)." }
}
# --- End non-stream readiness probe ---

# Auto-register with Forge: set env var so Python picks it up in _setup_memory_and_mcp
$env:FORGE_SHADCN_MCP_URL = "http://localhost:$Port/sse"
Write-Host "[env] FORGE_SHADCN_MCP_URL=http://localhost:$Port/sse (auto-registered with Forge)" -ForegroundColor Green

if ($NoServe) { Write-Host '[done] Proxy running only. Use Get-Job/Receive-Job to monitor.' -ForegroundColor Yellow; exit 0 }

Write-Host "[4/5] Launching Forge server..." -ForegroundColor Cyan
# Attempt to use uvx if available; fallback to 'Forge serve'
$serveCmd = 'uvx --python 3.12 --from Forge-ai Forge serve'
try { & uvx --version | Out-Null } catch { $serveCmd = 'Forge serve' }
Write-Host "[cmd] $serveCmd" -ForegroundColor DarkGray

# Run Forge in foreground
try {
  Invoke-Expression $serveCmd
} finally {
  Write-Host "[cleanup] Stopping proxy job" -ForegroundColor Cyan
  if (-not $process.HasExited) { try { $process.Kill() } catch {} }
  if (Test-Path $proxyLog) { Write-Host "[logs] Proxy log saved at $proxyLog" -ForegroundColor DarkCyan }
}
Write-Host "[5/5] Shutdown complete." -ForegroundColor Green
