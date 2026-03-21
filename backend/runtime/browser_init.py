"""Browser environment initialization for the action execution server."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.runtime.browser.browser_env import BrowserEnv


async def init_browser(enable_browser: bool) -> BrowserEnv | None:
    """Initialize the browser environment asynchronously.

    Args:
        enable_browser: Whether browser support is enabled.

    Returns:
        BrowserEnv instance if successful, None otherwise.
    """
    if not enable_browser:
        return None

    try:
        logger.info("Initializing browser environment...")
        from backend.runtime.browser.browser_env import BrowserEnv

        browser = BrowserEnv()
        logger.info("Browser environment initialized successfully")
        return browser
    except Exception as e:
        logger.error("Failed to initialize browser: %s", e)
        return None
