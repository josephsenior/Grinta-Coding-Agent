#!/usr/bin/env bash
# ============================================
# FORGE - Docker Quick Start
# ============================================

set -e

echo "🚀 Starting Forge in Docker..."

NO_DATABASE=0
DETACHED=0

for arg in "$@"; do
    case "$arg" in
        --no-db)
            NO_DATABASE=1
            ;;
        -d|--detached)
            DETACHED=1
            ;;
    esac
done

# Ensure settings.json exists
if [ ! -f "settings.json" ]; then
    if [ -f "settings.template.json" ]; then
        echo "📝 Creating settings.json from template..."
        cp settings.template.json settings.json
    else
        echo "⚠ settings.template.json not found. Creating minimal settings.json"
        printf '{"llm_model":"","llm_api_key":"","llm_base_url":""}\n' > settings.json
    fi
fi

# Run docker compose
echo "🐳 Running Docker Compose (default: Redis + Postgres + Forge)..."

if [ "$NO_DATABASE" -eq 1 ]; then
    export FORGE_KB_STORAGE_TYPE=file
    echo "⚠ Emergency mode enabled: KB_STORAGE_TYPE=file"
else
    export FORGE_KB_STORAGE_TYPE=database
fi

if [ "$DETACHED" -eq 1 ]; then
    docker compose up --build -d
else
    docker compose up --build
fi
