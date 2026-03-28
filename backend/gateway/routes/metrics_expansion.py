"""Expanded monitoring metrics for comprehensive observability.

Adds business metrics, technical metrics, and resource tracking.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from typing import Any

# In-memory metrics store (use Redis/Prometheus in production)
_metrics_store: dict[str, Any] = defaultdict(dict)


class MetricsCollector:
    """Collects and aggregates metrics for monitoring."""

    @staticmethod
    def record_conversation_start(
        conversation_id: str, user_id: str | None = None
    ) -> None:
        """Record conversation start."""
        _metrics_store["conversations"]["started"] = (
            _metrics_store["conversations"].get("started", 0) + 1
        )
        _metrics_store["conversations"]["active"] = (
            _metrics_store["conversations"].get("active", 0) + 1
        )
        if user_id:
            _metrics_store["users"][user_id] = _metrics_store["users"].get(user_id, {})
            _metrics_store["users"][user_id]["conversations"] = (
                _metrics_store["users"][user_id].get("conversations", 0) + 1
            )

    @staticmethod
    def record_conversation_end(
        conversation_id: str, success: bool, duration: float
    ) -> None:
        """Record conversation end."""
        _metrics_store["conversations"]["ended"] = (
            _metrics_store["conversations"].get("ended", 0) + 1
        )
        _metrics_store["conversations"]["active"] = max(
            0, _metrics_store["conversations"].get("active", 0) - 1
        )

        if success:
            _metrics_store["conversations"]["successful"] = (
                _metrics_store["conversations"].get("successful", 0) + 1
            )
        else:
            _metrics_store["conversations"]["failed"] = (
                _metrics_store["conversations"].get("failed", 0) + 1
            )

        # Track duration
        durations = _metrics_store["conversations"].setdefault("durations", [])
        durations.append(duration)
        if len(durations) > 1000:  # Keep last 1000
            durations.pop(0)

    @staticmethod
    def record_llm_call(
        provider: str,
        model: str,
        cost: float,
        latency_ms: float,
        success: bool,
    ) -> None:
        """Record LLM API call."""
        key = f"{provider}:{model}"
        _metrics_store["llm_calls"][key] = _metrics_store["llm_calls"].get(
            key,
            {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "total_cost": 0.0,
                "total_latency_ms": 0.0,
            },
        )

        stats = _metrics_store["llm_calls"][key]
        stats["total"] += 1
        if success:
            stats["successful"] += 1
        else:
            stats["failed"] += 1
        stats["total_cost"] += cost
        stats["total_latency_ms"] += latency_ms

    @staticmethod
    def record_api_request(
        endpoint: str,
        method: str,
        status_code: int,
        latency_ms: float,
    ) -> None:
        """Record API request."""
        key = f"{method}:{endpoint}"
        _metrics_store["api_requests"][key] = _metrics_store["api_requests"].get(
            key,
            {
                "total": 0,
                "by_status": defaultdict(int),
                "latencies": [],
            },
        )

        stats = _metrics_store["api_requests"][key]
        stats["total"] += 1
        stats["by_status"][status_code] += 1
        stats["latencies"].append(latency_ms)
        if len(stats["latencies"]) > 1000:
            stats["latencies"].pop(0)

    @staticmethod
    def record_resource_usage(
        conversation_id: str,
        memory_mb: float,
        cpu_percent: float,
        disk_mb: float,
    ) -> None:
        """Record resource usage for a conversation."""
        _metrics_store["resources"][conversation_id] = {
            "memory_mb": memory_mb,
            "cpu_percent": cpu_percent,
            "disk_mb": disk_mb,
            "timestamp": time.time(),
        }

    @staticmethod
    def get_metrics_summary() -> dict[str, Any]:
        """Get comprehensive metrics summary."""
        conversations = _metrics_store.get("conversations", {})
        llm_calls = _metrics_store.get("llm_calls", {})
        api_requests = _metrics_store.get("api_requests", {})

        return {
            "conversations": _calculate_conversation_metrics(conversations),
            "llm": _calculate_llm_metrics(llm_calls),
            "api": _calculate_api_metrics(api_requests),
            "timestamp": datetime.now().isoformat(),
        }


def _percentile(data: list[float], p: float) -> float:
    """Calculate percentile of data."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    index = int(len(sorted_data) * p)
    return sorted_data[min(index, len(sorted_data) - 1)]


def _calculate_conversation_metrics(conversations: dict) -> dict[str, Any]:
    """Calculate conversation metrics."""
    total_conversations = conversations.get("started", 0)
    successful = conversations.get("successful", 0)
    success_rate = (
        (successful / total_conversations * 100) if total_conversations > 0 else 0
    )
    durations = conversations.get("durations", [])
    avg_duration = sum(durations) / len(durations) if durations else 0

    return {
        "total_started": total_conversations,
        "active": conversations.get("active", 0),
        "successful": successful,
        "failed": conversations.get("failed", 0),
        "success_rate_percent": round(success_rate, 2),
        "avg_duration_seconds": round(avg_duration, 2),
        "p50_duration_seconds": round(_percentile(durations, 0.5), 2),
        "p95_duration_seconds": round(_percentile(durations, 0.95), 2),
        "p99_duration_seconds": round(_percentile(durations, 0.99), 2),
    }


def _calculate_llm_metrics(llm_calls: dict) -> dict[str, Any]:
    """Calculate LLM metrics."""
    total_llm_calls = sum(stats.get("total", 0) for stats in llm_calls.values())
    total_llm_cost = sum(stats.get("total_cost", 0.0) for stats in llm_calls.values())
    total_llm_latency = sum(
        stats.get("total_latency_ms", 0.0) for stats in llm_calls.values()
    )
    avg_llm_latency = total_llm_latency / total_llm_calls if total_llm_calls > 0 else 0

    return {
        "total_calls": total_llm_calls,
        "total_cost_usd": round(total_llm_cost, 4),
        "avg_latency_ms": round(avg_llm_latency, 2),
        "by_provider": {
            key: {
                "calls": stats.get("total", 0),
                "success_rate": round(
                    stats.get("successful", 0) / stats.get("total", 1) * 100, 2
                ),
                "total_cost": round(stats.get("total_cost", 0.0), 4),
                "avg_latency_ms": round(
                    stats.get("total_latency_ms", 0.0) / stats.get("total", 1), 2
                ),
            }
            for key, stats in llm_calls.items()
        },
    }


def _calculate_api_metrics(api_requests: dict) -> dict[str, Any]:
    """Calculate API metrics."""
    total_api_requests = sum(stats.get("total", 0) for stats in api_requests.values())
    api_latencies = []
    for stats in api_requests.values():
        api_latencies.extend(stats.get("latencies", []))
    avg_api_latency = sum(api_latencies) / len(api_latencies) if api_latencies else 0

    return {
        "total_requests": total_api_requests,
        "avg_latency_ms": round(avg_api_latency, 2),
        "p50_latency_ms": round(_percentile(api_latencies, 0.5), 2),
        "p95_latency_ms": round(_percentile(api_latencies, 0.95), 2),
        "p99_latency_ms": round(_percentile(api_latencies, 0.99), 2),
        "by_endpoint": {
            key: {
                "total": stats.get("total", 0),
                "by_status": dict(stats.get("by_status", {})),
                "avg_latency_ms": round(
                    sum(stats.get("latencies", [])) / len(stats.get("latencies", [1])),
                    2,
                ),
            }
            for key, stats in api_requests.items()
        },
    }


# Global metrics collector instance
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance."""
    return _metrics_collector
