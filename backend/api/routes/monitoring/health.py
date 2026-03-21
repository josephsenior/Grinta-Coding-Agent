"""Health check routes for monitoring."""

import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.controller import collect_controller_health as _collect_controller_health
from backend.core.logger import forge_logger as logger
from backend.events.stream import get_aggregated_event_stream_stats
from backend.runtime.utils.process_manager import (
    get_process_manager_health_snapshot as _get_process_manager_health_snapshot,
)

from . import monitoring_helpers

router = APIRouter()


def _event_stream_thresholds() -> dict[str, int]:
    return {
        "drops_per_minute_yellow": max(
            1, monitoring_helpers.int_env("FORGE_EVENTSTREAM_DROPS_YELLOW", 5)
        ),
        "drops_per_minute_red": max(1, monitoring_helpers.int_env("FORGE_EVENTSTREAM_DROPS_RED", 20)),
        "queue_utilization_yellow": max(
            1, min(100, monitoring_helpers.int_env("FORGE_EVENTSTREAM_QUEUE_UTIL_YELLOW", 80))
        ),
        "queue_utilization_red": max(
            1, min(100, monitoring_helpers.int_env("FORGE_EVENTSTREAM_QUEUE_UTIL_RED", 95))
        ),
    }


def _event_stream_recommendations(warnings: list[str]) -> list[str]:
    recs: list[str] = []
    if "event_stream_persist_failures" in warnings:
        recs.append("inspect_event_storage_and_write_permissions")
    if "event_stream_durable_writer_errors" in warnings:
        recs.append("inspect_durable_writer_runtime_and_disk_health")
    if "event_stream_durable_enqueue_failures" in warnings:
        recs.append("increase_durable_writer_capacity_or_reduce_emit_rate")
    if "event_stream_drops_rate_high" in warnings:
        recs.append("increase_queue_size_or_reduce_event_bursting")
    if "event_stream_queue_utilization_high" in warnings:
        recs.append("increase_delivery_workers_or_queue_capacity")
    if "event_stream_critical_blocked" in warnings:
        recs.append("investigate_blocked_critical_event_delivery")
    return recs


def _event_stream_severity(warnings: list[str]) -> str:
    red_markers = {
        "event_stream_persist_failures",
        "event_stream_durable_writer_errors",
        "event_stream_durable_enqueue_failures",
        "event_stream_drops_rate_high",
    }
    if any(marker in red_markers for marker in warnings):
        return "red"
    if warnings:
        return "yellow"
    return "green"


def _collect_event_stream_warnings(
    stats: dict[str, Any], thresholds: dict[str, int]
) -> list[str]:
    """Collect warnings based on event stream stats and thresholds."""
    warnings = _check_count_warnings(stats)
    warnings.extend(_check_threshold_warnings(stats, thresholds))
    return warnings


def _check_count_warnings(stats: dict[str, Any]) -> list[str]:
    """Check stats that trigger a warning if > 0."""
    count_keys = [
        ("dropped_oldest", "event_stream_dropped_oldest"),
        ("dropped_newest", "event_stream_dropped_newest"),
        ("persist_failures", "event_stream_persist_failures"),
        ("durable_writer_errors", "event_stream_durable_writer_errors"),
        ("durable_enqueue_failures", "event_stream_durable_enqueue_failures"),
        ("critical_queue_blocked", "event_stream_critical_blocked"),
    ]
    return [
        w for k, w in count_keys
        if int(stats.get(k, 0) or 0) > 0
    ]


def _check_threshold_warnings(
    stats: dict[str, Any], thresholds: dict[str, int]
) -> list[str]:
    """Check drops_per_minute and queue_utilization against thresholds."""
    warnings: list[str] = []
    dpm = int(stats.get("drops_per_minute", 0) or 0)
    if dpm >= int(thresholds["drops_per_minute_yellow"]):
        warnings.append("event_stream_drops_rate_elevated")
    if dpm >= int(thresholds["drops_per_minute_red"]):
        warnings.append("event_stream_drops_rate_high")

    util = int(stats.get("queue_utilization_pct_avg", 0) or 0)
    if util >= int(thresholds["queue_utilization_yellow"]):
        warnings.append("event_stream_queue_utilization_elevated")
    if util >= int(thresholds["queue_utilization_red"]):
        warnings.append("event_stream_queue_utilization_high")
    return warnings


