"""Browser-related action types for navigating and interacting with pages."""

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ActionSecurityRisk
from backend.core.schemas import ActionType
from backend.events.action.action import Action


@dataclass
class BrowseURLAction(Action):
    """Action to navigate browser to a URL.

    Attributes:
        url: URL to navigate to
        thought: Agent's reasoning for this action
        return_axtree: Whether to return accessibility tree

    """

    url: str = ""
    thought: str = ""
    action: ClassVar[str] = ActionType.BROWSE
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN
    return_axtree: bool = False

    @property
    def message(self) -> str:
        """Get browser navigation message."""
        return f"I am browsing the URL: {self.url}"

    def __str__(self) -> str:
        """Return a readable summary including thought and URL."""
        ret = "**BrowseURLAction**\n"
        if self.thought:
            ret += f"THOUGHT: {self.thought}\n"
        ret += f"URL: {self.url}"
        return ret

    __test__ = False


@dataclass
class BrowseInteractiveAction(Action):
    """Action to interact with browser (click, type, etc.).

    Uses BrowserGym actions to control the browser programmatically.

    Attributes:
        browser_actions: BrowserGym action code to execute
        thought: Agent's reasoning for this action
        browsergym_send_msg_to_user: Message to display to user
        return_axtree: Whether to return accessibility tree

    """

    browser_actions: str = ""
    thought: str = ""
    browsergym_send_msg_to_user: str = ""
    action: ClassVar[str] = ActionType.BROWSE_INTERACTIVE
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN
    return_axtree: bool = False

    @property
    def message(self) -> str:
        """Get browser interaction message."""
        return f"I am interacting with the browser:\n```\n{self.browser_actions}\n```"

    def __str__(self) -> str:
        """Return a readable summary including thought and browser actions."""
        ret = "**BrowseInteractiveAction**\n"
        if self.thought:
            ret += f"THOUGHT: {self.thought}\n"
        ret += f"BROWSER_ACTIONS: {self.browser_actions}"
        return ret

    __test__ = False
