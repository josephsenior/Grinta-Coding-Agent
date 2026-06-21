# Run one piped CLI task with the deterministic LLM stub (no live API).
#
# Usage:
#   .\scripts\smoke\run_stub_cli_task.ps1 -PythonExe C:\path\python.exe -RepoRoot C:\path\repo
#   .\scripts\smoke\run_stub_cli_task.ps1 -UseUvRun -RepoRoot C:\path\repo

[CmdletBinding()]
param(
    [string]$PythonExe,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [switch]$UseUvRun
)

$ErrorActionPreference = 'Stop'

if (-not $UseUvRun -and -not $PythonExe) {
    throw 'Either -PythonExe or -UseUvRun is required'
}

$smokeRoot = if ($env:SMOKE_ROOT) { $env:SMOKE_ROOT } else { Join-Path $env:TEMP 'grinta-stub-task-smoke' }
$appRoot = if ($env:APP_ROOT) { $env:APP_ROOT } else { Join-Path $smokeRoot 'app' }
$projectRoot = if ($env:PROJECT_ROOT) { $env:PROJECT_ROOT } else { Join-Path $smokeRoot 'project' }
$stubRunner = Join-Path $RepoRoot 'scripts\smoke\run_cli_with_stub.py'

if (Test-Path $smokeRoot) { Remove-Item -Recurse -Force $smokeRoot }
New-Item -ItemType Directory -Path $appRoot, $projectRoot -Force | Out-Null
Set-Content -Path (Join-Path $projectRoot 'README.md') -Value 'CLI smoke README target' -Encoding utf8

@'
{
  "llm_provider": "openai",
  "llm_model": "openai/gpt-4.1",
  "llm_api_key": "${LLM_API_KEY}",
  "llm_base_url": "",
  "agent": {
    "Orchestrator": {
      "autonomy_level": "balanced"
    }
  },
  "security": {
    "execution_profile": "hardened_local",
    "enforce_security": true
  }
}
'@ | Set-Content -Path (Join-Path $appRoot 'settings.json') -Encoding utf8

$env:APP_ROOT = $appRoot
if (-not $env:LLM_API_KEY) { $env:LLM_API_KEY = 'sk-smoke-stub-task' }
if (-not $env:LLM_MODEL) { $env:LLM_MODEL = 'openai/gpt-4.1' }
$env:GRINTA_NO_SPLASH = '1'
$env:GRINTA_SKIP_STARTUP_HEALTH_CHECK = '1'
$env:LOG_TO_FILE = 'false'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = $RepoRoot

if ($UseUvRun) {
    $output = 'Summarize README.md in one sentence.' | uv run python $stubRunner --project $projectRoot --no-splash 2>&1
} else {
    $output = 'Summarize README.md in one sentence.' | & $PythonExe $stubRunner --project $projectRoot --no-splash 2>&1
}

$outputText = ($output | Out-String)

if ($LASTEXITCODE -ne 0) {
    Write-Host $outputText
    throw "Stub CLI task failed with exit code $LASTEXITCODE"
}

if ($outputText -notmatch 'Agent completed') {
    Write-Host $outputText
    throw 'Stub CLI task did not report agent completion'
}

Write-Host '==> Stub CLI task smoke passed'
