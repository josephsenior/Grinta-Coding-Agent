"""Aggregated event-stream statistics across all live instances.

Extracted from :mod:`backend.ledger.stream` to keep module sizes within
the repository guideline (~400 LOC).
"""

from __future__ import annotations

from backend.core.logger import forge_logger as logger
from backend.ledger.stream import EventStream


def get_aggregated_event_stream_stats() -> dict[str, int]:
    """Aggregate stats across all live EventStream instances.

    Returns:
        Dictionary with summed counters and total queue size.
    """
    totals: dict[str, int] = {
        "streams": 0,
        "enqueued": 0,
        "dropped_oldest": 0,
        "dropped_newest": 0,
        "high_watermark_hits": 0,
        "persist_failures": 0,
        "cache_write_failures": 0,
        "critical_events": 0,
        "critical_queue_blocked": 0,
        "critical_sync_persistence": 0,
        "durable_enqueue_failures": 0,
        "durable_writer_drops": 0,
        "durable_writer_queue_depth": 0,
        "durable_writer_errors": 0,
        "events_per_minute": 0,
        "drops_per_minute": 0,
        "persist_failures_per_minute": 0,
        "queue_utilization_pct_avg": 0,
        "uptime_seconds_sum": 0,
        "queue_size": 0,
    }
    # Copy to list to avoid mutation during iteration
    for stream in EventStream.iter_global_streams():
        try:
            stats = stream.get_backpressure_snapshot()
            totals["streams"] += 1
            totals["enqueued"] += stats.get("enqueued", 0)
            totals["dropped_oldest"] += stats.get("dropped_oldest", 0)
            totals["dropped_newest"] += stats.get("dropped_newest", 0)
            totals["high_watermark_hits"] += stats.get("high_watermark_hits", 0)
            totals["persist_failures"] += stats.get("persist_failures", 0)
            totals["cache_write_failures"] += stats.get("cache_write_failures", 0)
            totals["critical_events"] += stats.get("critical_events", 0)
            totals["critical_queue_blocked"] += stats.get("critical_queue_blocked", 0)
            totals["critical_sync_persistence"] += stats.get(
                "critical_sync_persistence", 0
            )
            totals["durable_enqueue_failures"] += stats.get(
                "durable_enqueue_failures", 0
            )
            totals["durable_writer_drops"] += stats.get("durable_writer_drops", 0)
            totals["durable_writer_queue_depth"] += stats.get(
                "durable_writer_queue_depth", 0
            )
            totals["durable_writer_errors"] += stats.get("durable_writer_errors", 0)
            totals["events_per_minute"] += stats.get("events_per_minute", 0)
            totals["drops_per_minute"] += stats.get("drops_per_minute", 0)
            totals["persist_failures_per_minute"] += stats.get(
                "persist_failures_per_minute", 0
            )
            totals["queue_utilization_pct_avg"] += stats.get("queue_utilization_pct", 0)
            totals["uptime_seconds_sum"] += stats.get("uptime_seconds", 0)
            totals["queue_size"] += stats.get("queue_size", 0)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Aggregation: skipping broken EventStream: %s", exc)
            continue
    if totals["streams"] > 0:
        totals["queue_utilization_pct_avg"] = int(
            round(totals["queue_utilization_pct_avg"] / totals["streams"])
        )
    return totals
