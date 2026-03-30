"""Metrics routes for monitoring."""

import asyncio
import math
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.logger import app_logger as logger

from . import monitoring_helpers

router = APIRouter()


class LspMetricsResponse(BaseModel):
    sessions_scanned: int = 0
    samples: int = 0
    failures: int = 0
    failure_rate: float = 0.0
    latency_ms: dict[str, float] = Field(default_factory=dict)


class SystemMetrics(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    active_conversations: int = 0
    total_actions_today: int = 0
    avg_response_time_ms: float = 0.0
    uptime_seconds: float = 0.0
    memory_usage_mb: float = 0.0
    cache_stats: dict[str, Any] = Field(default_factory=dict)
    parallel_execution_stats: dict[str, Any] = Field(default_factory=dict)
    tool_usage: dict[str, int] = Field(default_factory=dict)
    failure_distribution: dict[str, int] = Field(default_factory=dict)
    lsp: LspMetricsResponse = Field(default_factory=LspMetricsResponse)


class AgentMetrics(BaseModel):
    agent_name: str
    total_actions: int = 0
    successful_actions: int = 0
    success_rate: float = 0.0


class MetricsResponse(BaseModel):
    system: SystemMetrics
    agents: list[AgentMetrics] = Field(default_factory=list)


def _percentile(sorted_values: list[int], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = max(0, min(len(sorted_values) - 1, math.ceil(pct * len(sorted_values)) - 1))
    return float(sorted_values[rank])


def _iter_recent_events_for_session(session: Any, limit: int) -> list[Any]:
    controller = getattr(session, "controller", None)
    event_stream = getattr(controller, "event_stream", None) if controller is not None else None
    if event_stream is None or not hasattr(event_stream, "search_events"):
        return []
    try:
        return list(event_stream.search_events(reverse=True, limit=limit))
    except Exception:
        logger.debug("Failed to read event stream for LSP metrics", exc_info=True)
        return []


def _extract_lsp_sample(event: Any) -> tuple[int, bool] | None:
    tool_result = getattr(event, "tool_result", None)
    if not isinstance(tool_result, dict):
        return None
    if str(tool_result.get("tool", "")).lower() != "lsp_query":
        return None
    latency = tool_result.get("latency_ms", 0)
    try:
        latency_ms = max(0, int(float(latency)))
    except Exception:
        latency_ms = 0
    has_error = bool(tool_result.get("has_error", False))
    return latency_ms, has_error


def _get_lsp_metrics_event_limit() -> int:
    return max(50, int(os.getenv("APP_LSP_METRICS_EVENT_LIMIT", "400")))


def _collect_lsp_metrics(manager: Any) -> LspMetricsResponse:
    if not manager:
        return LspMetricsResponse()

    sessions = monitoring_helpers.get_conversation_sessions(manager)
    per_session_limit = _get_lsp_metrics_event_limit()

    latencies: list[int] = []
    failures = 0
    sessions_scanned = 0

    for session in sessions.values():
        sessions_scanned += 1
        for event in _iter_recent_events_for_session(session, per_session_limit):
            sample = _extract_lsp_sample(event)
            if sample is None:
                continue
            latency_ms, has_error = sample
            latencies.append(latency_ms)
            if has_error:
                failures += 1

    if not latencies:
        return LspMetricsResponse(sessions_scanned=sessions_scanned)

    latencies.sort()
    total = len(latencies)

    return LspMetricsResponse(
        sessions_scanned=sessions_scanned,
        samples=total,
        failures=failures,
        failure_rate=round(failures / total, 4),
        latency_ms={
            "min": float(latencies[0]),
            "avg": round(float(sum(latencies)) / total, 2),
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "max": float(latencies[-1]),
        },
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """JSON-formatted system and agent metrics."""
    import time
    from backend.gateway.app_state import get_app_state

    try:
        manager = monitoring_helpers.get_manager()
        active_sessions = 0
        if manager:
            if hasattr(manager, "get_active_conversations"):
                convos = manager.get_active_conversations()
                if asyncio.iscoroutine(convos):
                    convos = await convos
                active_sessions = len(convos)
            elif hasattr(manager, "sessions"):
                active_sessions = len(manager.sessions)
            elif hasattr(manager, "_active_conversations"):
                active_sessions = len(getattr(manager, "_active_conversations"))

        uptime = time.time() - getattr(
            get_app_state().server_config, "_start_time", time.time()
        )

        cache_stats = {}
        try:
            from backend.core.cache import get_async_smart_cache

            cache = await get_async_smart_cache()
            if cache:
                cache_stats["async_smart_cache"] = await cache.get_cache_stats()
        except Exception:
            logger.debug("Failed to collect cache stats", exc_info=True)

        lsp_metrics = _collect_lsp_metrics(manager)

        return MetricsResponse(
            system=SystemMetrics(
                timestamp=datetime.now(),
                active_conversations=active_sessions,
                uptime_seconds=max(0, uptime),
                cache_stats=cache_stats,
                parallel_execution_stats={"enabled": True, "active_tasks": 0},
                lsp=lsp_metrics,
            ),
            agents=[AgentMetrics(agent_name="Orchestrator")],
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e)) from e


def _collect_session_metrics(
    convos: dict,
) -> tuple[list[dict[str, Any]], int]:
    """Collect metrics from all sessions. Returns (all_metrics, active_sessions)."""
    all_metrics: list[dict[str, Any]] = []
    active_sessions = 0

    for session in convos.values():
        controller = getattr(session, "controller", None)
        if controller is None:
            continue
        services = getattr(controller, "services", None)
        if services is None:
            continue
        metrics_service = getattr(services, "metrics", None)
        if metrics_service is None:
            continue

        active_sessions += 1
        aggregate = metrics_service.get_aggregate_metrics()
        if aggregate:
            all_metrics.append(
                {
                    "total_tasks": len(aggregate.tasks),
                    "success_rate": aggregate.success_rate,
                    "average_duration": aggregate.average_duration,
                    "average_cost": aggregate.average_cost,
                }
            )

    return all_metrics, active_sessions


def _aggregate_agent_metrics(
    all_metrics: list[dict[str, Any]], active_sessions: int
) -> dict[str, Any]:
    """Compute overall aggregates from per-session metrics."""
    if not all_metrics:
        return {
            "total_tasks": 0,
            "success_rate": 0.0,
            "average_duration_seconds": 0.0,
            "average_cost_usd": 0.0,
            "active_sessions": active_sessions,
        }

    total_tasks = sum(m["total_tasks"] for m in all_metrics)
    weighted_success = sum(
        m["success_rate"] * m["total_tasks"] for m in all_metrics
    )
    avg_success_rate = weighted_success / total_tasks if total_tasks > 0 else 0.0
    avg_duration = sum(m["average_duration"] for m in all_metrics) / len(all_metrics)
    avg_cost = sum(m["average_cost"] for m in all_metrics) / len(all_metrics)

    return {
        "total_tasks": total_tasks,
        "success_rate": round(avg_success_rate, 4),
        "average_duration_seconds": round(avg_duration, 2),
        "average_cost_usd": round(avg_cost, 6),
        "active_sessions": active_sessions,
    }


@router.get("/agent-metrics")
async def get_agent_metrics():
    """Aggregate agent performance metrics across all active sessions."""
    try:
        manager = monitoring_helpers.get_manager()
        if not manager:
            return {
                "total_tasks": 0,
                "success_rate": 0.0,
                "average_duration_seconds": 0.0,
                "average_cost_usd": 0.0,
                "active_sessions": 0,
            }

        convos = monitoring_helpers.get_conversation_sessions(manager)
        all_metrics, active_sessions = _collect_session_metrics(convos)
        return _aggregate_agent_metrics(all_metrics, active_sessions)
    except Exception as e:
        logger.error("Failed to collect agent metrics", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/lsp-metrics", response_model=LspMetricsResponse)
async def get_lsp_metrics():
    """Aggregate LSP query reliability and latency metrics from recent session events."""
    try:
        manager = monitoring_helpers.get_manager()
        return _collect_lsp_metrics(manager)
    except Exception as e:
        logger.error("Failed to collect LSP metrics", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
