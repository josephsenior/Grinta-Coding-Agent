"""Observation renderers — think_browser domain."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object


from backend.cli._typing import ObservationRenderersHost
from backend.ledger.observation import (
    AgentThinkObservation,
    BrowserScreenshotObservation,
)

logger = logging.getLogger(__name__)


class _ObsThinkBrowserMixin(_ObservationRenderersBase):
    def _render_agent_think_observation(self, obs: AgentThinkObservation) -> None:
        if bool(getattr(obs, 'suppress_cli', False)):
            self.refresh()
            return
        thought = getattr(obs, 'thought', '') or getattr(obs, 'content', '')
        self._apply_reasoning_text(thought)
        self.refresh()

    def _render_browser_screenshot_observation(
        self, obs: BrowserScreenshotObservation
    ) -> None:
        """Same UX as browser ``CmdOutputObservation``: suppress duplicate shell row."""
        del obs
        self._stop_reasoning()
        self._flush_pending_activity_card()
        self._reset_pending_shell()
        self.refresh()
