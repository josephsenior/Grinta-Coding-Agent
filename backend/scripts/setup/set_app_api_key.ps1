<#
Prompt for an app API key and persist it as APP_API_KEY for the current user.
This script uses `Read-Host -AsSecureString` to avoid echoing secrets.
It writes the variable persistently using `setx` and also updates the current session.

Usage (PowerShell):
    .\scripts\set_app_api_key.ps1

Note: setx writes to the registry and will not affect the current session automatically,
so this script also sets $env:APP_API_KEY for the running shell after storing it.
#>

# Prompt securely
$secureKey = Read-Host -Prompt "Enter your app API key" -AsSecureString
if (-not $secureKey) {
    Write-Host "No key entered — aborting." -ForegroundColor Yellow
    exit 1
}

# Convert SecureString to plain text in a safe local-only variable
$ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $plainKey = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}

# Persist for the current user (will be available in new shells)
setx APP_API_KEY $plainKey | Out-Null

# Also set for current session
$env:APP_API_KEY = $plainKey

Write-Host "APP_API_KEY set for current session and persisted for your user account." -ForegroundColor Green
Write-Host "Note: restart existing shells/IDE windows to pick up the persistent value." -ForegroundColor Cyan

# Zero-out sensitive variable
$plainKey = $null
$secureKey = $null

exit 0
