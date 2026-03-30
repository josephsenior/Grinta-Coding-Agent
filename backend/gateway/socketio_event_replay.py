"""Event-stream replay logic for Socket.IO reconnections.

Extracted from ``socketio_event_handlers.py`` so the replay/state-recovery
concern is isolated from connection lifecycle and event routing.
"""

from __future__ import annotations

from backend.core.logger import app_logger as logger
from backend.ledger.action import NullAction
from backend.ledger.action.agent import RecallAction
from backend.ledger.async_event_store_wrapper import AsyncEventStoreWrapper
from backend.ledger.event_store import EventStore
from backend.ledger.observation import NullObservation
from backend.ledger.observation.agent import AgentStateChangedObservation
from backend.ledger.serialization import event_to_dict
from backend.gateway.middleware.socketio_connection_manager import get_connection_manager
from backend.gateway.app_accessors import get_conversation_manager, sio


async def replay_events(
    async_store: AsyncEventStoreWrapper,
    connection_id: str,
) -> AgentStateChangedObservation | None:
    """Iterate through an event store wrapper and emit each event to the client.

    Returns the last ``AgentStateChangedObservation`` found, or *None*.
    """
    agent_state_changed: AgentStateChangedObservation | None = None
    event_count = 0

    async for event in async_store:
        event_count += 1
        logger.debug("app_event: %s", event.__class__.__name__)

        if isinstance(event, NullAction | NullObservation | RecallAction):
            continue

        if isinstance(event, AgentStateChangedObservation):
            logger.info("Found AgentStateChangedObservation: %s", event.agent_state)
            agent_state_changed = event
        else:
            await sio.emit("app_event", event_to_dict(event), to=connection_id)

    logger.info("Replayed %s events", event_count)
    return agent_state_changed


async def send_agent_state(
    agent_state_changed: AgentStateChangedObservation | None,
    conversation_id: str,
    connection_id: str,
) -> bool:
    """Emit the agent state to *connection_id*.

    If *agent_state_changed* is ``None``, falls back to querying the
    conversation manager for the current agent-loop state.

    Returns *True* if a state event was sent.
    """
    conn_manager = get_connection_manager()

    if agent_state_changed is not None:
        logger.info(
            "Found agent state in event stream: %s",
            agent_state_changed.agent_state,
        )
        conn_manager.update_activity(connection_id)
        await sio.emit(
            "app_event", event_to_dict(agent_state_changed), to=connection_id
        )
        return True

    try:
        manager = get_conversation_manager()
    except Exception:
        manager = None
    if manager is None:
        logger.error("Conversation manager is not initialized")
        return False

    try:
        agent_loop_info_list = await manager.get_agent_loop_info(
            filter_to_sids={conversation_id}
        )
        if agent_loop_info_list:
            info = agent_loop_info_list[0]
            if info.agent_state:
                current_state = AgentStateChangedObservation(
                    "", info.agent_state, "Connection established"
                )
                conn_manager.update_activity(connection_id)
                await sio.emit(
                    "app_event", event_to_dict(current_state), to=connection_id
                )
                return True
            logger.warning(
                "No agent state found in agent_loop_info for conversation %s",
                conversation_id,
            )
    except Exception as e:
        logger.error("Error getting agent state from conversation manager: %s", e)

    return False


async def replay_event_stream(
    event_store: EventStore,
    latest_event_id: int,
    connection_id: str,
    conversation_id: str,
) -> None:
    """Full replay sequence: emit stored events, then send current agent state.

    If no agent state is discovered during replay, a default
    ``awaiting_user_input`` state is emitted so the client never goes
    without a state.
    """
    logger.info(
        "Replaying event stream for conversation %s (connection %s, from id %s)",
        conversation_id,
        connection_id,
        latest_event_id,
    )

    async_store = AsyncEventStoreWrapper(event_store, latest_event_id + 1)
    agent_state_changed = await replay_events(async_store, connection_id)

    state_sent = await send_agent_state(
        agent_state_changed, conversation_id, connection_id
    )

    if not state_sent:
        logger.info(
            "No agent state found — sending default AWAITING_USER_INPUT to %s",
            connection_id,
        )
        try:
            default_state = AgentStateChangedObservation(
                "", "awaiting_user_input", "Default state on connection"
            )
            conn_manager = get_connection_manager()
            conn_manager.update_activity(connection_id)
            await sio.emit(
                "app_event", event_to_dict(default_state), to=connection_id
            )
        except Exception as e:
            logger.error(
                "Failed to send default agent state to %s: %s",
                connection_id,
                e,
            )

    logger.info("Finished replaying event stream for conversation %s", conversation_id)
