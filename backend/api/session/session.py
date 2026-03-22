"""Session orchestration tying together agent runtime, websockets, and events."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

from backend.controller.agent import Agent

if TYPE_CHECKING:
    pass
from backend.core.config.mcp_config import ForgeMCPConfig
from backend.core.errors import AgentNotRegisteredError, PlaybookValidationError
from backend.core.logger import ForgeLoggerAdapter
from backend.core.schemas import AgentState
from backend.events.action import MessageAction, NullAction
from backend.events.event import Event, EventSource
from backend.events.observation import (
    AgentStateChangedObservation,
    CmdOutputObservation,
    NullObservation,
)
from backend.events.observation.agent import RecallObservation
from backend.events.observation.error import ErrorObservation
from backend.events.serialization import event_from_dict, event_to_dict
from backend.events.stream import EventStreamSubscriber
from backend.core.provider_types import CustomSecretsType, ProviderTokenType
from backend.core.enums import RuntimeStatus
from backend.api.constants import ROOM_KEY
from backend.api.session.agent_session import AgentSession
from backend.api.session.conversation_init_data import ConversationInitData

if TYPE_CHECKING:
    from logging import LoggerAdapter

    import socketio  # type: ignore[import-untyped]

    from backend.core.config import ForgeConfig
    from backend.llm.llm_registry import LLMRegistry
    from backend.api.services.conversation_stats import ConversationStats
    from backend.storage.data_models.settings import Settings
    from backend.storage.files import FileStore


class Session:
    """Active conversation session encapsulating runtime, controller, and event stream."""

    sid: str
    sio: socketio.AsyncServer | None
    last_active_ts: int = 0
    is_alive: bool = True
    agent_session: AgentSession
    loop: asyncio.AbstractEventLoop
    config: ForgeConfig
    llm_registry: LLMRegistry
    file_store: FileStore
    user_id: str | None
    logger: LoggerAdapter

    def __init__(
        self,
        sid: str,
        config: ForgeConfig,
        llm_registry: LLMRegistry,
        conversation_stats: ConversationStats,
        file_store: FileStore,
        sio: socketio.AsyncServer | None,
        user_id: str | None = None,
    ) -> None:
        """Wire up agent session state, queue workers, and analytics tracking."""
        self.sid = sid
        self.sio = sio
        self.last_active_ts = int(time.time())
        self.file_store = file_store
        self.logger = ForgeLoggerAdapter(extra={"session_id": sid})
        self.llm_registry = llm_registry
        self.conversation_stats = conversation_stats
        self.agent_session = AgentSession(
            sid,
            file_store,
            llm_registry=self.llm_registry,
            conversation_stats=conversation_stats,
            status_callback=self.queue_status_message,
            user_id=user_id,
        )
        self.agent_session.event_stream.subscribe(  # type: ignore[attr-defined]
            EventStreamSubscriber.SERVER, self.on_event, self.sid
        )
        self.config = config
        self.loop = asyncio.get_event_loop()
        self.user_id = user_id
        self._publish_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._monitor_publish_queue_task: asyncio.Task = self.loop.create_task(
            self._monitor_publish_queue()
        )
        self._wait_websocket_initial_complete: bool = True
        self._closed: bool = False

    async def close(self) -> None:
        """Close session and notify clients of stopped state.

        Idempotent — calling more than once is a no-op.
        """
        if self._closed:
            return
        self._closed = True

        if self.sio:
            await self.sio.emit(
                "forge_event",
                event_to_dict(
                    AgentStateChangedObservation("", AgentState.STOPPED.value)
                ),
                to=ROOM_KEY.format(sid=self.sid),
            )
        self.is_alive = False
        await self.agent_session.close()
        self._monitor_publish_queue_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._monitor_publish_queue_task

    # ------------------------------------------------------------------ #
    # Settings consolidation                                              #
    # ------------------------------------------------------------------ #
    def _apply_settings(self, settings: Settings) -> None:
        """Apply all user settings to the session config in one place.

        Mutates ``self.config`` so downstream code picks up user overrides.
        """
        cfg = self.config

        # MCP
        self.logger.debug(
            "MCP configuration before setup - self.config.mcp_config: %s", cfg.mcp
        )
        mcp_config = getattr(settings, "mcp_config", None)
        if mcp_config is not None:
            cfg.mcp = cfg.mcp.merge(mcp_config)
            self.logger.debug("Merged custom MCP Config: %s", mcp_config)

        forge_mcp_server, forge_mcp_stdio_servers = (
            ForgeMCPConfig.create_default_mcp_server_config(
                cfg.mcp_host,
                cfg,
                self.user_id,
            )
        )
        if forge_mcp_server:
            cfg.mcp.servers.append(forge_mcp_server)

        if forge_mcp_stdio_servers:
            cfg.mcp.servers.extend(forge_mcp_stdio_servers)

        self.logger.debug(
            "MCP configuration after setup - self.config.mcp: %s", cfg.mcp
        )

    def _apply_condenser(self, settings: Settings, agent_config, llm_config) -> None:
        """Configure agent condenser — always uses automatic selection."""
        from backend.core.config.condenser_config import AutoCondenserConfig

        agent_config.condenser_config = AutoCondenserConfig(llm_config=llm_config)
        self.logger.info("Condenser: auto-selection enabled (adapts to session length and patterns)")

    def _extract_conversation_data(
        self,
        settings: Settings,
    ) -> tuple[
        ProviderTokenType | None,
        str | None,
        str | None,
        CustomSecretsType | None,
        str | None,
    ]:
        """Extract conversation-specific data from settings."""
        vcs_provider_tokens: ProviderTokenType | None = None
        selected_repository = None
        selected_branch = None
        custom_secrets: CustomSecretsType | None = None
        conversation_instructions = None

        if isinstance(settings, ConversationInitData):
            vcs_provider_tokens = settings.vcs_provider_tokens
            selected_repository = settings.selected_repository
            selected_branch = settings.selected_branch
            custom_secrets = settings.custom_secrets
            conversation_instructions = settings.conversation_instructions

        return (
            vcs_provider_tokens,
            selected_repository,
            selected_branch,
            custom_secrets,
            conversation_instructions,
        )

    async def _start_agent_session(
        self,
        agent,
        max_iterations: int,
        max_budget_per_task: float | None,
        vcs_provider_tokens: ProviderTokenType | None,
        custom_secrets: CustomSecretsType | None,
        selected_repository: str | None,
        selected_branch: str | None,
        initial_message: MessageAction | None,
        conversation_instructions: str | None,
        replay_json: str | None,
        settings: Settings | None = None,
    ) -> None:
        """Start the agent session with error handling."""
        try:
            await self.agent_session.start(
                runtime_name=self.config.runtime,
                config=self.config,
                agent=agent,
                max_iterations=max_iterations,
                max_budget_per_task=max_budget_per_task,
                agent_to_llm_config=self.config.get_agent_to_llm_config_map(),
                agent_configs=self.config.get_agent_configs(),
                vcs_provider_tokens=vcs_provider_tokens,
                custom_secrets=custom_secrets,
                selected_repository=selected_repository,
                selected_branch=selected_branch,
                initial_message=initial_message,
                conversation_instructions=conversation_instructions,
                replay_json=replay_json,
                user_settings=settings,
            )
        except PlaybookValidationError as e:
            self.logger.exception("Error creating agent_session: %s", e)
            await self.send_error(f"Failed to create agent session: {e!s}")
            return
        except ValueError as e:
            self.logger.exception("Error creating agent_session: %s", e)
            error_message = str(e)
            if "playbook" in error_message.lower():
                await self.send_error(
                    f"Failed to create agent session: {error_message}"
                )
            else:
                await self.send_error("Failed to create agent session: ValueError")
            return
        except Exception as e:
            self.logger.exception("Error creating agent_session: %s", e)
            detail = str(e).strip()
            if detail:
                await self.send_error(
                    f"Failed to create agent session: {e.__class__.__name__}: {detail}"
                )
            else:
                await self.send_error(
                    f"Failed to create agent session: {e.__class__.__name__}"
                )
            return

    async def initialize_agent(
        self,
        settings: Settings,
        initial_message: MessageAction | None,
        replay_json: str | None,
    ) -> None:
        """Initialize the agent with the provided settings."""
        # Set loading state
        self.agent_session.event_stream.add_event(  # type: ignore[attr-defined]
            AgentStateChangedObservation("", AgentState.LOADING),
            EventSource.ENVIRONMENT,
        )

        # Get agent class
        agent_cls = getattr(settings, "agent", None) or self.config.default_agent

        # Apply all settings in one shot
        self._apply_settings(settings)

        # Derive agent config and budget limits
        max_iterations = getattr(settings, "max_iterations", None) or self.config.max_iterations
        settings_budget = getattr(settings, "max_budget_per_task", None)
        max_budget_per_task = (
            settings_budget
            if settings_budget is not None
            else self.config.max_budget_per_task
        )
        agent_config = self.config.get_agent_config(agent_cls)
        settings_playbooks = getattr(settings, "disabled_playbooks", None)
        if settings_playbooks is not None:
            agent_config.disabled_playbooks = list(settings_playbooks)
        agent_name = agent_cls if agent_cls is not None else "agent"
        llm_config = self.config.get_llm_config_from_agent(agent_name)

        # Configure condenser if enabled
        self._apply_condenser(settings, agent_config, llm_config)

        # Create agent
        try:
            agent_type = Agent.get_cls(agent_cls)
        except AgentNotRegisteredError:
            fallback_agent = self.config.default_agent
            self.logger.warning(
                "Agent '%s' is not registered; falling back to default '%s'",
                agent_cls,
                fallback_agent,
            )
            agent_cls = fallback_agent
            agent_config = self.config.get_agent_config(agent_cls)
            disabled_playbooks = getattr(settings, "disabled_playbooks", None)
            if disabled_playbooks is not None:
                agent_config.disabled_playbooks = list(disabled_playbooks)
            agent_name = agent_cls if agent_cls is not None else "agent"
            llm_config = self.config.get_llm_config_from_agent(agent_name)
            self._apply_condenser(settings, agent_config, llm_config)
            agent_type = Agent.get_cls(agent_cls)

        agent = agent_type(agent_config, self.llm_registry)
        self.llm_registry.retry_listner = self._notify_on_llm_retry

        # Extract conversation data
        (
            vcs_provider_tokens,
            selected_repository,
            selected_branch,
            custom_secrets,
            conversation_instructions,
        ) = self._extract_conversation_data(settings)

        # Start agent session
        await self._start_agent_session(
            agent,
            max_iterations,
            max_budget_per_task,
            vcs_provider_tokens,
            custom_secrets,
            selected_repository,
            selected_branch,
            initial_message,
            conversation_instructions,
            replay_json,
            settings=settings,
        )

    def _notify_on_llm_retry(self, retries: int, max_retries: int) -> None:
        self.queue_status_message(
            "info",
            RuntimeStatus.LLM_RETRY,
            f"Retrying LLM request, {retries} / {max_retries}",
        )

    def on_event(self, event: Event) -> None:
        """Synchronous event callback that delegates to async handler.

        Called from EventStream's delivery thread pool, NOT the main
        event loop thread.  We must schedule work on ``self.loop`` so
        that ``_publish_queue`` operations happen on the same loop as
        ``_monitor_publish_queue``, avoiding cross-thread notification
        issues with ``asyncio.Queue``.

        Args:
            event: Event to process

        """
        asyncio.run_coroutine_threadsafe(self._on_event(event), self.loop)

    async def _on_event(self, event: Event) -> None:
        """Callback function for events that mainly come from the agent.

        Event is the base class for any agent action and observation.

        Args:
            event: The agent event (Observation or Action).

        """
        if isinstance(event, NullAction):
            return
        if isinstance(event, NullObservation):
            return
        if event.source in (EventSource.AGENT, EventSource.USER):
            await self.send(event_to_dict(event))
        elif event.source == EventSource.ENVIRONMENT and isinstance(
            event,
            CmdOutputObservation | AgentStateChangedObservation | RecallObservation,
        ):
            event_dict = event_to_dict(event)
            # Preserve original source for frontend provenance tracking
            event_dict["original_source"] = EventSource.ENVIRONMENT
            event_dict["source"] = EventSource.AGENT
            # Debug logging for agent state changes
            if isinstance(event, AgentStateChangedObservation):
                self.logger.info(
                    "DEBUG: AgentStateChangedObservation received - "
                    "state: %s, reason: %s, sending to WebSocket",
                    event.agent_state,
                    event.reason,
                    extra={"session_id": self.sid},
                )
            await self.send(event_dict)
            if (
                isinstance(event, AgentStateChangedObservation)
                and event.agent_state == AgentState.ERROR
            ):
                self.logger.error(
                    f"Agent status error: {event.reason}",
                    extra={"signal": "agent_status_error"},
                )
        elif isinstance(event, ErrorObservation):
            event_dict = event_to_dict(event)
            event_dict["original_source"] = event.source
            event_dict["source"] = EventSource.AGENT
            await self.send(event_dict)

    async def dispatch(self, data: dict) -> None:
        """Dispatch incoming event data to appropriate handlers."""
        # Wait for agent initialization to finish the EXECUTION phase before
        # delivering user events.  This prevents a user message from racing
        # against the initial ChangeAgentStateAction emitted during startup.
        try:
            await asyncio.wait_for(self.agent_session._init_ready.wait(), timeout=120)
        except asyncio.TimeoutError:
            self.logger.warning(
                "Timed out waiting for agent initialization; delivering event anyway",
                extra={"signal": "dispatch_init_timeout"},
            )

        # Log dispatch start
        self._log_dispatch_start(data)

        # Parse event from data
        event = event_from_dict(data.copy())
        self._log_parsed_event(event)

        # Handle image validation for message actions
        if await self._handle_image_validation(event):
            return

        # Add event to stream
        self.agent_session.event_stream.add_event(event, EventSource.USER)  # type: ignore[attr-defined]

    def _log_dispatch_start(self, data: dict) -> None:
        """Log the start of dispatch operation."""
        try:
            self.logger.info(
                "Dispatch called with data keys: %s",
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                extra={"signal": "dispatch_called"},
            )
        except Exception:
            pass  # logging failure must not block dispatch

    def _log_parsed_event(self, event) -> None:
        """Log the parsed event information."""
        try:
            self.logger.info(
                "Parsed event: %s",
                type(event).__name__,
                extra={"signal": "dispatch_parsed_event"},
            )
        except Exception:
            pass  # logging failure must not block dispatch

    async def _handle_image_validation(self, event) -> bool:
        """Handle image validation for message actions. Returns True if validation failed."""
        if not isinstance(event, MessageAction) or not event.image_urls:
            return False

        controller = self.agent_session.controller
        if not controller:
            return False

        if controller.agent.llm.config.disable_vision:
            await self.send_error(
                "Images are turned off for this model. Enable vision in Settings or remove the image."
            )
            return True

        from backend.llm.catalog_loader import lookup

        model_name = getattr(controller.agent.llm.config, "model", None) or ""
        entry = lookup(str(model_name)) if model_name else None
        if not entry or not entry.supports_vision:
            await self.send_error(
                "This model doesn't accept images. Choose a vision-capable model in Settings or remove the image."
            )
            return True

        return False

    async def send(self, data: dict[str, object]) -> None:
        """Queue data for publishing to WebSocket clients.

        If the queue is full, the oldest pending event is dropped
        to prevent unbounded memory growth during backpressure.

        Args:
            data: Data dictionary to send

        """
        try:
            self._publish_queue.put_nowait(data)
        except asyncio.QueueFull:
            # Drop the oldest queued item to make room
            try:
                self._publish_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._publish_queue.put_nowait(data)

    async def _monitor_publish_queue(self) -> None:
        try:
            while True:
                try:
                    data: dict = await self._publish_queue.get()
                    await self._send(data)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.logger.error("Error in publish queue handler: %s", getattr(e, 'message', str(e)))
        except asyncio.CancelledError:
            return

    async def _send(self, data: dict[str, object]) -> bool:
        """Send data to websocket with retry logic.

        Args:
            data: Data dictionary to send

        Returns:
            True if sent successfully, False otherwise

        """
        try:
            if not self.is_alive:
                return False

            if self.sio:
                await self._wait_for_client_connection()

                if self._should_drop_event(data):
                    return True

                await self._emit_to_client(data)

            # Removed artificial delay for instant streaming
            # await asyncio.sleep(0.001)
            self.last_active_ts = int(time.time())
            return True

        except Exception as e:
            self.logger.exception("Error sending data to websocket: %s", str(e))
            self.is_alive = False
            return False

    async def _wait_for_client_connection(self) -> None:
        """Wait for client to connect to room.

        Waits up to 2 seconds for a client to join the room.
        """
        _start_time = time.time()
        _waiting_times = 1

        sio = self.sio
        if sio is None:
            return
        manager = getattr(sio, "manager", None)
        if manager is None:
            return

        while (
            self._wait_websocket_initial_complete
            and time.time() - _start_time < 2
            and not bool(manager.rooms.get("/", {}).get(ROOM_KEY.format(sid=self.sid)))  # type: ignore[arg-type]
        ):
            self.logger.warning(
                f"There is no listening client in the current room, waiting for the {
                    _waiting_times
                }th attempt: {self.sid}",
            )
            _waiting_times += 1
            await asyncio.sleep(0.1)

    def _should_drop_event(self, data: dict) -> bool:
        """Check if event should be dropped due to null values.

        Args:
            data: Event data

        Returns:
            True if event should be dropped

        """
        if isinstance(data, dict) and (
            data.get("observation") == "null" or data.get("action") == "null"
        ):
            try:
                self.logger.warning(
                    'Dropping event with literal "null" in observation/action',
                    extra={"payload_sample": data},
                )
            except Exception:
                pass  # logging failure must not affect event filtering
            return True
        return False

    async def _emit_to_client(self, data: dict) -> None:
        """Emit event to client via websocket.

        Args:
            data: Event data to emit

        """
        self._wait_websocket_initial_complete = False

        # Performance logging for streaming events
        event_type = data.get("action") or data.get("observation") or "unknown"
        event_id = data.get("id", "N/A")
        self.logger.debug("📡 Emitting to WebSocket: %s (id=%s)", event_type, event_id)

        # Special logging for state changes
        if data.get("observation") == "agent_state_changed":
            self.logger.info(
                "🔄 Agent state changed to: %s",
                data.get("extras", {}).get("agent_state", "unknown"),
            )

        if self.sio is None:
            self.logger.warning("Socket.IO server not available; dropping event.")
            return
        await self.sio.emit("forge_event", data, to=ROOM_KEY.format(sid=self.sid))

    async def send_error(self, message: str) -> None:
        """Sends an error message to the client."""
        await self._send_status_message("error", RuntimeStatus.ERROR, message)

    async def _send_status_message(
        self, msg_type: str, runtime_status: RuntimeStatus, message: str
    ) -> None:
        """Sends a status message to the client."""
        if msg_type == "error":
            agent_session = self.agent_session
            controller = self.agent_session.controller
            if controller is not None and (not agent_session.is_closed()):
                await controller.set_agent_state_to(AgentState.ERROR)
            else:
                # If no controller yet, manually emit state change so UI updates
                await self.send(
                    event_to_dict(
                        AgentStateChangedObservation(
                            content=message,
                            reason=message,
                            agent_state=AgentState.ERROR,
                        )
                    )
                )
            self.logger.error(
                "Agent status error: %s",
                message,
                extra={"signal": "agent_status_error"},
            )
        await self.send(
            {
                "status_update": True,
                "type": msg_type,
                "id": runtime_status.value,
                "message": message,
            }
        )

    def queue_status_message(
        self, msg_type: str, runtime_status: RuntimeStatus, message: str
    ) -> None:
        """Queues a status message to be sent asynchronously."""
        asyncio.run_coroutine_threadsafe(
            self._send_status_message(msg_type, runtime_status, message), self.loop
        )
