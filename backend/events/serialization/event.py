"""Serialization helpers for converting events to and from dictionaries."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from backend.core.pydantic_compat import model_dump_with_options
from backend.events.event import Event, EventSource
from backend.events.serialization.action import action_from_dict
from backend.events.serialization.observation import observation_from_dict
from backend.events.serialization.utils import remove_fields
from backend.events.tool import ToolCallMetadata
from backend.llm.metrics import Cost, Metrics, ResponseLatency, TokenUsage

TOP_KEYS = [
    "id",
    "sequence",
    "timestamp",
    "source",
    "message",
    "cause",
    "action",
    "observation",
    "tool_call_metadata",
    "llm_metrics",
]
from backend.events.serialization.common import UNDERSCORE_KEYS

DELETE_FROM_TRAJECTORY_EXTRAS = {
    "dom_object",
    "axtree_object",
    "active_page_index",
    "last_browser_action",
    "last_browser_action_error",
    "focused_element_bid",
    "extra_element_properties",
}
DELETE_FROM_TRAJECTORY_EXTRAS_AND_SCREENSHOTS = DELETE_FROM_TRAJECTORY_EXTRAS | {
    "screenshot",
    "set_of_marks",
}


def event_from_dict(data: dict[str, Any]) -> Event:
    """Convert dictionary to Event object."""
    evt = _create_event_from_data(data)
    _process_underscore_keys(evt, data)
    return evt


def _create_event_from_data(data: dict[str, Any]) -> Event:
    """Create event from data based on type."""
    if "action" in data:
        return action_from_dict(data)
    if "observation" in data:
        return observation_from_dict(data)
    msg = f"Unknown event type: {data}"
    raise ValueError(msg)


def _process_underscore_keys(evt: Event, data: dict[str, Any]) -> None:
    """Process underscore keys and set attributes on event."""
    for key in UNDERSCORE_KEYS:
        if key in data:
            value = _process_key_value(key, data[key])
            setattr(evt, f"_{key}", value)


def _process_key_value(key: str, value: Any) -> Any:
    """Process a key-value pair based on the key type."""
    if key == "timestamp" and isinstance(value, datetime):
        return value.isoformat()
    if key == "source":
        return EventSource(value)
    if key == "tool_call_metadata":
        return _process_tool_call_metadata(value)
    if key == "llm_metrics":
        return _process_llm_metrics(value)
    return value


def _process_tool_call_metadata(value: Any) -> Any:
    """Process tool call metadata value."""
    if not value:
        return None
    try:
        return ToolCallMetadata(**value)
    except Exception:
        return None


def _process_llm_metrics(value: Any) -> Metrics:
    """Process LLM metrics value."""
    metrics = Metrics()
    if isinstance(value, dict):
        _populate_metrics_from_dict(metrics, value)
    return metrics


def _populate_metrics_from_dict(metrics: Metrics, value: dict) -> None:
    """Populate metrics object from dictionary."""
    metrics.accumulated_cost = value.get("accumulated_cost", 0.0)
    metrics.max_budget_per_task = value.get("max_budget_per_task")

    # Process costs
    for cost in value.get("costs", []):
        if not isinstance(cost, dict):
            continue
        cost_kwargs: dict[str, Any] = {}
        cost_kwargs["cost"] = cost.get("cost", 0.0)
        cost_kwargs["model"] = cost.get(
            "model", metrics.model_name if hasattr(metrics, "model_name") else ""
        )
        if "prompt_tokens" in cost:
            cost_kwargs["prompt_tokens"] = cost["prompt_tokens"]
        if "timestamp" in cost:
            cost_kwargs["timestamp"] = cost["timestamp"]
        metrics._costs.append(Cost(**cost_kwargs))

    # Process response latencies
    metrics.response_latencies = [
        ResponseLatency(**latency) for latency in value.get("response_latencies", [])
    ]

    # Process token usages
    metrics.token_usages = [
        TokenUsage(**usage) for usage in value.get("token_usages", [])
    ]

    # Process accumulated token usage
    if "accumulated_token_usage" in value:
        accumulated = value.get("accumulated_token_usage", {})
        if isinstance(accumulated, dict):
            metrics._accumulated_token_usage = TokenUsage(**accumulated)


def _convert_pydantic_to_dict(obj: BaseModel | dict) -> dict:
    return model_dump_with_options(obj) if isinstance(obj, BaseModel) else obj


def _extract_event_properties(event: Event) -> tuple[dict, bool]:
    """Extract properties from event, handling both dataclass and non-dataclass events."""
    is_dataclass = True
    try:
        props = asdict(event)
    except TypeError:
        is_dataclass = False
        props = {}
    return (props, is_dataclass)


def _process_top_level_keys(
    event: Event, props: dict[str, Any], is_dataclass: bool
) -> dict[str, Any]:
    """Process top-level keys for event serialization."""
    d: dict[str, Any] = {}

    for key in TOP_KEYS:
        # Extract value for key
        value = _extract_key_value(event, key)
        if value is not None:
            d[key] = value

        # Apply key-specific transformations
        _apply_key_transformations(d, key)

        # Remove from props
        props.pop(key, None)

    return d


def _extract_key_value(event: Event, key: str) -> Any:
    """Extract value for a key from event, checking both direct and private attributes."""
    # Check direct attribute first
    if hasattr(event, key) and getattr(event, key) is not None:
        return getattr(event, key)

    # Check private attribute
    private_key = f"_{key}"
    if hasattr(event, private_key) and getattr(event, private_key) is not None:
        return getattr(event, private_key)

    return None


def _apply_key_transformations(d: dict, key: str) -> None:
    """Apply key-specific transformations to the dictionary."""
    if key == "id":
        _transform_id_key(d)
    elif key == "sequence":
        _transform_sequence_key(d)
    elif key == "timestamp":
        _transform_timestamp_key(d)
    elif key == "source":
        _transform_source_key(d)
    elif key == "recall_type":
        _transform_recall_type_key(d)
    elif key == "tool_call_metadata":
        _transform_tool_call_metadata_key(d)
    elif key == "llm_metrics":
        _transform_llm_metrics_key(d)


def _transform_id_key(d: dict) -> None:
    """Transform ID key by removing invalid values."""
    if d.get("id") == -1:
        d.pop("id", None)


def _transform_sequence_key(d: dict) -> None:
    """Transform sequence key by removing invalid values."""
    if d.get("sequence") == -1:
        d.pop("sequence", None)


def _transform_timestamp_key(d: dict) -> None:
    """Transform timestamp key to ISO format."""
    if "timestamp" in d and isinstance(d["timestamp"], datetime):
        d["timestamp"] = d["timestamp"].isoformat()


def _transform_source_key(d: dict) -> None:
    """Transform source key to its value."""
    if "source" in d:
        d["source"] = d["source"].value


def _transform_recall_type_key(d: dict) -> None:
    """Transform recall_type key to its value."""
    if "recall_type" in d:
        d["recall_type"] = d["recall_type"].value


def _transform_tool_call_metadata_key(d: dict) -> None:
    """Transform tool_call_metadata key using model dump."""
    if "tool_call_metadata" in d:
        d["tool_call_metadata"] = model_dump_with_options(d["tool_call_metadata"])


def _transform_llm_metrics_key(d: dict) -> None:
    """Transform llm_metrics key by calling get method."""
    if "llm_metrics" in d:
        d["llm_metrics"] = d["llm_metrics"].get()


def event_to_dict(event: Event) -> dict[str, Any]:
    """Convert event to dictionary representation."""
    props, is_dataclass = _extract_event_properties(event)
    d = _process_top_level_keys(event, props, is_dataclass)

    # Clean up None values
    _clean_none_values(props)

    # Handle non-dataclass events
    if not is_dataclass:
        return _create_minimal_event_dict(event)

    # Handle action events
    if "action" in d:
        return _process_action_event(event, d, props)

    # Handle observation events
    if "observation" in d:
        return _process_observation_event(event, d, props)

    msg = f"Event must be either action or observation. has: {event}"
    raise ValueError(msg)


def _clean_none_values(props: dict[str, Any]) -> None:
    """Remove None values from props."""
    if "security_risk" in props and props["security_risk"] is None:
        props.pop("security_risk")
    if "task_completed" in props and props["task_completed"] is None:
        props.pop("task_completed")


def _create_minimal_event_dict(event: Event) -> dict[str, Any]:
    """Create minimal dictionary for non-dataclass events."""
    raise TypeError(
        f"Attempted to serialize unsupported non-dataclass event of type {type(event).__name__}."
    )


def _process_action_event(
    event: Event, d: dict[str, Any], props: dict[str, Any]
) -> dict[str, Any]:
    """Process action event dictionary."""
    # Handle security risk
    if "security_risk" in props:
        props["security_risk"] = props["security_risk"].value

    d["args"] = props

    # Add timeout if available
    if event.timeout is not None:
        d["timeout"] = event.timeout

    return d


def _process_observation_event(
    event: Event, d: dict[str, Any], props: dict[str, Any]
) -> dict[str, Any]:
    """Process observation event dictionary."""
    # Add content
    d["content"] = props.pop("content", "")

    # Remove sequence from persisted observation payload
    d.pop("sequence", None)

    # Convert extras safely
    d["extras"] = _convert_extras_safely(props)

    # Add success if available
    if hasattr(event, "success"):
        d["success"] = event.success

    return d


def _convert_extras_safely(props: dict[str, Any]) -> dict[str, Any]:
    """Convert extras dictionary safely."""

    def _safe_convert(v):
        if v is None or isinstance(v, (str, int, float, bool, dict, list)):
            return v
        if isinstance(v, Enum):
            return v.value
        return _convert_pydantic_to_dict(v) if isinstance(v, BaseModel) else None

    return {k: _safe_convert(v) for k, v in props.items()}


def event_to_trajectory(
    event: Event, include_screenshots: bool = False
) -> dict[str, Any] | None:
    """Convert event to trajectory format for storage/analysis.

    Serializes event and removes sensitive fields based on screenshot inclusion preference.

    Args:
        event: Event to convert
        include_screenshots: Whether to include screenshot data

    Returns:
        Dictionary representation suitable for trajectory storage, or None if invalid

    """
    d = event_to_dict(event)
    if d.get("action") == "null" or d.get("observation") == "null":
        return None
    if "extras" in d:
        remove_fields(
            d["extras"],
            DELETE_FROM_TRAJECTORY_EXTRAS
            if include_screenshots
            else DELETE_FROM_TRAJECTORY_EXTRAS_AND_SCREENSHOTS,
        )
        # set_of_marks can be very large; exclude regardless of screenshot preference
        d["extras"].pop("set_of_marks", None)
    return d


def truncate_content(content: str, max_chars: int | None = None) -> str:
    """Truncate the middle of the observation content if it is too long."""
    if max_chars is None or len(content) <= max_chars or max_chars < 0:
        return content
    half = max_chars // 2
    return (
        content[:half]
        + "\n[... Observation truncated due to length ...]\n"
        + content[-half:]
    )
