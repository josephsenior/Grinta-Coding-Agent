"""Socket.IO event handlers for real-time conversation streaming.

Responsibilities:
- Socket.IO lifecycle events (``connect``, ``disconnect``)
- Event routing (``forge_user_action``, ``forge_action``)

Connection-parameter validation and event-stream replay logic have been
extracted into :mod:`backend.api.socket_params` and
:mod:`backend.api.socket_replay` respectively.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from socketio.exceptions import (
    ConnectionRefusedError as SocketIOConnectionRefusedError,  # type: ignore[import-untyped]
)

from backend.core.logger import forge_logger as logger
from backend.core.provider_types import ProviderType
from backend.events.event_store import EventStore
from backend.api.middleware.socketio_connection_manager import get_connection_manager
from backend.api.services.conversation_service import (
    setup_init_conversation_settings,
)
from backend.api.shared import (
    get_conversation_manager,
    sio,
)
from backend.api.socket_params import (
    parse_latest_event_id,
    parse_providers_set,
    validate_connection_params,
)
from backend.api.socket_replay import replay_event_stream
from backend.api.types import MissingSettingsError
from backend.storage.conversation.conversation_validator import (
    create_conversation_validator,
)


def _get_conversation_manager_instance():
    """Get conversation manager instance, initializing if needed."""
    try:
        return get_conversation_manager()
    except Exception:
        return None


async def _register_and_deliver(
    connection_id: str, user_id: str | None, conversation_id: str | None
) -> None:
    """Register connection and deliver queued messages."""
    conn_manager = get_connection_manager()
    try:
        conn_manager.register_connection(
            sid=connection_id, user_id=user_id, conversation_id=conversation_id
        )
        logger.info("Connection registered: %s", connection_id)
    except ValueError as e:
        logger.warning("Connection limit exceeded: %s", e)
        raise SocketIOConnectionRefusedError(str(e)) from e
    try:
        delivered = await conn_manager.deliver_queued_messages(connection_id, sio)
        if delivered > 0:
            logger.info("Delivered %s queued messages to %s", delivered, connection_id)
    except Exception as e:
        logger.error("Error delivering queued messages: %s", e)


async def _create_event_store_and_replay(
    connection_id: str,
    conversation_id: str | None,
    user_id: str | None,
    latest_event_id: int,
) -> None:
    """Create EventStore and replay events. Raises SocketIOConnectionRefusedError on failure."""
    manager = _get_conversation_manager_instance()
    if manager is None:
        raise SocketIOConnectionRefusedError("Conversation manager is not initialized")
    assert conversation_id is not None
    try:
        event_store = EventStore(conversation_id, manager.file_store, user_id)
    except FileNotFoundError as e:
        logger.error(
            "Failed to create EventStore for conversation %s: %s", conversation_id, e
        )
        raise SocketIOConnectionRefusedError(
            f"Failed to access conversation events: {e}"
        ) from e
    await replay_event_stream(
        event_store, latest_event_id, connection_id, conversation_id
    )


async def _setup_and_join(
    connection_id: str,
    conversation_id: str | None,
    user_id: str | None,
    providers_set: list[ProviderType] | None,
) -> bool:
    """Setup conversation and join. Returns False if MissingSettingsError (allow connect); raises on other failure."""
    manager = _get_conversation_manager_instance()
    if manager is None:
        raise SocketIOConnectionRefusedError("Conversation manager is not initialized")
    assert conversation_id is not None
    try:
        conversation_init_data = await setup_init_conversation_settings(
            user_id, conversation_id, providers_set
        )
    except MissingSettingsError as e:
        logger.warning(
            "No settings for conversation %s (user_id: %s) — "
            "socket stays connected but agent will not start: %s",
            conversation_id,
            user_id,
            e,
        )
        return False
    except Exception as e:
        logger.error(
            "Failed to setup conversation settings for conversation %s (user_id: %s): %s",
            conversation_id,
            user_id,
            e,
            exc_info=True,
        )
        raise SocketIOConnectionRefusedError(
            f"Failed to setup conversation settings: {e}"
        ) from e
    agent_loop_info = await manager.join_conversation(
        conversation_id, connection_id, conversation_init_data, user_id
    )
    if agent_loop_info is None:
        raise SocketIOConnectionRefusedError("Failed to join conversation")
    return True


@sio.event
async def connect(connection_id: str, environ: dict, *args) -> None:
    """Handle Socket.IO client connection.

    Authenticates user, validates conversation access, replays events, and joins conversation.

    Args:
        connection_id: Unique connection identifier
        environ: WSGI environment dictionary with request data
        *args: Additional arguments provided by Socket.IO for compatibility

    Raises:
        SocketIOConnectionRefusedError: If authentication or validation fails

    """
    try:
        logger.info(
            "*** DEBUG: connect handler called with connection_id: %s", connection_id
        )
        logger.info("sio:connect: %s", connection_id)
        # Parse parameters
        query_string = environ.get("QUERY_STRING", "")
        if not query_string and "query_string" in environ:
            # Handle ASGI scope where query_string is bytes
            qs_bytes = environ["query_string"]
            query_string = (
                qs_bytes.decode() if isinstance(qs_bytes, bytes) else str(qs_bytes)
            )

        query_params = parse_qs(query_string)
        latest_event_id = parse_latest_event_id(query_params)
        conversation_id = query_params.get("conversation_id", [None])[0]
        providers_set = parse_providers_set(query_params)

        logger.info(
            "Socket request for conversation %s with connection_id %s",
            conversation_id,
            connection_id,
        )

        # Validate connection
        validate_connection_params(conversation_id)

        # Authenticate user
        cookies_str = environ.get("HTTP_COOKIE", "")
        authorization_header = environ.get("HTTP_AUTHORIZATION")
        conversation_validator = create_conversation_validator()
        # At this point, conversation_id is guaranteed to be a string due to validate_connection_params
        user_id = await conversation_validator.validate(
            conversation_id, cookies_str, authorization_header  # type: ignore[arg-type]
        )
        logger.info(
            "User %s is allowed to connect to conversation %s", user_id, conversation_id
        )

        await _register_and_deliver(connection_id, user_id, conversation_id)
        await _create_event_store_and_replay(
            connection_id, conversation_id, user_id, latest_event_id
        )
        joined = await _setup_and_join(
            connection_id, conversation_id, user_id, providers_set
        )
        if not joined:
            return
        logger.info(
            "Successfully joined conversation %s with connection_id %s",
            conversation_id,
            connection_id,
        )
    except SocketIOConnectionRefusedError:
        from backend.utils.async_utils import create_tracked_task

        create_tracked_task(
            sio.disconnect(connection_id),
            name="socket-disconnect-on-error",
        )
        raise
    except Exception:
        import traceback

        traceback.print_exc()
        raise


@sio.event
async def forge_user_action(connection_id: str, data: dict[str, Any]) -> None:
    """Handle user action from Socket.IO client.

    Args:
        connection_id: Client connection identifier
        data: Action data dictionary

    """
    # Debug logging
    logger.info(
        "forge_user_action received: action=%s, data=%s", data.get("action"), data
    )

    manager = _get_conversation_manager_instance()
    if manager is not None:
        await manager.send_to_event_stream(connection_id, data)


@sio.event
async def forge_action(connection_id: str, data: dict[str, Any]) -> None:
    """Handle agent action from Socket.IO client.

    Args:
        connection_id: Client connection identifier
        data: Action data dictionary

    """
    manager = _get_conversation_manager_instance()
    if manager is not None:
        await manager.send_to_event_stream(connection_id, data)


@sio.event
async def disconnect(connection_id: str) -> None:
    """Handle Socket.IO client disconnection.

    Args:
        connection_id: Unique connection identifier

    """
    logger.info("sio:disconnect: %s", connection_id)

    # Unregister connection from connection manager
    conn_manager = get_connection_manager()
    conn_manager.unregister_connection(connection_id)
    logger.info("Connection unregistered: %s", connection_id)

    # Disconnect from session
    manager = _get_conversation_manager_instance()
    if manager is not None:
        await manager.disconnect_from_session(connection_id)


@sio.event
async def test_event(connection_id: str, data: dict[str, Any]) -> None:
    """Handle test event (no-op).

    Args:
        connection_id: Client connection identifier
        data: Event data

    """
    return


# ------------------------------------------------------------------
# Debug introspection — show which handlers Socket.IO has registered
# ------------------------------------------------------------------


def show_events() -> None:
    """Display all registered Socket.IO events for debugging purposes."""
    logger.info("Socket.IO event handlers registered")
    if hasattr(sio, "handlers") and "/" in sio.handlers:
        for event_name in sio.handlers["/"].keys():
            logger.info("  handler: %s", event_name)
    else:
        logger.info("  (none)")


show_events()
