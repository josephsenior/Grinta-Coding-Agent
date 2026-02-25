"""Browser environment wrapper."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

class BrowserEnv:
    """Wrapper around a browser environment (e.g., Playwright). STUB implementation."""

    def __init__(self):
        """Initialize browser environment."""
        self.browser_launched = False
        logger.warning("Browser environment is a stub and will not function. Ensure browser-use MCP is configured.")

    def check_alive(self, timeout: int = 5) -> bool:
        """Check if browser process is alive."""
        return False

    def init_browser(self):
        """Perform actual browser launch."""
        logger.error("Attempted to initialize stub browser environment.")

    def close(self):
        """Close browser environment."""
        pass
