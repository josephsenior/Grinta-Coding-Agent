"""Health and diagnostics endpoints for the App server."""

import os
import shutil
import socket
import sys
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.execution.utils import system_stats


def get_system_info() -> dict:
    """Proxy to runtime system stats for easier monkeypatching in tests."""
    return system_stats.get_system_info()


def _check_storage() -> dict:
    """Validate that the file-store directory is writable."""
    try:
        from backend.persistence.locations import get_local_data_root

        store_path = get_local_data_root()
        writable = os.path.isdir(store_path) and os.access(store_path, os.W_OK)
        return {"status": "ok" if writable else "degraded", "path": str(store_path)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_config() -> dict:
    """Validate that the core config is loadable."""
    try:
        from backend.core.config import load_app_config

        cfg = load_app_config()
        return {
            "status": "ok",
            "project_root": str(getattr(cfg, "project_root", None) or ""),
            "local_data_root": str(getattr(cfg, "local_data_root", "") or ""),
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_dependency_endpoint(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_redis() -> dict:
    host = os.environ.get('REDIS_HOST', '').strip()
    url = os.environ.get('REDIS_URL', '').strip()
    if not host and not url:
        return {"status": "not_configured"}

    if host:
        try:
            port = int(os.environ.get('REDIS_PORT', '6379'))
        except ValueError:
            port = 6379
        reachable = _check_dependency_endpoint(host, port)
        return {
            "status": "ok" if reachable else "degraded",
            "host": host,
            "port": port,
            "reachable": reachable,
        }

    return {"status": "configured", "url": "set", "reachable": "unknown"}


def _check_database() -> dict:
    storage_mode = os.environ.get('APP_KB_STORAGE_TYPE', 'file').strip().lower()
    if storage_mode not in {'database', 'db'}:
        return {"status": "not_configured", "mode": storage_mode or 'file'}

    db_url = os.environ.get('DATABASE_URL', '').strip()
    if not db_url:
        return {
            "status": "error",
            "mode": storage_mode,
            "detail": "DATABASE_URL missing",
        }

    host = os.environ.get('POSTGRES_HOST', 'postgres').strip()
    try:
        port = int(os.environ.get('POSTGRES_PORT', '5432'))
    except ValueError:
        port = 5432
    reachable = _check_dependency_endpoint(host, port)
    return {
        "status": "ok" if reachable else "degraded",
        "mode": storage_mode,
        "host": host,
        "port": port,
        "reachable": reachable,
    }


def _check_tmux() -> dict:
    tmux_path = shutil.which('tmux')
    if tmux_path is None:
        return {"status": "degraded", "available": False}
    return {
        "status": "ok",
        "available": True,
        "path": tmux_path,
        "tmux_tmpdir": os.environ.get('TMUX_TMPDIR', ''),
    }


def _check_recovery() -> dict:
    """Expose recent restore provenance and aggregate event persistence health."""
    try:
        from backend.gateway.app_state import get_app_state
        from backend.ledger.stream_stats import get_aggregated_event_stream_stats

        app_state = get_app_state()
        stream_stats = get_aggregated_event_stream_stats()
        status = "ok"
        if stream_stats.get("persist_failures", 0) > 0 or stream_stats.get(
            "durable_writer_errors", 0
        ) > 0:
            status = "degraded"
        return {
            "status": status,
            "state_restores": app_state.get_state_restore_snapshot(limit=10),
            "event_streams": stream_stats,
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_startup() -> dict:
    """Expose the latest canonical startup snapshot for operators."""
    try:
        from backend.gateway.app_state import get_app_state

        snapshot = get_app_state().get_startup_snapshot()
        if not snapshot:
            return {"status": "unknown"}
        return {"status": "ok", "server": snapshot}
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

        Checks critical subsystems (config, file store) and includes non-critical
        dependency diagnostics (redis/database/tmux) for debugging.

        Returns 200 if critical checks pass, 503 if a critical check fails.
        """
        config_check = _check_config()
        storage_check = _check_storage()
        redis_check = _check_redis()
        database_check = _check_database()
        tmux_check = _check_tmux()
        recovery_check = _check_recovery()
        startup_check = _check_startup()

        checks = {
            "config": config_check,
            "storage": storage_check,
            "redis": redis_check,
            "database": database_check,
            "tmux": tmux_check,
            "recovery": recovery_check,
            "startup": startup_check,
        }

        all_ok = all(
            c.get("status") == "ok"
            for c in (config_check, storage_check)
        )
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
