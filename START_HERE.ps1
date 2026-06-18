# Backward-compatible entrypoint — implementation lives in scripts/launch/
& "$PSScriptRoot\scripts\launch\start_here.ps1" @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
