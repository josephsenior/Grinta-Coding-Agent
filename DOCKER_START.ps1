# ============================================
# FORGE - Docker Quick Start
# ============================================

Write-Host "🚀 Starting Forge in Docker..." -ForegroundColor Cyan

# Ensure config.toml exists so it can be mounted
if (-not (Test-Path "config.toml")) {
    Write-Host "📝 Creating config.toml from template..." -ForegroundColor Yellow
    Copy-Item "config.template.toml" "config.toml"
}

# Run docker compose
Write-Host "🐳 Running Docker Compose..." -ForegroundColor Green
docker compose up --build

Write-Host "✅ Docker session ended." -ForegroundColor Cyan
pause
