# ============================================
# FORGE - Docker Quick Start
# ============================================

Write-Host "🚀 Starting Forge in Docker..." -ForegroundColor Cyan

# Ensure settings.json exists so it can be mounted
if (-not (Test-Path "settings.json")) {
    Write-Host "📝 Creating settings.json from template..." -ForegroundColor Yellow
    Copy-Item "settings.template.json" "settings.json"
}

# Run docker compose
Write-Host "🐳 Running Docker Compose..." -ForegroundColor Green
docker compose up --build

Write-Host "✅ Docker session ended." -ForegroundColor Cyan
pause
