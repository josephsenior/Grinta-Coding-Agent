"""Module-level accessors backed by AppState.

All mutable state lives in :class:`~backend.gateway.app_state.AppState`.
This module exports stable accessors and shared references that delegate
to the centralised AppState container.

**No module-level ``global`` mutations** — every accessor function reads
directly from ``AppState``, ensuring a single source of truth.

.. deprecated::
    Route files should inject ``AppConfig``, ``file_store``, and ``server_config``
    via FastAPI ``Depends()`` providers defined in
    ``backend.gateway.services.service_dependencies`` (``get_app_config``,
    ``get_file_store``, ``get_server_config``). Direct accessor imports from
    this module remain supported for non-route code (CLI, tests, utilities)
    that cannot use the DI system.
"""

from __future__ import annotations

import logging

from backend.gateway.app_state import get_app_state

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Eagerly available (read-only references delegated to AppState)
# ---------------------------------------------------------------------------
_state = get_app_state()

server_config = _state.server_config
sio = _state.sio
def get_config():
    """Get the current AppConfig reference."""
    return _state.config
file_store = _state.file_store
monitoring_listener = _state.monitoring_listener

# Store implementation classes with proper type annotations
from backend.persistence.conversation.conversation_store import ConversationStore  # noqa: E402
from backend.persistence.secrets.secrets_store import SecretsStore  # noqa: E402
from backend.persistence.settings.settings_store import SettingsStore  # noqa: E402

SettingsStoreImpl: type[SettingsStore] = _state.SettingsStoreImpl
SecretsStoreImpl: type[SecretsStore] = _state.SecretsStoreImpl
ConversationStoreImpl: type[ConversationStore] = _state.ConversationStoreImpl


# ---------------------------------------------------------------------------
# Lazy accessors — delegate directly to AppState without caching here
# ---------------------------------------------------------------------------


def get_event_service_adapter():
    """Get or create the event service adapter singleton."""
    return _state.get_event_service_adapter()


def get_conversation_manager_impl():
    """Get the ConversationManager implementation class."""
    return _state.get_conversation_manager_impl()


def get_conversation_manager():
    """Get the conversation manager singleton."""
    return _state.get_conversation_manager()


async def get_conversation_store_async(user_id: str | None = None):
    """Async-safe conversation store accessor."""
    return await _state.get_conversation_store_async(user_id)


def get_conversation_store():
    """Synchronous conversation store accessor."""
    return _state.get_conversation_store()

