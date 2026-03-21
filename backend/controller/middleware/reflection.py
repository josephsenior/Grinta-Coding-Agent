"""Reflection middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.controller.tool_pipeline import ToolInvocationMiddleware
from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.tool_pipeline import ToolInvocationContext


class ReflectionMiddleware(ToolInvocationMiddleware):
    """Enables self-reflection before executing actions."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller

    async def verify(self, ctx: ToolInvocationContext) -> None:
        """Verify action correctness before execution."""
        if not ctx.action.runnable:
            return

        agent = getattr(self.controller, "agent", None)
        if not agent:
            return

        config = getattr(agent, "config", None)
        if not self._is_reflection_enabled(config):
            return

        from backend.events.action import FileEditAction, FileWriteAction, CmdRunAction

        # For file edits, verify syntax and logic
        if isinstance(ctx.action, (FileEditAction, FileWriteAction)):
            await self._verify_file_action(ctx, agent)

        # For commands, verify safety
        if isinstance(ctx.action, CmdRunAction):
            await self._verify_command_action(ctx, agent)

    async def _verify_file_action(self, ctx: ToolInvocationContext, agent) -> None:
        """Verify file edit action before execution."""
        action = ctx.action
        if not hasattr(action, "path") or not hasattr(action, "content"):
            return

        # Basic verification: check for common errors
        content = getattr(action, "content", "")
        if not content:
            return

        # Check for syntax errors in common file types
        path = getattr(action, "path", "")
        if path.endswith((".py", ".js", ".ts", ".json")):
            # Basic validation - could be extended with actual parsers
            if path.endswith(".json") and content:
                try:
                    import json

                    json.loads(content)
                except json.JSONDecodeError:
                    logger.warning(
                        "⚠️ Reflection: Potential JSON syntax error in %s", path
                    )
                    # Don't block, but log warning

        logger.debug("✅ Reflection: File action verified for %s", path)

    async def _verify_command_action(self, ctx: ToolInvocationContext, agent) -> None:
        """Verify command action before execution."""
        action = ctx.action
        if not hasattr(action, "command"):
            return

        command = getattr(action, "command", "")
        if not command:
            return

        # Check for destructive operations
        destructive_patterns = [
            r"\brm\s+-rf\s+/",
            r"\bdd\s+if=",
            r"\bmkfs\s+",
            r"\bformat\s+",
            r">\s+/dev/",
        ]

        import re

        for pattern in destructive_patterns:
            if re.search(pattern, command):
                from backend.events.event import EventSource
                from backend.events.observation import ErrorObservation

                logger.warning(
                    "Reflection blocked destructive command: %s",
                    command,
                )
                ctx.block("reflection_blocked_destructive_command")
                ctx.metadata["handled"] = True
                error_obs = ErrorObservation(
                    content=(
                        "ACTION BLOCKED: Reflection middleware detected a potentially destructive command.\n"
                        f"Command: {command}"
                    ),
                    error_id="REFLECTION_BLOCKED_DESTRUCTIVE_COMMAND",
                )
                error_obs.cause = getattr(ctx.action, "id", None)
                self.controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)
                self.controller._pending_action = None
                return

        logger.debug("✅ Reflection: Command action verified: %s", command)

    @staticmethod
    def _is_reflection_enabled(config: Any) -> bool:
        if not config:
            return False
        return bool(
            getattr(config, "enable_reflection", True)
            and getattr(config, "enable_reflection_middleware", False)
        )
