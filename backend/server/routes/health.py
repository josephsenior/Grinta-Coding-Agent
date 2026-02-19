"""Health and diagnostics endpoints for the Forge server."""

import os
import sys
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.runtime.utils import system_stats


def get_system_info() -> dict:
    """Proxy to runtime system stats for easier monkeypatching in tests."""
    return system_stats.get_system_info()


def _check_storage() -> dict:
    """Validate that the file-store directory is writable."""
    try:
        from backend.storage.locations import get_file_store_path

        store_path = get_file_store_path()
        writable = os.path.isdir(store_path) and os.access(store_path, os.W_OK)
        return {"status": "ok" if writable else "degraded", "path": str(store_path)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_config() -> dict:
    """Validate that the core config is loadable."""
    try:
        from backend.core.config import load_forge_config

        cfg = load_forge_config()
        return {
            "status": "ok",
            "workspace_base": str(getattr(cfg, "workspace_base", "?")),
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


_start_time = time.monotonic()


def add_health_endpoints(app: FastAPI) -> None:
    """Add health check endpoints to the FastAPI application.

    Args:
        app: The FastAPI application to add endpoints to.

    """

    @app.get("/alive")
    async def alive():
        """Simple liveness probe returning status ok."""
        return {"status": "ok"}

    @app.get("/api/health/live")
    async def health_live():
        """Liveness probe endpoint.

        Returns 200 as long as the process is running and can serve requests.
        Unlike /alive, includes uptime information.
        """
        return {
            "status": "ok",
            "uptime_seconds": round(time.monotonic() - _start_time, 1),
        }

    @app.get("/api/health/ready")
    async def health_ready():
        """Readiness probe endpoint.

        Checks that critical subsystems (config, file store) are operational.
        Returns 200 if all checks pass, 503 if any critical check fails.
        """
        config_check = _check_config()
        storage_check = _check_storage()

        checks = {
            "config": config_check,
            "storage": storage_check,
        }

        all_ok = all(c.get("status") == "ok" for c in checks.values())
        status_code = 200 if all_ok else 503

        return JSONResponse(
            content={
                "status": "ready" if all_ok else "not_ready",
                "checks": checks,
                "uptime_seconds": round(time.monotonic() - _start_time, 1),
            },
            status_code=status_code,
        )

    @app.get("/server_info")
    async def get_server_info():
        """Expose system metrics gathered from runtime utilities."""
        module = sys.modules[__name__]
        fetcher = getattr(module, "get_system_info")
        return fetcher()
