"""Condenser that masks older browser observations to reduce token usage."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config.condenser_config import BrowserOutputCondenserConfig
from backend.events.observation import BrowserOutputObservation
from backend.events.observation.agent import AgentCondensationObservation
from backend.memory.condenser.condenser import Condensation, Condenser
from backend.memory.view import View

if TYPE_CHECKING:
    from backend.events.event import Event
    from backend.llm.llm_registry import LLMRegistry


class BrowserOutputCondenser(Condenser):
    """A condenser that masks the observations from browser outputs outside of a recent attention window.

    The intent here is to mask just the browser outputs and leave everything else untouched. This is important because currently we provide screenshots and accessibility trees as input to the model for browser observations. These are really large and consume a lot of tokens without any benefits in performance. So we want to mask all such observations from all previous timesteps, and leave only the most recent one in context.
    """

    def __init__(self, attention_window: int = 1) -> None:
        """Initialize browser output condenser with attention window.

        Args:
            attention_window: Number of recent browser outputs to keep in full. Defaults to 1

        Returns:
            None

        Side Effects:
            - Sets self.attention_window
            - Calls parent Condenser.__init__()

        Notes:
            - Browser outputs (screenshots, trees) are very token-expensive
            - Only keeping most recent keeps context fresh while reducing tokens
            - Earlier browser outputs replaced with URL placeholder + "Content omitted"

        Example:
            >>> condenser = BrowserOutputCondenser(attention_window=2)
            >>> # Last 2 browser outputs stay; older ones are masked

        """
        self.attention_window = attention_window
        super().__init__()

    def condense(self, view: View) -> View | Condensation:
        """Replace the content of browser observations outside of the attention window with a placeholder."""
        results: list[Event] = []
        cnt: int = 0
        for event in reversed(view):
            if isinstance(event, BrowserOutputObservation) and cnt >= self.attention_window:
                results.append(AgentCondensationObservation(f"Visited URL {event.url}\nContent omitted"))
            else:
                results.append(event)
                if isinstance(event, BrowserOutputObservation):
                    cnt += 1
        return View(events=list(reversed(results)))

    @classmethod
    def from_config(cls, config: BrowserOutputCondenserConfig, llm_registry: LLMRegistry) -> BrowserOutputCondenser:
        """Instantiate condenser from Pydantic config."""
        from backend.core.pydantic_compat import model_dump_with_options

        return BrowserOutputCondenser(**model_dump_with_options(config, exclude={"type"}))


# Lazy registration to avoid circular imports
def _register_config():
    """Register BrowserOutputCondenser config class for factory pattern.

    Args:
        None

    Returns:
        None

    Side Effects:
        - Registers BrowserOutputCondenserConfig with condenser factory
        - Called at module load time to enable dynamic config creation

    Notes:
        - Deferred import avoids circular dependency on config module
        - Enables from_config class method to work

    """
    from backend.core.config.condenser_config import BrowserOutputCondenserConfig

    BrowserOutputCondenser.register_config(BrowserOutputCondenserConfig)


_register_config()
