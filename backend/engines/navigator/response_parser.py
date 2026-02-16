"""Utilities for parsing LLM responses into browse actions."""

from __future__ import annotations

import ast
import re

from backend.controller.action_parser import ActionParser, ResponseParser
from backend.core.logger import FORGE_logger as logger
from backend.events.action import Action, BrowseInteractiveAction


class BrowsingResponseParser(ResponseParser):
    """Parse LLM responses into browsing actions for BrowserGym integration."""

    def __init__(self) -> None:
        """Initialize browsing response parser with action parsers."""
        super().__init__()
        self.action_parsers = [BrowsingActionParserMessage()]
        self.default_parser = BrowsingActionParserBrowseInteractive()

    def parse(
        self, response: str | dict[str, list[dict[str, dict[str, str | None]]]]
    ) -> Action:
        """Parse LLM response into a browsing action.

        Args:
            response: Raw LLM response (string or dict format)

        Returns:
            Parsed `Action` object for browser interaction.

        """
        if isinstance(response, str):
            action_str = response
        else:
            action_str = self.parse_response(response)
        return self.parse_action(action_str)

    def parse_response(
        self, response: dict[str, list[dict[str, dict[str, str | None]]]]
    ) -> str:
        """Extract an action string from a structured LLM response.

        Args:
            response: Structured LLM response with choices.

        Returns:
            Extracted action string with formatting fixes applied.

        """
        action_str = response["choices"][0]["message"]["content"]
        if action_str is None:
            return ""
        action_str = action_str.strip()
        if action_str and (not action_str.endswith("```")):
            action_str += "```" if action_str.endswith(")") else ")```"
        logger.debug(action_str)
        return action_str

    def parse_action(self, action_str: str) -> Action:
        """Parse an action string using the registered parsers.

        Tries each registered parser in order, falling back to the default
        BrowseInteractive parser if no specialized parser matches.

        Args:
            action_str: Action string to parse.

        Returns:
            Parsed `Action` object.

        """
        for action_parser in self.action_parsers:
            if action_parser.check_condition(action_str):
                return action_parser.parse(action_str)
        return self.default_parser.parse(action_str)


class BrowsingActionParserMessage(ActionParser):
    """Parse plain text messages into BrowserGym message actions.

    Handles cases where the LLM response does not contain code blocks,
    treating the entire response as a message to send to the user.
    """

    def __init__(self) -> None:
        """Initialize message parser."""

    def check_condition(self, action_str: str) -> bool:
        """Check whether the action string is a plain message (no code blocks).

        Args:
            action_str: Action string to check.

        Returns:
            True if the string contains no code block markers.

        """
        return "```" not in action_str

    def parse(self, action_str: str) -> Action:
        """Parse plain text into a `BrowseInteractiveAction` message action.

        Args:
            action_str: Plain text message from the LLM.

        Returns:
            `BrowseInteractiveAction` configured to send a message to the user.

        """
        msg = f'send_msg_to_user("""{action_str}""")'
        return BrowseInteractiveAction(
            browser_actions=msg,
            thought=action_str,
            browsergym_send_msg_to_user=action_str,
        )


class BrowsingActionParserBrowseInteractive(ActionParser):
    """Parse code-block formatted browser actions into browse interactions.

    Extracts browser commands from code blocks and separates them from
    the agent's thoughts. Also extracts any `send_msg_to_user` calls.
    """

    def __init__(self) -> None:
        """Initialize browse interactive parser."""

    def check_condition(self, action_str: str) -> bool:
        """Return True because this is the fallback parser."""
        return True

    def parse(self, action_str: str) -> Action:
        """Parse browser actions from a code-block formatted response.

        Extracts:
        - Browser actions from code blocks (```)
        - Agent thoughts (text before code block)
        - User messages from `send_msg_to_user()` calls

        Args:
            action_str: LLM response with code blocks.

        Returns:
            `BrowseInteractiveAction` with the extracted components.

        """
        parts = action_str.split("```")
        browser_actions, thought = self._extract_browser_actions_and_thought(parts)
        msg_content = self._extract_send_msg_to_user(browser_actions)
        return BrowseInteractiveAction(
            browser_actions=browser_actions,
            thought=thought,
            browsergym_send_msg_to_user=msg_content,
        )

    def _extract_browser_actions_and_thought(self, parts: list[str]) -> tuple[str, str]:
        if len(parts) < 2:
            segment = parts[0].strip() if parts else ""
            return segment, ""
        code_block = parts[1].strip()
        if code_block:
            return code_block, parts[0].strip()
        return parts[0].strip(), ""

    def _extract_send_msg_to_user(self, browser_actions: str) -> str:
        message = ""
        for sub_action in browser_actions.splitlines():
            if "send_msg_to_user(" not in sub_action:
                continue
            parsed = self._message_from_ast(sub_action)
            if parsed is not None:
                message = parsed
                continue
            parsed = self._message_from_regex(sub_action)
            message = parsed or ""
        return message

    def _message_from_ast(self, sub_action: str) -> str | None:
        try:
            tree = ast.parse(sub_action)
        except SyntaxError:
            logger.error("Error parsing action: %s", sub_action)
            return None

        stmt = tree.body[0] if tree.body else None
        call_node = stmt.value if isinstance(stmt, ast.Expr) else None
        first_arg = (
            call_node.args[0]
            if isinstance(call_node, ast.Call) and call_node.args
            else None
        )
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            return first_arg.value
        return None

    def _message_from_regex(self, sub_action: str) -> str | None:
        if match := re.search(r"send_msg_to_user\(([\"'])(.*?)\1\)", sub_action):
            return match[2]
        return None
