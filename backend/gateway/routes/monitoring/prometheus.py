"""Prometheus metrics routes for monitoring."""

import contextlib
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from backend.core.logger import app_logger as logger

from . import monitoring_helpers
from .metrics import get_metrics

router = APIRouter()


def _get_request_metrics_snapshot_safe() -> dict[str, Any]:
    """Get request metrics from middleware, or defaults if unavailable."""
    try:
        from backend.gateway.middleware.request_metrics import (
            get_request_metrics_snapshot,
        )

        return get_request_metrics_snapshot()
    except Exception:
        return {
            "request_count_total": 0,
            "request_exceptions_total": 0,
            "hist_buckets": {"le_inf": 0},
            "hist_sum": 0.0,
            "hist_count": 0,
        }


def _build_prom_base_lines(req: dict[str, Any], active_sessions: int) -> list[str]:
    """Build base Prometheus lines (build info, request counters, runtime gauges)."""
    request_total = int(req.get("request_count_total", 0) or 0)
    request_exceptions_total = int(req.get("request_exceptions_total", 0) or 0)
    hist_sum = float(req.get("hist_sum", 0.0) or 0.0)
    hist_count = int(req.get("hist_count", 0) or 0)
    hist_buckets = req.get("hist_buckets", {}) or {}

    lines = [
        "# HELP app_build_info Build information",
        "# TYPE app_build_info gauge",
        'app_build_info{version="1.0.0"} 1',
        "# HELP app_request_total Total HTTP requests",
        "# TYPE app_request_total counter",
        f"app_request_total {request_total}",
        "# HELP app_request_exceptions_total Total HTTP request exceptions",
        "# TYPE app_request_exceptions_total counter",
        f"app_request_exceptions_total {request_exceptions_total}",
        "# HELP app_request_duration_ms_bucket HTTP request duration histogram",
        "# TYPE app_request_duration_ms_histogram",
    ]

    lines.extend(_build_prom_histogram_lines(hist_buckets, hist_sum, hist_count))

    lines.extend(
        [
            "# HELP app_runtime_running_sessions_total Total running agent sessions",
            "# TYPE app_runtime_running_sessions_total gauge",
            f"app_runtime_running_sessions_total {active_sessions}",
            "# HELP app_runtime_warm_pool_total Total warm runtime containers",
            "# TYPE app_runtime_warm_pool_total gauge",
            "app_runtime_warm_pool_total 0",
        ]
    )
    return lines


def _build_prom_histogram_lines(
    hist_buckets: dict, hist_sum: float, hist_count: float
) -> list[str]:
    """Build Prometheus histogram bucket lines."""
    lines: list[str] = []
    try:
        numeric = []
        for key, value in hist_buckets.items():
            if isinstance(key, str) and key.startswith("le_") and key != "le_inf":
                with contextlib.suppress(Exception):
                    numeric.append((int(key.split("_", 1)[1]), int(value)))
        for bucket, value in sorted(numeric, key=lambda x: x[0]):
            lines.append(f'app_request_duration_ms_bucket{{le="{bucket}"}} {value}')
        lines.append(
            f'app_request_duration_ms_bucket{{le="+Inf"}} {int(hist_buckets.get("le_inf", 0) or 0)}'
        )
    except Exception:
        lines.append('app_request_duration_ms_bucket{le="+Inf"} 0')

    lines.append(f"app_request_duration_ms_sum {hist_sum}")
    lines.append(f"app_request_duration_ms_count {hist_count}")
    return lines


def _format_acquire_release(k: str, v: Any) -> list[str]:
    """Format acquire/release telemetry (single total)."""
    total = sum(v.values()) if isinstance(v, dict) else v
    return [f"app_runtime_{k}_total {total}"]


def _format_reuse(v: Any) -> list[str]:
    """Format reuse telemetry (per-kind labels)."""
    items = v.items() if isinstance(v, dict) else []
    return [f'app_runtime_reuse{{kind="{kind}"}} {count}' for kind, count in items]


def _format_watchdog_lines(v: Any) -> list[str]:
    """Format watchdog telemetry into prometheus lines."""
    lines: list[str] = []
    if isinstance(v, dict):
        total = 0
        for key, count in v.items():
            total += count
            if "|" in key:
                kind, reason = key.split("|", 1)
                lines.append(
                    f'app_runtime_watchdog_terminations{{kind="{kind}",reason="{reason}"}} {count}'
                )
        lines.append(f"app_runtime_watchdog_terminations_total {total}")
    return lines


def _format_scaling_lines(v: Any) -> list[str]:
    """Format scaling telemetry into prometheus lines."""
    if not isinstance(v, dict):
        return []
    lines: list[str] = []
    for key, count in v.items():
        if "|" in key:
            signal, kind = key.split("|", 1)
            lines.append(
                f'app_runtime_scaling_signals{{kind="{kind}",signal="{signal}"}} {count}'
            )
    return lines


def _format_telemetry_key(k: str, v: Any) -> list[str]:
    """Format a single telemetry key/value into prometheus lines."""
    handlers: dict[str, Callable[[Any], list[str]]] = {
        "acquire": lambda x: _format_acquire_release("acquire", x),
        "release": lambda x: _format_acquire_release("release", x),
        "reuse": _format_reuse,
        "watchdog": _format_watchdog_lines,
        "scaling": _format_scaling_lines,
    }
    if k in handlers:
        return handlers[k](v)
    if isinstance(v, dict):
        return [f'app_runtime_{k}{{type="{label}"}} {val}' for label, val in v.items()]
    return [f"app_runtime_{k} {v}"]


