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
$hookDir = if ($env:HOOK_DIR) { $env:HOOK_DIR } else { Join-Path $smokeRoot 'hooks' }
$stubSource = Join-Path $RepoRoot 'scripts\smoke\cli_llm_stub_sitecustomize.py'

if (Test-Path $smokeRoot) { Remove-Item -Recurse -Force $smokeRoot }
New-Item -ItemType Directory -Path $appRoot, $projectRoot, $hookDir -Force | Out-Null
Set-Content -Path (Join-Path $projectRoot 'README.md') -Value 'CLI smoke README target' -Encoding utf8
Copy-Item -Path $stubSource -Destination (Join-Path $hookDir 'sitecustomize.py')

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
$env:LOG_TO_FILE = 'false'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = "$hookDir;$RepoRoot"

if ($UseUvRun) {
    $output = 'Summarize README.md in one sentence.' | uv run python -m backend.cli.entry --project $projectRoot --no-splash 2>&1
} else {
    $output = 'Summarize README.md in one sentence.' | & $PythonExe -m backend.cli.entry --project $projectRoot --no-splash 2>&1
}

if ($LASTEXITCODE -ne 0) {
    Write-Host $output
    throw "Stub CLI task failed with exit code $LASTEXITCODE"
}

if ($output -notmatch 'Task complete: summarized README.md for the CLI regression.') {
    Write-Host $output
    throw 'Stub CLI task did not emit the expected completion message'
}

Write-Host '==> Stub CLI task smoke passed'
