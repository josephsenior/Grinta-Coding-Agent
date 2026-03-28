"""Conversation status definitions used by the server and UI layers."""

from __future__ import annotations

from enum import Enum


class ConversationStatus(str, Enum):
    """Enumerate high-level lifecycle states for a conversation."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"
    ARCHIVED = "archived"
    UNKNOWN = "unknown"

    @classmethod
    def from_runtime_status(cls, status: str | None) -> ConversationStatus:
        """Best-effort conversion from runtime status strings.

        Args:
            status: Raw runtime status reported by runtimes.

        Returns:
            Matched ConversationStatus value, defaulting to UNKNOWN.

        """
        if not status:
            return cls.UNKNOWN

        normalized = status.lower()
        if normalized in {cls.STARTING.value, "starting"}:
            return cls.STARTING
        if normalized in {cls.RUNNING.value, "active", "started"}:
            return cls.RUNNING
        if normalized in {cls.STOPPED.value, "stopped", "stopping"}:
            return cls.STOPPED
        if normalized in {cls.PAUSED.value, "paused", "pause"}:
            return cls.PAUSED
        if normalized in {cls.ARCHIVED.value, "archived", "deleted"}:
            return cls.ARCHIVED
        return cls.UNKNOWN
