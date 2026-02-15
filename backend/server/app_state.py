"""Application state container for the Forge server.

Replaces hidden mutable globals in ``shared.py`` with an explicit,
app-scoped container that encapsulates singleton lifecycle.  Module-level
accessors in ``shared.py`` delegate to this container so that existing
import sites continue to work without changes.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from backend.core.config import ForgeConfig
from backend.events.adapter import EventServiceAdapter
from backend.server.config.server_config import ServerConfig, load_server_config
from backend.server.monitoring import MonitoringListener
from backend.server.store_factory import get_conversation_store_instance
from backend.storage.conversation.conversation_store import ConversationStore
from backend.storage.files import FileStore
from backend.storage.local import LocalFileStore
from backend.utils.import_utils import get_impl

logger = logging.getLogger(__name__)


class AppState:
    """Centralized, explicit application state.

    All singletons are lazily initialized through accessor methods rather than
    at module-import time.  A ``threading.Lock`` guards lazy init to keep it
    safe for use from synchronous bootstrap code.
    """

    def __init__(self, server_config: ServerConfig | None = None) -> None:
        self._lock = threading.Lock()

        # Eagerly loaded (cheap, no I/O)
        self.server_config: ServerConfig = server_config or load_server_config()
        self.config: ForgeConfig = ForgeConfig()
        workspace_base = os.path.expanduser(self.config.file_store_path)
        self.file_store: FileStore = LocalFileStore(workspace_base)

        # Store implementation classes (resolved once from config)
        from backend.storage.secrets.secrets_store import SecretsStore
        from backend.storage.settings.settings_store import SettingsStore

        self.SettingsStoreImpl: type[SettingsStore] = get_impl(
            SettingsStore, self.server_config.settings_store_class
        )
        self.SecretsStoreImpl: type[SecretsStore] = get_impl(
            SecretsStore, self.server_config.secret_store_class
        )
        self.ConversationStoreImpl: type[ConversationStore] = get_impl(
            ConversationStore, self.server_config.conversation_store_class
        )

        # Socket.IO (created once)
        import socketio  # type: ignore[import-untyped]

        _default_cors = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"
        _cors_str = os.environ.get("FORGE_CORS_ORIGINS", _default_cors)
        _allowed = [o.strip() for o in _cors_str.split(",") if o.strip()]
        self.sio = socketio.AsyncServer(
            cors_allowed_origins=_allowed, async_mode="asgi"
        )

        # Lazily initialized singletons
        self._event_service_adapter: EventServiceAdapter | None = None
        self._conversation_manager_impl: type | None = None
        self._conversation_manager: Any = None
        self._conversation_store: ConversationStore | None = None
        self.monitoring_listener: MonitoringListener | None = None

    # ----- Event service adapter -----

    def get_event_service_adapter(self) -> EventServiceAdapter:
        with self._lock:
            if self._event_service_adapter is None:
                self._event_service_adapter = EventServiceAdapter(
                    lambda user_id: self.file_store
                )
        return self._event_service_adapter

    @property
    def event_service_adapter(self) -> EventServiceAdapter | None:
        return self._event_service_adapter

    # ----- Conversation manager -----

    def get_conversation_manager_impl(self) -> type:
        from backend.server.conversation_manager.conversation_manager import (
            ConversationManager,
        )

        if self._conversation_manager_impl is None:
            self._conversation_manager_impl = get_impl(
                ConversationManager, self.server_config.conversation_manager_class
            )
        return self._conversation_manager_impl

    def get_conversation_manager(self) -> Any:
        with self._lock:
            if self._conversation_manager is None:
                logger.debug(
                    "Resolving ConversationManager: %s",
                    self.server_config.conversation_manager_class,
                )
                impl = self.get_conversation_manager_impl()
                self._conversation_manager = impl.get_instance(  # type: ignore[attr-defined]
                    self.sio,
                    self.config,
                    self.file_store,
                    self.server_config,
                    self.monitoring_listener,
                )
                logger.info(
                    "ConversationManager initialized: %s",
                    type(self._conversation_manager).__name__,
                )
        return self._conversation_manager

    @property
    def conversation_manager(self) -> Any:
        return self._conversation_manager

    # ----- Conversation store -----

    async def get_conversation_store_async(
        self, user_id: str | None = None
    ) -> ConversationStore:
        if self._conversation_store is not None:
            return self._conversation_store
        store = await get_conversation_store_instance(
            self.ConversationStoreImpl, self.config, user_id or "oss_user"
        )
        self._conversation_store = store
        return store

    def get_conversation_store(self) -> ConversationStore | None:
        if self._conversation_store is not None:
            return self._conversation_store
        import asyncio

        from backend.utils.async_utils import get_active_loop

        loop = get_active_loop()
        if loop is not None:
            logger.warning(
                "get_conversation_store() called from running loop; use async variant"
            )
            return None
        try:
            loop = asyncio.new_event_loop()
            self._conversation_store = loop.run_until_complete(
                get_conversation_store_instance(
                    self.ConversationStoreImpl, self.config, "oss_user"
                )
            )
            loop.close()
            return self._conversation_store
        except Exception as e:
            logger.error("Failed to init conversation_store: %s", e)
            return None

    # ----- Teardown -----

    def close(self) -> None:
        """Release resources held by this AppState instance.

        Closes the conversation manager (which stops sessions and runtimes),
        the event service adapter, and the conversation store.  Safe to call
        multiple times.
        """
        with self._lock:
            if self._conversation_manager is not None:
                try:
                    if hasattr(self._conversation_manager, "close"):
                        self._conversation_manager.close()
                except Exception:
                    logger.debug("Error closing conversation manager", exc_info=True)
                self._conversation_manager = None

            if self._event_service_adapter is not None:
                try:
                    if hasattr(self._event_service_adapter, "close"):
                        self._event_service_adapter.close()
                except Exception:
                    logger.debug("Error closing event service adapter", exc_info=True)
                self._event_service_adapter = None

            if self._conversation_store is not None:
                try:
                    if hasattr(self._conversation_store, "close"):
                        self._conversation_store.close()
                except Exception:
                    logger.debug("Error closing conversation store", exc_info=True)
                self._conversation_store = None

            logger.info("AppState closed")


# Global singleton — created once at import time (same as before)
_app_state: AppState | None = None
_state_lock = threading.Lock()


def get_app_state() -> AppState:
    """Return (or create) the global ``AppState`` singleton."""
    global _app_state
    if _app_state is None:
        with _state_lock:
            if _app_state is None:
                _app_state = AppState()
    return _app_state
