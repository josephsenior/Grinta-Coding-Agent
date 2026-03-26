# ============================================================================
# Forge — Docker build
# ============================================================================
# Usage:
#   docker compose up              # recommended (uses docker-compose.yml)
#   docker build -t forge .        # standalone build
#   docker run -p 3000:3000 forge  # standalone run
# ============================================================================

# --- Builder stage: install deps + build ---
FROM python:3.12-slim AS builder

# Install uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential python3-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy manifest and sync dependencies (using --system to populate site-packages)
COPY pyproject.toml ./
RUN /uv/bin/uv pip install --system --no-cache -e .

COPY backend/ ./backend/
COPY settings.template.json start_server.py ./

# --- Runtime stage: minimal image ---
FROM python:3.12-slim AS runtime

# System deps for tmux (libtmux) and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux git curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash forge

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/backend ./backend
COPY --from=builder /build/settings.template.json /build/start_server.py ./

# Default config: copy template if no settings.json mounted
RUN cp settings.template.json settings.json && \
    mkdir -p /app/.tmux && \
    mkdir -p /app/workspace && \
    chown -R forge:forge /app

# Switch to non-root user
USER forge

# Runtime environment
ENV FORGE_HOST=0.0.0.0 \
    FORGE_PORT=3000 \
    PROJECT_ROOT=/app/workspace \
    TMUX_TMPDIR=/app/.tmux

EXPOSE 3000/tcp

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:3000/api/health/live || exit 1

CMD ["python", "start_server.py"]
