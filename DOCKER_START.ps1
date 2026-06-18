# Backward-compatible entrypoint — implementation lives in scripts/docker/
& "$PSScriptRoot\scripts\docker\docker_start.ps1" @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
