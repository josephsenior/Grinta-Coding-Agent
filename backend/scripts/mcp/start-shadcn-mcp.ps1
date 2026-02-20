<#!
.SYNOPSIS
  Starts the shadcn-ui MCP server via SuperGateway and keeps streaming logs.
.DESCRIPTION
  Launches SuperGateway to expose the shadcn-ui MCP server (via npx) as an SSE endpoint
  at http://localhost:8090/sse.
.PARAMETER Port
  Port to bind SuperGateway SSE endpoint (default 8090)
.PARAMETER Framework
  Framework to fetch (react|svelte|vue) passed through to the MCP server (default react)
.PARAMETER GitHubToken
  Personal access token to raise rate limits (optional)
.PARAMETER VerboseLogs
  Switch to enable MCP server debug logging
.EXAMPLE
  ./start-shadcn-mcp.ps1 -Port 8090 -Framework react -GitHubToken ghp_xxx
#>
param(
  [int]$Port = 8090,
  [ValidateSet('react','svelte','vue')] [string]$Framework = 'react',
  [string]$GitHubToken,
  [switch]$VerboseLogs
)

$ErrorActionPreference = 'Stop'

$envFlags = @()
if ($GitHubToken) { $env:SHADCN_MCP_GITHUB_TOKEN = $GitHubToken }
if ($VerboseLogs) { $env:MCP_DEBUG = '1' }

# Compose stdio command
$stdioCmd = "npx @jpisnice/shadcn-ui-mcp-server --framework $Framework" + ($GitHubToken ? ' --github-api-key *****' : '')
Write-Host "[run] Starting SuperGateway on port $Port wrapping: $stdioCmd" -ForegroundColor Green

# Note: we do not echo the full token for safety
if ($GitHubToken) { Write-Host '[info] GitHub token provided (redacted) – higher rate limits enabled.' -ForegroundColor Yellow }

# Start supergateway (assumes npx available in PATH)
# Using Start-Process so the user can keep terminal; -NoNewWindow to stay attached
$npxArgs = @('supergateway','--stdio',"npx @jpisnice/shadcn-ui-mcp-server --framework $Framework" ,'--port', "$Port")
if ($GitHubToken) {
  # pass token via env instead of CLI argument for privacy if server respects env var
  $env:GITHUB_PERSONAL_ACCESS_TOKEN = $GitHubToken
}

Write-Host "[run] Executing: npx $($npxArgs -join ' ')" -ForegroundColor DarkGray

# Direct invocation so we stream logs inline
npx @npxArgs

Write-Host "[hint] To connect Forge to this proxy, set: `$env:FORGE_SHADCN_MCP_URL='http://localhost:$Port/sse' before running 'Forge serve'" -ForegroundColor Yellow
