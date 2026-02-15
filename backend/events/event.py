"""Event system for agent actions and observations.

Classes:
    EventSource
    FileEditSource
    FileReadSource
    RecallType
    Event

Functions:
    message
    id
    timestamp
    timestamp
    source
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from backend.core.schemas import EventSource, RecallType
from backend.events.tool import ToolCallMetadata

if TYPE_CHECKING:
    from backend.llm.metrics import Metrics


@dataclass
class Event:
    """Base dataclass for stream events emitted by the runtime."""

    INVALID_ID = -1

    @property
    def message(self) -> str | None:
        """Get human-readable message for this event."""
        if hasattr(self, "_message"):
            msg = self._message
            return str(msg) if msg is not None else None
        return ""

    @property
    def id(self) -> int:
        """Get event ID (assigned when added to event stream)."""
        if hasattr(self, "_id"):
            id_val = self._id
            return int(id_val) if id_val is not None else Event.INVALID_ID
        return Event.INVALID_ID

    @id.setter
    def id(self, value: int | None) -> None:
        """Set event ID."""
        self._id = value

    @property
    def sequence(self) -> int:
        """Sequence number for guaranteed event ordering."""
        if hasattr(self, "_sequence"):
            seq_val = self._sequence
            return int(seq_val) if seq_val is not None else Event.INVALID_ID
        return Event.INVALID_ID

    @sequence.setter
    def sequence(self, value: int | None) -> None:
        """Set event sequence number."""
        self._sequence = value

    @property
    def timestamp(self) -> str | None:
        """Get event timestamp in ISO format."""
        if hasattr(self, "_timestamp") and isinstance(self._timestamp, str):
            ts = self._timestamp
            return str(ts) if ts is not None else None
        return None

    @timestamp.setter
    def timestamp(self, value: datetime) -> None:
        """Set event timestamp from datetime object."""
        if isinstance(value, datetime):
            self._timestamp = value.isoformat()

    @property
    def source(self) -> EventSource | None:
        """Get event source (USER, AGENT, ENVIRONMENT, etc.)."""
        if hasattr(self, "_source"):
            src = self._source
            return EventSource(src) if src is not None else None
        return None

    @source.setter
    def source(self, value: EventSource | str | None) -> None:
        """Set event source.

        Accepts ``EventSource`` enum members, raw strings from serialized
        payloads, or ``None``.
        """
        if value is None:
            self._source = None
        elif isinstance(value, EventSource):
            self._source = value.value
        elif isinstance(value, str):
            # Validate that the string corresponds to a known EventSource
            try:
                self._source = EventSource(value).value
            except ValueError:
                self._source = value  # preserve unknown sources from old payloads
        else:
            raise TypeError(f"source must be EventSource, str, or None — got {type(value).__name__}")

    @property
    def cause(self) -> int | None:
        """Get ID of event that caused this event."""
        if hasattr(self, "_cause"):
            cause_val = self._cause
            return int(cause_val) if cause_val is not None else None
        return None

    @cause.setter
    def cause(self, value: int | None) -> None:
        """Set ID of event that caused this event."""
        self._cause = value

    @property
    def hidden(self) -> bool:
        """Return whether this event is hidden."""
        return bool(getattr(self, "_hidden", False))

    @hidden.setter
    def hidden(self, value: bool) -> None:
        """Set whether this event is hidden."""
        self._hidden = value

    @property
    def timeout(self) -> float | None:
        """Get timeout value in seconds."""
        if hasattr(self, "_timeout"):
            timeout_val = self._timeout
            return float(timeout_val) if timeout_val is not None else None
        return None

    def set_hard_timeout(self, value: float | None, blocking: bool = True) -> None:
        """Set the timeout for the event.

        NOTE, this is a hard timeout, meaning that the event will be blocked
        until the timeout is reached.
        """
        self._timeout = value
        if hasattr(self, "blocking"):
            self.blocking = blocking

    @property
    def llm_metrics(self) -> Metrics | None:
        """Get LLM metrics attached to this event."""
        try:
            from backend.llm.metrics import Metrics

            if hasattr(self, "_llm_metrics"):
                metrics = self._llm_metrics
                return metrics if isinstance(metrics, Metrics) else None
            return None
        except Exception:
            return None

    @llm_metrics.setter
    def llm_metrics(self, value: Metrics) -> None:
        """Set LLM metrics for this event."""
        self._llm_metrics = value

    @property
    def tool_call_metadata(self) -> ToolCallMetadata | None:
        """Get tool call metadata if this event involved tool calls."""
        if not hasattr(self, "_tool_call_metadata"):
            return None
        metadata_raw: Any = self._tool_call_metadata
        # Be resilient to monkeypatched ToolCallMetadata classes in unit tests.
        # Accept any object that exposes the expected attributes instead of requiring exact class identity.
        if metadata_raw is None:
            return None
        if isinstance(metadata_raw, ToolCallMetadata):  # fast path
            return metadata_raw
        required_attrs = {"function_name", "tool_call_id", "total_calls_in_response"}
        if all(hasattr(metadata_raw, attr) for attr in required_attrs):
            return cast(ToolCallMetadata, metadata_raw)  # permissive acceptance for test doubles
        return None

    @tool_call_metadata.setter
    def tool_call_metadata(self, value: ToolCallMetadata | None) -> None:
        """Set tool call metadata."""
        self._tool_call_metadata = value

    @property
    def response_id(self) -> str | None:
        """Get LLM response ID for this event."""
        return self._response_id if hasattr(self, "_response_id") else None

    @response_id.setter
    def response_id(self, value: str) -> None:
        """Set LLM response ID."""
        self._response_id = value