@router.get("/health")
async def get_health():
    """Detailed health check for all system components."""
    event_stream = await event_stream_health()
    process_health = await process_manager_health()
    overall = "healthy"
    if (
        event_stream.get("status") == "unhealthy"
        or process_health.get("status") == "unhealthy"
    ):
        overall = "unhealthy"
    elif (
        event_stream.get("status") == "degraded"
        or process_health.get("status") == "degraded"
    ):
        overall = "degraded"
    return {
        "status": overall,
        "timestamp": time.time(),
        "version": "1.0.0",
        "services": {
            "database": "connected",
            "redis": "connected" if os.getenv("REDIS_URL") else "not_configured",
            "storage": "available",
            "event_stream": event_stream.get("status", "healthy"),
            "process_manager": process_health.get("status", "healthy"),
        },
    }


@router.get("/event-stream/health")
async def event_stream_health():
    """Aggregate EventStream backpressure and durability health across sessions."""
    stats = get_aggregated_event_stream_stats()
    thresholds = _event_stream_thresholds()
    warnings = _collect_event_stream_warnings(stats, thresholds)

    severity = _event_stream_severity(warnings)
    status = monitoring_helpers.status_from_severity(severity)
    recommendations = _event_stream_recommendations(warnings)

    return {
        "status": status,
        "severity": severity,
        "timestamp": time.time(),
        "thresholds": thresholds,
        "stats": stats,
        "warnings": warnings,
        "recommendations": recommendations,
        "version": 1,
    }


@router.get("/controller/{sid}/health")
async def controller_health(sid: str):
    """Health status of a specific agent controller."""
    manager = monitoring_helpers.get_manager()
    if not manager:
        raise HTTPException(status_code=404, detail="Manager not found")

    session = manager.get_agent_session(sid)
    if not session or not session.controller:
        raise HTTPException(status_code=404, detail="Session or controller not found")

    health_info = {"status": "healthy"}
    func = _collect_controller_health
    if func:
        health_info.update(func(session.controller))
    severity = str(health_info.get("severity", "green"))
    health_info["status"] = monitoring_helpers.status_from_severity(severity)

    return health_info


def collect_controller_health(controller: Any) -> dict[str, Any]:
    """Collect health info from a controller. Re-exported for tests."""
    return _collect_controller_health(controller)


@router.get("/processes/health")
async def process_manager_health():
    """Health status of the process manager."""
    health: dict[str, Any] = {"status": "healthy"}
    health.update(get_process_manager_health_snapshot())
    if health.get("severity") in {"yellow", "red"}:
        health["status"] = monitoring_helpers.status_from_severity(str(health.get("severity")))
    else:
        warnings = health.get("warnings")
        if isinstance(warnings, list) and warnings:
            health["status"] = "degraded"
    return health


def get_process_manager_health_snapshot() -> dict[str, Any]:
    """Get process manager health. Re-exported for tests."""
    active_processes: list[Any] = []
    manager = monitoring_helpers.get_manager()
    if manager and hasattr(manager, "sessions"):
        sessions = getattr(manager, "sessions", {})
        if isinstance(sessions, dict):
            for session in sessions.values():
                runtime = getattr(session, "runtime", None)
                process_manager = getattr(runtime, "process_manager", None)
                if process_manager and hasattr(
                    process_manager, "get_running_processes"
                ):
                    try:
                        active_processes.extend(process_manager.get_running_processes())
                    except Exception:
                        logger.debug(
                            "Failed to collect processes from session", exc_info=True
                        )
    return _get_process_manager_health_snapshot(active_processes=active_processes)
