"""Shared state and helpers for monitoring routes."""

import os
from typing import Any

from backend.api.app_state import get_app_state

# For testing monkeypatching
conversation_manager = None


def get_manager() -> Any:
    """Get the conversation manager from app state or test override."""
    if conversation_manager is not None:
        return conversation_manager  # type: ignore[unreachable]
    return get_app_state().get_conversation_manager()


def status_from_severity(severity: str) -> str:
    """Map severity to health status."""
    if severity == "red":
        return "unhealthy"
    if severity == "yellow":
        return "degraded"
    return "healthy"


def int_env(name: str, default: int) -> int:
    """Read integer from environment."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def get_conversation_sessions(manager: Any) -> dict:
    """Extract conversation sessions dict from manager."""
    if hasattr(manager, "_active_conversations"):
        return dict(getattr(manager, "_active_conversations", {}))
    if hasattr(manager, "sessions"):
        return dict(getattr(manager, "sessions", {}))
    return {}


# Telemetry placeholders for tests
class TelemetryPlaceholder:
    def snapshot(self):
        return {}


class OrchestratorPlaceholder:
    def pool_stats(self):
        return {}

    def idle_reclaim_stats(self):
        return {}

    def eviction_stats(self):
        return {}


class WatchdogPlaceholder:
    def stats(self):
        return {}


config_telemetry = TelemetryPlaceholder()
runtime_telemetry = TelemetryPlaceholder()
runtime_orchestrator = OrchestratorPlaceholder()
runtime_watchdog = WatchdogPlaceholder()
