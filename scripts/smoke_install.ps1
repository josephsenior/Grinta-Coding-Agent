# Clean-room install smoke-test for Grinta on Windows / PowerShell.
#
# Validates that `pip install grinta-ai` and the optional extras install cleanly
# on a fresh Python environment. Mirror of `scripts/smoke_install.sh`.
#
# Usage:
#   .\scripts\smoke_install.ps1                 # base install only
#   .\scripts\smoke_install.ps1 rag             # base + [rag]
#   .\scripts\smoke_install.ps1 rag documents   # multiple extras
#   .\scripts\smoke_install.ps1 all             # everything

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Extras
)

$ErrorActionPreference = 'Stop'
$wheelDir = if ($env:WHEEL_DIR) { $env:WHEEL_DIR } else { '.\dist' }

$wheels = @()
if (Test-Path $wheelDir) {
    $wheels = Get-ChildItem -Path $wheelDir -Filter 'grinta_ai-*.whl' -ErrorAction SilentlyContinue
}

if ($wheels.Count -gt 0) {
    $pkgSpec = $wheels[0].FullName
    Write-Host "==> Using local wheel: $pkgSpec"
} else {
    $pkgSpec = 'grinta-ai'
    Write-Host "==> Using PyPI: $pkgSpec"
}

$extraSpec = ''
if ($Extras -and $Extras.Count -gt 0) {
    $extraSpec = '[' + ($Extras -join ',') + ']'
}

$venvPath = Join-Path $env:TEMP 'grinta-smoke-venv'
Write-Host "==> Creating fresh venv at $venvPath"
if (Test-Path $venvPath) { Remove-Item -Recurse -Force $venvPath }
python -m venv $venvPath

$pythonExe = Join-Path $venvPath 'Scripts\python.exe'
$pipExe = Join-Path $venvPath 'Scripts\pip.exe'

Write-Host "==> Installing: $pkgSpec$extraSpec"
& $pythonExe -m pip install --upgrade pip --quiet
& $pipExe install "$pkgSpec$extraSpec"

Write-Host ''
Write-Host '==> Disk size of installed site-packages'
$libPath = Join-Path $venvPath 'Lib\site-packages'
$sizeMb = [math]::Round(((Get-ChildItem -Path $libPath -Recurse -ErrorAction SilentlyContinue |
    Measure-Object -Sum Length).Sum / 1MB), 1)
Write-Host "$sizeMb MB"

Write-Host ''
Write-Host '==> Smoke-test: import + --help'
& $pythonExe -c "import backend; print('backend imported OK')"
& $pythonExe -m backend.cli.entry --help | Select-Object -First 5

Write-Host ''
Write-Host '==> Smoke-test: optional-imports verifier'
& $pythonExe backend\scripts\verify\verify_optional_imports.py

Write-Host ''
Write-Host "==> Done. Extras installed: $($Extras -join ', ')"
