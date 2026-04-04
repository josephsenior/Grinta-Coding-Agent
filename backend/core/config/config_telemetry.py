from __future__ import annotations

from collections import Counter


class ConfigTelemetry:
    """Tracks configuration schema health metrics for monitoring."""

    def __init__(self) -> None:
        self._schema_missing = 0
        self._schema_mismatch: Counter[str] = Counter()
        self._invalid_agents: Counter[str] = Counter()
        self._invalid_base = 0

    def record_schema_missing(self) -> None:
        self._schema_missing += 1

    def record_schema_mismatch(self, provided: str | None) -> None:
        key = str(provided or 'unknown')
        self._schema_mismatch[key] += 1

    def record_invalid_agent(self, agent_name: str) -> None:
        self._invalid_agents[agent_name] += 1

    def record_invalid_base(self) -> None:
        self._invalid_base += 1

    def reset(self) -> None:
        """Reset counters (useful for tests)."""
        self._schema_missing = 0
        self._schema_mismatch.clear()
        self._invalid_agents.clear()
        self._invalid_base = 0

    def snapshot(self) -> dict[str, dict[str, int] | int]:
        return {
            'schema_missing': self._schema_missing,
            'schema_mismatch': dict(self._schema_mismatch),
            'invalid_agents': dict(self._invalid_agents),
            'invalid_base': self._invalid_base,
        }


config_telemetry = ConfigTelemetry()
