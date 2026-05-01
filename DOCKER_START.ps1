# ============================================
# Grinta - Docker Quick Start
# ============================================

param(
    [switch]$NoDatabase,
    [switch]$Detached
)

Write-Host "🚀 Starting Grinta in Docker..." -ForegroundColor Cyan

# Ensure settings.json exists so it can be mounted
if (-not (Test-Path "settings.json")) {
    if (Test-Path "settings.template.json") {
        Write-Host "📝 Creating settings.json from template..." -ForegroundColor Yellow
        Copy-Item "settings.template.json" "settings.json"
    } else {
        Write-Host "⚠ settings.template.json not found. Creating minimal settings.json" -ForegroundColor Yellow
        '{"llm_model":"","llm_api_key":"","llm_base_url":""}' | Set-Content -Path "settings.json" -Encoding UTF8
    }
}

# Run docker compose only when project provides a compose file.
if (-not (Test-Path "docker-compose.yml") -and -not (Test-Path "compose.yml")) {
    Write-Host "⚠ No docker-compose file found in this repository." -ForegroundColor Yellow
    Write-Host "This path is community/experimental. Use the published image instead:" -ForegroundColor Yellow
    Write-Host 'docker run -it --rm -v "$PWD:/work" -w /work -e LLM_API_KEY=${LLM_API_KEY} ghcr.io/josephsenior/grinta:latest'
    exit 1
}

Write-Host "🐳 Running Docker Compose..." -ForegroundColor Green

if ($Detached) {
    docker compose up --build -d
} else {
    docker compose up --build
}

Write-Host "✅ Docker session ended." -ForegroundColor Cyan
pause
