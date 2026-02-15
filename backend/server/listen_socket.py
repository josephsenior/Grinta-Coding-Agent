"""Socket.IO event handlers for real-time conversation streaming.

Responsibilities:
- Socket.IO lifecycle events (``connect``, ``disconnect``)
- Event routing (``forge_user_action``, ``forge_action``)

Authentication / validation and event-stream replay logic have been
extracted into :mod:`backend.server.socket_auth` and
:mod:`backend.server.socket_replay` respectively.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from socketio.exceptions import (
    ConnectionRefusedError as SocketIOConnectionRefusedError,  # type: ignore[import-untyped]
)

from backend.core.logger import FORGE_logger as logger
from backend.events.event_store import EventStore
from backend.server.middleware.socketio_connection_manager import get_connection_manager
from backend.server.services.conversation_service import (
    setup_init_conversation_settings,
)
from backend.server.shared import (
    get_conversation_manager,
    sio,
)
from backend.server.socket_auth import (
    parse_latest_event_id,
    parse_providers_set,
    validate_connection_params,
)
from backend.server.socket_replay import replay_event_stream
from backend.storage.conversation.conversation_validator import (
    create_conversation_validator,
)


def _get_conversation_manager_instance():
    """Get conversation manager instance, initializing if needed."""
    try:
        return get_conversation_manager()
    except Exception:
        return None


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
        query_params = parse_qs(environ.get("QUERY_STRING", ""))
        auth = args[0] if args else {}

        # Parse parameters
        latest_event_id = parse_latest_event_id(query_params)
        conversation_id = query_params.get("conversation_id", [None])[0]
        providers_set = parse_providers_set(query_params)

        logger.info(
            "Socket request for conversation %s with connection_id %s",
            conversation_id,
            connection_id,
        )

        # Validate connection
        validate_connection_params(conversation_id, query_params, auth)

        # Authenticate user
        cookies_str = environ.get("HTTP_COOKIE", "")
        authorization_header = environ.get("HTTP_AUTHORIZATION")
        conversation_validator = create_conversation_validator()
        user_id = await conversation_validator.validate(
            conversation_id, cookies_str, authorization_header
        )
        logger.info(
            "User %s is allowed to connect to conversation %s", user_id, conversation_id
        )

        # Register connection with connection manager
        conn_manager = get_connection_manager()
        try:
            conn_manager.register_connection(
                sid=connection_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            logger.info("Connection registered: %s", connection_id)
        except ValueError as e:
            logger.warning("Connection limit exceeded: %s", e)
            raise SocketIOConnectionRefusedError(str(e)) from e

        # Deliver any queued messages
        try:
            delivered = await conn_manager.deliver_queued_messages(connection_id, sio)
            if delivered > 0:
                logger.info(
                    "Delivered %s queued messages to %s", delivered, connection_id
                )
        except Exception as e:
            logger.error("Error delivering queued messages: %s", e)

        # Create event store
        manager = _get_conversation_manager_instance()
        if manager is None:
            msg = "Conversation manager is not initialized"
            raise SocketIOConnectionRefusedError(msg)
        try:
            event_store = EventStore(conversation_id, manager.file_store, user_id)
        except FileNotFoundError as e:
            logger.error(
                "Failed to create EventStore for conversation %s: %s",
                conversation_id,
                e,
            )
            msg = f"Failed to access conversation events: {e}"
            raise SocketIOConnectionRefusedError(msg) from e

        # Replay events
        await replay_event_stream(
            event_store, latest_event_id, connection_id, conversation_id
        )

        # Join conversation
        try:
            conversation_init_data = await setup_init_conversation_settings(
                user_id, conversation_id, providers_set
            )
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
            conversation_id,
            connection_id,
            conversation_init_data,
            user_id,
        )
        if agent_loop_info is None:
            msg = "Failed to join conversation"
            raise SocketIOConnectionRefusedError(msg)

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


# Removed duplicate connect handler - using the one above that properly creates sessions


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
    return None


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
