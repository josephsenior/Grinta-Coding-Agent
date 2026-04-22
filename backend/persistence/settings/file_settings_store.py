"""SettingsStore implementation persisted via the configured FileStore backend."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import SecretStr

from backend.core.app_paths import get_app_settings_root
from backend.core.config.dotenv_keys import persist_llm_api_key_to_dotenv
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER, SETTINGS_CACHE_TTL
from backend.core.pydantic_compat import model_dump_with_options
from backend.persistence import get_file_store
from backend.persistence.data_models.settings import Settings
from backend.persistence.settings.settings_store import SettingsStore
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from backend.core.config.app_config import AppConfig
    from backend.persistence.files import FileStore

# 🚀 PERFORMANCE FIX: Global cache and lock for concurrent file access
#   Prevents file I/O contention when multiple users load settings simultaneously
_file_settings_cache: dict[str, tuple[Settings | None, float]] = {}
_file_settings_locks: dict[str, asyncio.Lock] = {}


@dataclass
class FileSettingsStore(SettingsStore):
    """SettingsStore implementation persisting workspace settings to local file."""

    file_store: FileStore
    path: str = 'settings.json'
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def load(self) -> Settings | None:
        """Load settings with caching and lock to prevent concurrent file I/O contention.

        🚀 PERFORMANCE FIX: Added global cache + asyncio lock to fix 1,129ms bottleneck
           when 10+ users load settings concurrently.
        """
        # 🚀 FIX: Check global cache first (keyed by path for multi-user support)
        cache_key = self.path
        current_time = time.time()

        if cache_key in _file_settings_cache:
            cached_settings, cached_time = _file_settings_cache[cache_key]
            if current_time - cached_time < SETTINGS_CACHE_TTL:
                return cached_settings

        # 🚀 FIX: Use lock to prevent concurrent file reads
        #   Get or create lock for this file path
        if cache_key not in _file_settings_locks:
            _file_settings_locks[cache_key] = asyncio.Lock()

        lock = _file_settings_locks[cache_key]

        async with lock:
            # Double-check cache after acquiring lock (another request might have loaded it)
            if cache_key in _file_settings_cache:
                cached_settings, cached_time = _file_settings_cache[cache_key]
                if current_time - cached_time < SETTINGS_CACHE_TTL:
                    return cached_settings

            # Cache miss - load from file
            try:
                json_str = await call_sync_from_async(self.file_store.read, self.path)
                kwargs = json.loads(json_str)
                settings = Settings(**kwargs)

                # 🚀 FIX: Cache the result
                _file_settings_cache[cache_key] = (settings, current_time)

                return settings
            except FileNotFoundError:
                # 🚀 FIX: Cache the None result too
                _file_settings_cache[cache_key] = (None, current_time)
                return None

    async def store(self, settings: Settings) -> None:
        """Store settings and invalidate cache."""
        # Persist LLM connectivity plus MCP overrides. App still supplies defaults;
        # merged MCP from GET is optional to save, but when the user edits MCP in the
        # UI we must not drop it on the next LLM-only save (merge happens before store).
        minimal = model_dump_with_options(
            settings,
            context={'expose_secrets': True},
            include={'llm_model', 'llm_api_key', 'llm_base_url', 'mcp_config'},
            exclude_none=False,
        )

        llm_api_key = minimal.get('llm_api_key')
        if isinstance(llm_api_key, SecretStr):
            llm_api_key = llm_api_key.get_secret_value()
        elif llm_api_key is not None:
            llm_api_key = str(llm_api_key).strip() or None

        llm_api_key_json: str | None
        if llm_api_key:
            settings_path = Path(get_app_settings_root()) / self.path
            persist_llm_api_key_to_dotenv(llm_api_key, settings_json_path=settings_path)
            llm_api_key_json = LLM_API_KEY_SETTINGS_PLACEHOLDER
        else:
            llm_api_key_json = llm_api_key

        normalized: dict = {
            'llm_model': minimal.get('llm_model'),
            'llm_api_key': llm_api_key_json,
            'llm_base_url': minimal.get('llm_base_url'),
        }
        mcp = minimal.get('mcp_config')
        if mcp is not None:
            normalized['mcp_config'] = mcp

        json_str = json.dumps(normalized, ensure_ascii=False, indent=2)
        await call_sync_from_async(self.file_store.write, self.path, json_str)

        # 🚀 FIX: Invalidate cache on write
        cache_key = self.path
        if cache_key in _file_settings_cache:
            del _file_settings_cache[cache_key]

    @classmethod
    async def get_instance(
        cls, config: AppConfig, user_id: str | None
    ) -> FileSettingsStore:
        """Get FileSettingsStore singleton instance.

        Persisted path is always ``settings.json`` under :func:`get_app_settings_root`
        (not ``config.local_data_root`` / project folder), so the open-folder workspace does not get a
        second settings file.

        Args:
            config: Application configuration (used for store *type* and webhooks only)
            user_id: Optional user ID

        Returns:
            FileSettingsStore instance

        """
        from backend.core.app_paths import get_app_settings_root

        file_store = get_file_store(
            file_store_type=config.file_store,
            local_data_root=get_app_settings_root(),
        )
        return FileSettingsStore(file_store)
