"""Metrics routes for monitoring."""

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.logger import forge_logger as logger

from . import monitoring_helpers

router = APIRouter()


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


class AgentMetrics(BaseModel):
    agent_name: str
    total_actions: int = 0
    successful_actions: int = 0
    success_rate: float = 0.0


class MetricsResponse(BaseModel):
    system: SystemMetrics
    agents: list[AgentMetrics] = Field(default_factory=list)


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """JSON-formatted system and agent metrics."""
    import time
    from backend.api.app_state import get_app_state

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

        return MetricsResponse(
            system=SystemMetrics(
                timestamp=datetime.now(),
                active_conversations=active_sessions,
                uptime_seconds=max(0, uptime),
                cache_stats=cache_stats,
                parallel_execution_stats={"enabled": True, "active_tasks": 0},
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
