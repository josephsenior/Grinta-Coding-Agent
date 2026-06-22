# Grinta unified Windows launcher (source checkout or pipx install).
#
# Auto-selects the flow:
#   - Source checkout (uv sync + uv run) when pyproject.toml is present
#   - pipx install (grinta on PATH) otherwise
#
# Override:
#   .\START_HERE.ps1 -Pipx     # force pipx flow from a source checkout
#   .\START_HERE.ps1 -Source   # force source flow
#
# Implementation: scripts/launch/

param(
    [switch]$Pipx,
    [switch]$Source,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Remaining
)

$ErrorActionPreference = 'Stop'
$launchDir = Join-Path $PSScriptRoot 'scripts\launch'

$usePipx = $false
if ($Pipx) {
    $usePipx = $true
} elseif ($Source) {
    $usePipx = $false
} else {
    $usePipx = -not (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml'))
}

$scriptName = if ($usePipx) { 'start_here_pipx.ps1' } else { 'start_here.ps1' }
& (Join-Path $launchDir $scriptName) @Remaining
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
