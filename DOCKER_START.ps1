# ============================================
# App - Docker Quick Start
# ============================================

param(
    [switch]$NoDatabase,
    [switch]$Detached
)

Write-Host "🚀 Starting app in Docker..." -ForegroundColor Cyan

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

# Run docker compose
Write-Host "🐳 Running Docker Compose (default: Redis + Postgres + app)..." -ForegroundColor Green

$env:APP_KB_STORAGE_TYPE = if ($NoDatabase) { "file" } else { "database" }

if ($NoDatabase) {
    Write-Host "⚠ Emergency mode enabled: APP_KB_STORAGE_TYPE=file" -ForegroundColor Yellow
}

if ($Detached) {
    docker compose up --build -d
} else {
    docker compose up --build
}

Write-Host "✅ Docker session ended." -ForegroundColor Cyan
pause
