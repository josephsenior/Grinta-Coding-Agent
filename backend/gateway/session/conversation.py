"""Server-side wrapper for conversations, linking runtimes and event streams."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from backend.core.logger import app_logger as logger
from backend.inference.llm_registry import LLMRegistry
from backend.execution import get_runtime_cls
from backend.gateway.app_accessors import get_event_service_adapter

if TYPE_CHECKING:
    from backend.core.config import AppConfig
    from backend.ledger.stream import EventStream
    from backend.execution.base import Runtime
    from backend.persistence.files import FileStore


class ServerConversation:
    """In-memory representation of a conversation session managed by server."""

    sid: str
    file_store: FileStore
    event_stream: EventStream
    runtime: Runtime
    user_id: str | None
    _attach_to_existing: bool = False

    def __init__(
        self,
        sid: str,
        file_store: FileStore,
        config: AppConfig,
        user_id: str | None,
        event_stream: EventStream | None = None,
        runtime: Runtime | None = None,
    ) -> None:
        """Initialize conversation state, optionally attaching to an existing runtime."""
        self.sid = sid
        self.config = config
        self.file_store = file_store
        self.user_id = user_id
        if event_stream is None:
            adapter = get_event_service_adapter()
            adapter.start_session(
                session_id=sid,
                user_id=user_id,
                labels={"source": "server_conversation"},
            )
            event_stream = adapter.get_event_stream(sid)
        self.event_stream = event_stream
        if runtime:
            self._attach_to_existing = True
        else:
            runtime_cls = get_runtime_cls(self.config.runtime)
            # Runtime can start WITHOUT valid LLM config
            # Agent (created later) is what actually needs LLM
            # This allows background runtime initialization for faster UX
            try:
                llm_registry = LLMRegistry(self.config)
            except Exception as e:
                # If LLM config invalid/missing, create empty registry
                # Runtime will work, agent creation will fail (expected)
                logger.warning(
                    "LLM config not ready, runtime will start without agent capability: %s",
                    e,
                )
                llm_registry = LLMRegistry(self.config, require_llm=False)

            runtime = _instantiate_runtime(
                runtime_cls,
                llm_registry=llm_registry,
                config=config,
                event_stream=self.event_stream,
                sid=self.sid,
                attach_to_existing=False,
                headless_mode=False,
            )
        self.runtime = runtime

    @property
    def security_analyzer(self):
        """Access security analyzer through runtime."""
        return self.runtime.security_analyzer

    async def connect(self) -> None:
        """Connect to runtime environment.

        Skipped if attaching to existing runtime.
        """
        if not self._attach_to_existing:
            from backend.execution.supervisor import runtime_supervisor

            await runtime_supervisor.ensure_connected(self)

    async def disconnect(self) -> None:
        """Disconnect from runtime and clean up resources.

        Skipped if attached to existing runtime.
        """
        if self._attach_to_existing:
            return
        if self.event_stream:
            self.event_stream.close()
        from backend.execution.supervisor import runtime_supervisor
        from backend.utils.async_utils import create_tracked_task

        create_tracked_task(
            runtime_supervisor.close(self),
            name="runtime-close",
        )


def _instantiate_runtime(runtime_cls: type[object], **kwargs: Any) -> Runtime:
    """Instantiate runtime implementation and return Runtime-typed value."""
    return cast("Runtime", runtime_cls(**kwargs))
