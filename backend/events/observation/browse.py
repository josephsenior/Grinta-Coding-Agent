"""Browser observation payloads capturing rendered pages and metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.schemas import ObservationType
from backend.events.observation.observation import Observation


@dataclass
class BrowserOutputObservation(Observation):
    """This data class represents the output of a browser."""

    url: str
    trigger_by_action: str
    screenshot: str = field(repr=False, default="")
    screenshot_path: str | None = field(default=None)
    set_of_marks: str = field(default="", repr=False)
    error: bool = False
    goal_image_urls: list[str] = field(default_factory=list)
    open_pages_urls: list[str] = field(default_factory=list)
    active_page_index: int = -1
    dom_object: dict[str, Any] = field(default_factory=dict, repr=False)
    axtree_object: dict[str, Any] = field(default_factory=dict, repr=False)
    extra_element_properties: dict[str, Any] = field(default_factory=dict, repr=False)
    last_browser_action: str = ""
    last_browser_action_error: str = ""
    focused_element_bid: str = ""
    filter_visible_only: bool = False
    observation: ClassVar[str] = ObservationType.BROWSE

    @property
    def message(self) -> str:
        """Get browser navigation message."""
        return f"Visited {self.url}"

    def __str__(self) -> str:
        """Return a readable summary of the browser state and agent notes."""
        ret = f"**BrowserOutputObservation**\nURL: {self.url}\nError: {
            self.error
        }\nOpen pages: {self.open_pages_urls}\nActive page index: {
            self.active_page_index
        }\nLast browser action: {self.last_browser_action}\nLast browser action error: {
            self.last_browser_action_error
        }\nFocused element bid: {self.focused_element_bid}\n"
        if self.screenshot_path:
            ret += f"Screenshot saved to: {self.screenshot_path}\n"
        ret += "--- Agent Observation ---\n"
        ret += self.content
        return ret
