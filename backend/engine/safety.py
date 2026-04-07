from __future__ import annotations

import re
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.ledger.action.message import MessageAction

if TYPE_CHECKING:
    from backend.ledger.action import Action
    from backend.orchestration.state.state import State


# Intentionally conservative: this guard only fires on explicit claims of
# externally verifiable side effects. It should prefer false negatives over
# false positives so conversational responses are never trapped in retry loops.
_FILELIKE_TARGET = (
    r'(?:[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)*\.'
    r'(?:py|js|ts|tsx|jsx|json|ya?ml|toml|ini|cfg|conf|md|txt|html|css|scss|sql|sh|ps1|psm1|psd1|env))'
)
_SIDE_EFFECT_OBJECTS = (
    r'(?:file|script|module|project|directory|folder|environment|package|dependency|dependencies|'
    r'config(?:uration)?|server|endpoint|branch|commit|migration|test(?:\s+suite)?|tests)'
)
_INSTALL_OBJECTS = r'(?:package|dependency|dependencies|module|library)'
_EXECUTION_OBJECTS = r'(?:command|script|test(?:\s+suite)?|tests|migration|server)'
_SIDE_EFFECT_VERBS = (
    r'(?:created|wrote|written|edited|updated|configured|generated|initialized|deleted|removed|set\s*up)'
)

# Phrases that indicate the model *claims* it performed a concrete side effect.
# Only matched when the response contains plain message actions and no structured
# tool-derived actions.
_ACTION_CLAIM_PATTERNS: re.Pattern[str] = re.compile(
    rf"""
    \b(?:
        I(?:'ve|\s+have)?\s+{_SIDE_EFFECT_VERBS}\s+
        (?:(?:a|an|the|this|that|these|those|new)\s+)?
        (?:{_SIDE_EFFECT_OBJECTS}|(?:file\s+)?{_FILELIKE_TARGET})
        |
        (?:the\s+)?(?:{_SIDE_EFFECT_OBJECTS}|(?:file\s+)?{_FILELIKE_TARGET})\s+
        (?:has|have)\s+been\s+
        (?:created|written|edited|updated|configured|generated|initialized|deleted|removed|set\s*up)
        |
        I(?:'ve|\s+have)?\s+installed\s+
        (?:(?:a|an|the|this|that|these|those|new)\s+)?{_INSTALL_OBJECTS}
        |
        (?:the\s+)?{_INSTALL_OBJECTS}\s+(?:has|have)\s+been\s+installed
        |
        I(?:'ve|\s+have)?\s+(?:ran|run|executed)\s+
        (?:(?:a|an|the|this|that|these|those)\s+)?{_EXECUTION_OBJECTS}
        |
        (?:the\s+)?{_EXECUTION_OBJECTS}\s+(?:has|have)\s+been\s+(?:run|executed)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
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

        # Any structured action means the model used function calling or an
        # explicit orchestration action, even if the action itself is not
        # runnable. Only plain message-only replies are eligible for this guard.
        if not self._is_plain_message_only(actions):
            self._consecutive_hallucinations = 0
            return True, actions

        # Plain-message response — check only for high-confidence side-effect claims.
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

    @staticmethod
    def _is_plain_message_only(actions: list[Action]) -> bool:
        """Return True when all actions are plain assistant messages.

        Structured actions from tool/function calling should bypass the
        hallucination detector, even if they are not runnable.
        """
        return all(isinstance(action, MessageAction) for action in actions)
