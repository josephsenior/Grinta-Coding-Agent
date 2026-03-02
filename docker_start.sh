#!/usr/bin/env bash
# ============================================
# FORGE - Docker Quick Start
# ============================================

set -e

echo "🚀 Starting Forge in Docker..."

# Ensure settings.json exists
if [ ! -f "settings.json" ]; then
    echo "📝 Creating settings.json from template..."
    cp settings.template.json settings.json
fi

# Run docker compose
echo "🐳 Running Docker Compose..."
docker compose up --build
