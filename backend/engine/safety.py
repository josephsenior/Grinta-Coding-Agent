from __future__ import annotations

import re
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.ledger.action import Action
    from backend.orchestration.state.state import State


# Phrases that indicate the model *claims* it performed a concrete action.
# Only matched when the response contains ZERO runnable tool calls — i.e. the
# model produced pure text instead of actually calling tools.
_ACTION_CLAIM_PATTERNS: re.Pattern[str] = re.compile(
    r"(?i)"
    r"(?:"
    # File creation / editing claims
    r"I(?:'ve| have)?\s+(?:created|written|set\s*up|configured|generated|built|made|prepared|initialized)"
    r"|(?:file|script|module|project|directory|folder|environment|package)\s+(?:has|have)\s+been\s+"
    r"(?:created|written|set\s*up|configured|generated|built|initialized)"
    r"|(?:created|wrote|set\s*up)\s+(?:the\s+)?(?:file|script|module|project|directory|folder)"
    # Installation claims
    r"|I(?:'ve| have)?\s+installed"
    r"|(?:package|dependency|dependencies|module)\s+(?:has|have)\s+been\s+installed"
    # Execution claims
    r"|I(?:'ve| have)?\s+(?:ran|run|executed)\s+(?:the\s+)?(?:command|script|test)"
    r")"
)


class OrchestratorSafetyManager:
    """Safety manager that detects hallucinated actions.

    When the model produces a text-only response (no tool calls) but the text
    claims it created files, ran commands, or installed packages, the response
    is flagged as a hallucination so the executor can re-prompt.
    """

    def __init__(self, *args, **kwargs) -> None:
        _ = (args, kwargs)
        self._consecutive_hallucinations: int = 0
        self._max_retries: int = 2

    def should_enforce_tools(
        self,
        last_user_message: str | None,
        state: State,
        default: str,
    ) -> str:
        _ = (last_user_message, state)
        return default

    def apply(
        self, response_text: str, actions: list[Action]
    ) -> tuple[bool, list[Action]]:
        """Validate actions against the response text.

        Returns ``(False, actions)`` when the model claims to have performed
        actions (file creation, installation, command execution) without
        actually invoking any tools.  The executor uses this signal to inject
        a corrective re-prompt instead of showing the hallucinated response.
        """
        if not response_text or not actions:
            return True, actions

        # If any action is runnable (FileEditAction, CmdRunAction, etc.),
        # the model DID call tools — no hallucination.
        has_tool_calls = any(getattr(a, 'runnable', False) for a in actions)
        if has_tool_calls:
            self._consecutive_hallucinations = 0
            return True, actions

        # Pure-text response — check for action-claiming language.
        if _ACTION_CLAIM_PATTERNS.search(response_text):
            self._consecutive_hallucinations += 1
            if self._consecutive_hallucinations > self._max_retries:
                # Model keeps hallucinating — let the response through so the
                # user sees it and can intervene.  Reset counter.
                logger.warning(
                    'Hallucination retry limit reached (%d); '
                    'allowing response through to user',
                    self._max_retries,
                )
                self._consecutive_hallucinations = 0
                return True, actions

            logger.warning(
                'Hallucination detected (attempt %d/%d): model claimed '
                'actions in prose without tool calls (%d chars of text)',
                self._consecutive_hallucinations,
                self._max_retries,
                len(response_text),
            )
            return False, actions

        self._consecutive_hallucinations = 0
        return True, actions