def _extract_telemetry_prom_lines(stats: dict[str, Any]) -> list[str]:
    """Extract prometheus lines from telemetry stats."""
    lines: list[str] = []
    for k, v in stats.items():
        lines.extend(_format_telemetry_key(k, v))
    return lines


def _extract_pool_prom_lines() -> list[str]:
    """Extract prometheus lines from runtime orchestrator pool stats."""
    lines: list[str] = []
    if not monitoring_helpers.runtime_orchestrator:
        return lines

    if hasattr(monitoring_helpers.runtime_orchestrator, "pool_stats"):
        pool_stats = monitoring_helpers.runtime_orchestrator.pool_stats()
        total = 0
        for pool_type, count in pool_stats.items():
            total += count
            lines.append(f'app_runtime_pool_size{{kind="{pool_type}"}} {count}')
        lines.append(f"app_runtime_pool_size_total {total}")

    if hasattr(monitoring_helpers.runtime_orchestrator, "idle_reclaim_stats"):
        idle_stats = monitoring_helpers.runtime_orchestrator.idle_reclaim_stats()
        total = sum(idle_stats.values())
        for kind, count in idle_stats.items():
            lines.append(f'app_runtime_pool_idle_reclaim{{kind="{kind}"}} {count}')
        lines.append(f"app_runtime_pool_idle_reclaim_total {total}")

    if hasattr(monitoring_helpers.runtime_orchestrator, "eviction_stats"):
        eviction_stats = monitoring_helpers.runtime_orchestrator.eviction_stats()
        total = sum(eviction_stats.values())
        for kind, count in eviction_stats.items():
            lines.append(f'app_runtime_pool_eviction{{kind="{kind}"}} {count}')
        lines.append(f"app_runtime_pool_eviction_total {total}")

    return lines


def _extract_watchdog_prom_lines() -> list[str]:
    """Extract prometheus lines from runtime watchdog stats."""
    lines = []
    if monitoring_helpers.runtime_watchdog and hasattr(monitoring_helpers.runtime_watchdog, "stats"):
        wd_stats = monitoring_helpers.runtime_watchdog.stats()
        total = sum(wd_stats.values())
        for kind, count in wd_stats.items():
            lines.append(f'app_runtime_watchdog_watched{{kind="{kind}"}} {count}')
        lines.append(f"app_runtime_watchdog_watched_total {total}")
    return lines


def _runtime_orchestrator_prom_lines() -> list[str]:
    """Helper for prometheus runtime metrics."""
    lines = []
    try:
        from backend.execution import telemetry as telemetry_module

        telemetry = getattr(telemetry_module, "runtime_telemetry", None)
        if telemetry:
            lines.extend(_extract_telemetry_prom_lines(telemetry.snapshot()))

        lines.extend(_extract_pool_prom_lines())
        lines.extend(_extract_watchdog_prom_lines())

    except Exception:
        logger.debug("Failed to collect runtime orchestrator prom lines", exc_info=True)
    return lines


def _format_schema_missing(v: Any) -> list[str]:
    return [f"app_agent_config_schema_missing_total {v}"]


def _format_schema_mismatch(v: Any) -> list[str]:
    return [
        f'app_agent_config_schema_mismatch{{version="{ver}"}} {count}'
        for ver, count in (v.items() if isinstance(v, dict) else [])
    ]


def _format_invalid_agents(v: Any) -> list[str]:
    return [
        f'app_agent_config_invalid_section{{agent="{agent}"}} {count}'
        for agent, count in (v.items() if isinstance(v, dict) else [])
    ]


def _format_config_schema_key(k: str, v: Any) -> list[str]:
    """Format a single config schema stats key into prometheus lines."""
    handlers: dict[str, Callable[[Any], list[str]]] = {
        "schema_missing": _format_schema_missing,
        "schema_mismatch": _format_schema_mismatch,
        "invalid_agents": _format_invalid_agents,
    }
    if k in handlers:
        return handlers[k](v)
    if k == "invalid_base":
        return [f"app_agent_config_invalid_base_total {v}"]
    if isinstance(v, dict):
        return [
            f'app_agent_config_{k}_total{{version="{label}"}} {val}'
            for label, val in v.items()
        ]
    return [f"app_agent_config_{k}_total {v}"]


def _config_schema_prom_lines() -> list[str]:
    """Helper for prometheus config metrics."""
    lines: list[str] = []
    try:
        if monitoring_helpers.config_telemetry:
            stats = monitoring_helpers.config_telemetry.snapshot()
            for k, v in stats.items():
                lines.extend(_format_config_schema_key(k, v))
    except Exception:
        logger.debug("Failed to collect config schema prom lines", exc_info=True)
    return lines


@router.get("/metrics-prom", response_class=PlainTextResponse)
async def get_prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    metrics = await get_metrics()
    active_sessions = metrics.system.active_conversations

    req = _get_request_metrics_snapshot_safe()
    lines = _build_prom_base_lines(req, active_sessions)
    try:
        lines.extend(_runtime_orchestrator_prom_lines())
    except Exception:
        logger.debug("Failed to collect runtime orchestrator metrics", exc_info=True)
    try:
        lines.extend(_config_schema_prom_lines())
    except Exception:
        logger.debug("Failed to collect config schema metrics", exc_info=True)

    return "\n".join(lines) + "\n"
