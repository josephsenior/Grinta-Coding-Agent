# Backward-compatible entrypoint — implementation lives in scripts/smoke/
& "$PSScriptRoot\smoke\smoke_source_onboarding.ps1" @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
