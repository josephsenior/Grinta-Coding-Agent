#!/usr/bin/env bash
# ============================================
# FORGE - Docker Quick Start
# ============================================

set -e

echo "🚀 Starting Forge in Docker..."

# Ensure config.toml exists
if [ ! -f "config.toml" ]; then
    echo "📝 Creating config.toml from template..."
    cp config.template.toml config.toml
fi

# Run docker compose
echo "🐳 Running Docker Compose..."
docker compose up --build
