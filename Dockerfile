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

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

ENV POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1
RUN pip install --no-cache-dir poetry==2.1.3
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /build

COPY pyproject.toml poetry.toml poetry.lock* ./
RUN poetry install --no-root --no-directory --only main 2>/dev/null || \
    poetry install --no-root --no-directory

COPY backend/ ./backend/
COPY config.template.toml start_server.py ./

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
COPY --from=builder /build/config.template.toml /build/start_server.py ./

# Default config: copy template if no config.toml mounted
RUN cp config.template.toml config.toml && \
    mkdir -p /app/workspace && \
    chown -R forge:forge /app

# Switch to non-root user
USER forge

# Runtime environment
ENV FORGE_HOST=0.0.0.0 \
    FORGE_PORT=3000 \
    WORKSPACE_BASE=/app/workspace

EXPOSE 3000/tcp

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:3000/api/health/live || exit 1

CMD ["python", "start_server.py"]
