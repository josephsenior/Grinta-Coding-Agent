"""Gemini context caching manager for the app."""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from google import genai

from backend.core.logger import app_logger as logger


class GeminiCacheManager:
    """Manages Gemini context caches to avoid redundant uploads and reduce costs.

    Gemini stateful context caching requires explicit creation and management
    of cache objects. This manager tracks creations and attempts to reuse
    existing caches based on content hashes.
    """

    _instance = None
    _lock = None
    _caches: dict[str, str]

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._caches = {}  # hash -> cache_name
        return cls._instance

    def _get_hash(self, system_instruction: str | None, messages: list[dict]) -> str:
        """Create a stable hash of the context to identify existing caches."""
        content = f"sys:{system_instruction or ''}|msgs:{str(messages)}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get_or_create_cache(
        self,
        client: genai.Client,
        model: str,
        system_instruction: str | None,
        messages: list[dict],
        ttl_minutes: int = 60,
    ) -> str | None:
        """Get an existing cache name or create a new one for the given context.

        Args:
            client: The genai.Client instance
            model: Model name (e.g. 'gemini-1.5-pro')
            system_instruction: The system prompt
            messages: The list of messages (history)
            ttl_minutes: Time-to-live for the cache in minutes

        Returns:
            The name/ID of the cache, or None if creation failed or model doesn't support it.
        """
        # Context caching is typically for > 32k tokens.
        # We only use it if specifically requested via 'cache_prompt'
        # logic handled in the calling client.

        content_hash = self._get_hash(system_instruction, messages)

        # Check in-memory index first
        if content_hash in self._caches:
            cache_name = self._caches[content_hash]
            try:
                # Verify it still exists in Google's end
                client.caches.get(name=cache_name)
                logger.debug("Reusing Gemini context cache: %s", cache_name)
                return cache_name
            except Exception:
                logger.debug(
                    "Gemini cache %s expired or not found, recreating", cache_name
                )
                del self._caches[content_hash]

        try:
            # Prepare contents for Gemini caching
            # Gemini caching usually takes system_instruction + initial messages
            contents = []
            for m in messages:
                role = "user" if m.get("role") == "user" else "model"
                contents.append(
                    {"role": role, "parts": [{"text": m.get("content", "")}]}
                )

            cache = cast(Any, client.caches.create)(
                model=model,
                config={
                    "display_name": f"app_cache_{int(time.time())}",
                    "system_instruction": system_instruction,
                    "ttl": f"{ttl_minutes * 60}s",
                },
                contents=contents,
            )

            logger.info(
                "Created new Gemini context cache: %s for model %s", cache.name, model
            )
            self._caches[content_hash] = cache.name
            return cache.name

        except Exception as e:
            logger.warning("Failed to create Gemini context cache: %s", e)
            return None

    def cleanup_old_caches(self, client: genai.Client):
        """Cleanup expired caches from the provider."""
        try:
            for _ in client.caches.list():
                # Google handles TTL automatically, but we can manually delete
                # if we have too many or they are redundant.
                pass
        except Exception as e:
            logger.debug("Failed to list/cleanup Gemini caches: %s", e)


# Global instance
gemini_cache_manager = GeminiCacheManager()
