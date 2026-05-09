"""Observation types describing recoverable agent errors."""

from dataclasses import dataclass
from typing import ClassVar

from backend.core.schemas import ObservationType
from backend.ledger.observation.observation import Observation


# Structured error categories set at the source (RecoveryService) so the UI
# never needs to guess the error type from rendered text.
ERROR_CATEGORY_RATE_LIMIT = 'rate_limit'
ERROR_CATEGORY_AUTH = 'auth'
ERROR_CATEGORY_CONTEXT_WINDOW = 'context_window'
ERROR_CATEGORY_TIMEOUT = 'timeout'
ERROR_CATEGORY_NETWORK = 'network'
ERROR_CATEGORY_MODEL_NOT_FOUND = 'model_not_found'
ERROR_CATEGORY_RUNTIME_DISCONNECTED = 'runtime_disconnected'


@dataclass
class ErrorObservation(Observation):
    """This data class represents an error encountered by the agent.

    This is the type of error that LLM can recover from.
    E.g., Linter error after editing a file.

    ``notify_ui_only`` marks **user-facing LLM/provider/config** failures (bad API key,
    quota, provider outage messaging, etc.): the client shows a toast, hides the card
    from the transcript, and memory omits the observation from model context.

    Leave ``notify_ui_only`` false for **capability / tool** outcomes (MCP unreachable,
    command failed, file errors, etc.) so the agent still sees actionable feedback.

    ``agent_only`` marks **internal system feedback** that is only intended for the
    agent (e.g. "FINISH BLOCKED" task-tracker messages): the observation is kept in
    model context but is NOT rendered in the user-facing transcript.

    ``error_category`` is a structured tag set by the backend at the point where the
    exception type is known (RecoveryService).  The UI uses this instead of text
    matching to decide styling and guidance.  Use the ``ERROR_CATEGORY_*`` constants.
    """

    error_id: str = ''
    notify_ui_only: bool = False
    agent_only: bool = False
    timeout_kind: str | None = None
    error_category: str | None = None
    observation: ClassVar[str] = ObservationType.ERROR

    @property
    def message(self) -> str:
        """Get error message content."""
        return self.content

    def __str__(self) -> str:
        """Return a readable summary of the error message."""
        base = f'**ErrorObservation**\n{self.content}'
        if self.timeout_kind:
            return f'{base}\n[timeout_kind={self.timeout_kind}]'
        return base
