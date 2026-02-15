"""Action type for invoking Model Context Protocol tools."""

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.schemas import ActionType
from backend.events.action.action import Action, ActionSecurityRisk


@dataclass
class MCPAction(Action):
    """Action to call an MCP (Model Context Protocol) tool.

    Attributes:
        name: Name of the MCP tool to call
        arguments: Arguments to pass to the tool
        thought: Agent's reasoning for this action

    """

    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    thought: str = ""
    action: ClassVar[str] = ActionType.MCP
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get MCP tool call message."""
        return f"I am interacting with the MCP server with name:\n```\n{
            self.name
        }\n```\nand arguments:\n```\n{self.arguments}\n```"

    def __str__(self) -> str:
        """Return a readable summary of the MCP invocation."""
        ret = "**MCPAction**\n"
        if self.thought:
            ret += f"THOUGHT: {self.thought}\n"
        ret += f"NAME: {self.name}\n"
        ret += f"ARGUMENTS: {self.arguments}"
        return ret

    __test__ = False
