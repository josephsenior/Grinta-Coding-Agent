"""Application state container for the Forge server.

Replaces hidden mutable globals in ``shared.py`` with an explicit,
app-scoped container that encapsulates singleton lifecycle.  Module-level
accessors in ``shared.py`` delegate to this container so that existing
import sites continue to work without changes.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any

from backend.core.config import ForgeConfig
from backend.ledger.adapter import EventServiceAdapter
from backend.gateway.config.server_config import ServerConfig, load_server_config
from backend.gateway.monitoring import MonitoringListener
from backend.gateway.store_factory import get_conversation_store_instance
from backend.persistence.conversation.conversation_store import ConversationStore
from backend.persistence.files import FileStore
from backend.persistence.local_file_store import LocalFileStore
from backend.utils.import_utils import get_impl

logger = logging.getLogger(__name__)


def _close_and_clear(obj: Any, name: str) -> None:
    """Close object if it has a close method; always returns None. Logs errors."""
    if obj is None:
        return
    try:
        if hasattr(obj, "close"):
            obj.close()
    except Exception:
        logger.debug("Error closing %s", name, exc_info=True)


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

        from pathlib import Path

        from backend.core.app_paths import get_app_settings_root
        from backend.core.config.config_loader import load_forge_config
        from backend.core.workspace_resolution import (
            apply_workspace_to_config,
            is_reserved_user_forge_data_dir,
            load_persisted_workspace_path,
            resolve_existing_directory,
        )

        self.config: ForgeConfig = load_forge_config()

        persisted = load_persisted_workspace_path()
        if persisted:
            try:
                root = resolve_existing_directory(persisted)
                apply_workspace_to_config(self.config, root)
            except ValueError as e:
                logger.warning(
                    "Ignoring persisted workspace path %s: %s", persisted, e
                )

        wb = (self.config.project_root or "").strip()
        if not wb:
            fsp = (self.config.local_data_root or "").strip()
            if fsp:
                try:
                    cand = Path(fsp).expanduser().resolve()
                    if is_reserved_user_forge_data_dir(cand):
                        self.config.local_data_root = ""
                    else:
                        apply_workspace_to_config(self.config, cand)
                        wb = (self.config.project_root or "").strip()
                except OSError:
                    self.config.local_data_root = ""

        app_root = str(Path(get_app_settings_root()).resolve())
        if wb:
            disk_root = str(Path(wb).expanduser().resolve())
        else:
            disk_root = app_root
        self.config.local_data_root = disk_root

        self.file_store: FileStore = LocalFileStore(disk_root)

        # Store implementation classes (resolved once from config)
        from backend.persistence.secrets.secrets_store import SecretsStore
        from backend.persistence.settings.settings_store import SettingsStore

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

        # Default: allow all origins for local development. In production override
        # FORGE_CORS_ORIGINS with an explicit comma-separated list.
        _default_cors = os.environ.get("FORGE_CORS_ORIGINS", "*")
        if _default_cors == "*":
            _allowed: list[str] | str = "*"
        else:
            _allowed = [o.strip() for o in _default_cors.split(",") if o.strip()]
        self.sio = socketio.AsyncServer(
            cors_allowed_origins=_allowed, async_mode="asgi"
        )

        # Lazily initialized singletons
        self._event_service_adapter: EventServiceAdapter | None = None
        self._conversation_manager_impl: type | None = None
        self._conversation_manager: Any = None
        self._conversation_store: ConversationStore | None = None
        self.monitoring_listener: MonitoringListener | None = None
        self._state_restore_records: dict[str, dict[str, Any]] = {}
        self._startup_snapshot: dict[str, Any] | None = None

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
        from backend.gateway.conversation_manager.conversation_manager import (
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

                # Ensure config is fresh before initializing manager
                from backend.core.config.config_loader import load_forge_config
                self.config = load_forge_config()

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

    def record_state_restore(
        self,
        sid: str,
        *,
        source: str,
        path: str,
        primary_error: str | None = None,
    ) -> None:
        """Record state restore provenance for operator-facing diagnostics."""
        entry = {
            "sid": sid,
            "source": source,
            "path": path,
            "primary_error": primary_error,
            "recorded_at": time.time(),
        }
        with self._lock:
            self._state_restore_records[sid] = entry
            if len(self._state_restore_records) > 50:
                oldest_sid = min(
                    self._state_restore_records,
                    key=lambda key: self._state_restore_records[key].get(
                        "recorded_at", 0.0
                    ),
                )
                self._state_restore_records.pop(oldest_sid, None)

    def get_state_restore_snapshot(self, limit: int = 10) -> dict[str, Any]:
        """Return recent state-restore provenance for health/status endpoints."""
        with self._lock:
            records = sorted(
                self._state_restore_records.values(),
                key=lambda item: item.get("recorded_at", 0.0),
                reverse=True,
            )
        trimmed = records[: max(limit, 0)]
        return {
            "count": len(records),
            "recent": trimmed,
        }

    def record_startup_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Record the latest local-server startup plan for health/status endpoints."""
        entry = dict(snapshot)
        entry["recorded_at"] = time.time()
        with self._lock:
            self._startup_snapshot = entry

    def get_startup_snapshot(self) -> dict[str, Any]:
        """Return the latest recorded startup snapshot, if any."""
        with self._lock:
            snapshot = dict(self._startup_snapshot or {})
        return snapshot

    def close(self) -> None:
        """Release resources held by this AppState instance.

        Closes the conversation manager (which stops sessions and runtimes),
        the event service adapter, and the conversation store.  Safe to call
        multiple times.
        """
        with self._lock:
            _close_and_clear(self._conversation_manager, "conversation manager")
            self._conversation_manager = None
            _close_and_clear(self._event_service_adapter, "event service adapter")
            self._event_service_adapter = None
            _close_and_clear(self._conversation_store, "conversation store")
            self._conversation_store = None
            logger.info("AppState closed")


# Global singleton — created once at import time (same as before)
_app_state: AppState | None = None
_state_lock = threading.Lock()


def get_app_state() -> AppState:
    """Return (or create) the global ``AppState`` singleton."""
    module = sys.modules[__name__]
    if module.__dict__.get("_app_state") is None:
        with _state_lock:
            if module.__dict__.get("_app_state") is None:
                module.__dict__["_app_state"] = AppState()
    return module.__dict__["_app_state"]

