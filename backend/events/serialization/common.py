"""Common serialization constants for events, actions, and observations."""

from __future__ import annotations

# Common fields that are shared across Event, Action, and Observation serialization.
# These fields are often treated as metadata or handled separately from core data.
COMMON_METADATA_FIELDS = (
    "id",
    "sequence",
    "timestamp",
    "source",
    "cause",
    "tool_call_metadata",
)

# Fields that should be ignored or handled specially during serialization.
UNDERSCORE_KEYS = list(COMMON_METADATA_FIELDS) + [
    "llm_metrics",
    "reason",
    "tool_result",
]
