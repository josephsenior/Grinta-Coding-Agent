# Automated smoke for the contributor / source-checkout onboarding path.
#
# Usage (from repo root):
#   .\scripts\smoke\smoke_source_onboarding.ps1

$ErrorActionPreference = 'Stop'

Write-Host '==> Source onboarding smoke: sync base profile'
& python scripts/bootstrap_env.py base

Write-Host '==> Source onboarding smoke: CLI --help'
& uv run python -m backend.cli.entry --help | Select-Object -First 5

Write-Host '==> Source onboarding smoke: init rejects non-interactive stdin'
$smokeAppRoot = Join-Path $env:TEMP 'grinta-source-smoke-app'
if (Test-Path $smokeAppRoot) { Remove-Item -Recurse -Force $smokeAppRoot }
New-Item -ItemType Directory -Path $smokeAppRoot | Out-Null
$prevAppRoot = $env:APP_ROOT
$env:APP_ROOT = $smokeAppRoot
try {
    $null | & uv run python -m backend.cli.entry init 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 3) {
        throw "Expected grinta init exit 3 without TTY, got $LASTEXITCODE"
    }
    if (Test-Path (Join-Path $smokeAppRoot 'settings.json')) {
        throw 'grinta init should not write settings.json without a TTY'
    }
} finally {
    if ($null -eq $prevAppRoot) {
        Remove-Item Env:APP_ROOT -ErrorAction SilentlyContinue
    } else {
        $env:APP_ROOT = $prevAppRoot
    }
}

Write-Host '==> Source onboarding smoke: stub CLI task (deterministic LLM, no live API)'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
& (Join-Path $repoRoot 'scripts\smoke\run_stub_cli_task.ps1') -UseUvRun -RepoRoot $repoRoot

Write-Host '==> Source onboarding smoke: passed'
exit 0
