# Backward-compatible entrypoint for pipx installs — implementation in scripts/launch/
& "$PSScriptRoot\scripts\launch\start_here_pipx.ps1" @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
