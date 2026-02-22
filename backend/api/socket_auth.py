"""Socket.IO authentication and connection-parameter validation.

Extracted from ``listen_socket.py`` to keep each module focused on a
single concern.
"""

from __future__ import annotations

from typing import Any

from socketio.exceptions import (
    ConnectionRefusedError as SocketIOConnectionRefusedError,  # type: ignore[import-untyped]
)

from backend.core.logger import forge_logger as logger
from backend.core.provider_types import ProviderType


def parse_latest_event_id(query_params: dict[str, Any]) -> int:
    """Parse ``latest_event_id`` from query parameters.

    Handles ``"undefined"`` string from client, non-integer values,
    and missing keys.
    """
    latest_event_id_str = query_params.get("latest_event_id", [-1])[0]
    if latest_event_id_str == "undefined":
        return -1
    try:
        return int(latest_event_id_str)
    except ValueError:
        logger.debug(
            "Invalid latest_event_id value: %s, defaulting to -1",
            latest_event_id_str,
        )
        return -1


def parse_providers_set(query_params: dict[str, Any]) -> list[ProviderType]:
    """Parse ``providers_set`` from query parameters."""
    raw_list = query_params.get("providers_set", [])
    providers_list: list[str] = []
    for item in raw_list:
        providers_list.extend(item.split(",") if isinstance(item, str) else [])
    providers_list = [p for p in providers_list if p]
    return [ProviderType(p) for p in providers_list]


def validate_connection_params(
    conversation_id: str | None,
    query_params: dict[str, Any],
    auth: dict[str, Any] | None = None,
) -> None:
    """Validate mandatory connection params.

    Raises:
        SocketIOConnectionRefusedError: on invalid / missing params.
    """
    if not conversation_id:
        logger.error("No conversation_id in query params")
        raise SocketIOConnectionRefusedError("No conversation_id in query params")



