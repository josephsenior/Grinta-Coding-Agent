"""Exception classification and handling for SessionOrchestrator.

Centralizes the exception → reported-error transformation logic so that
`SessionOrchestrator._step_with_exception_handling` stays focused on orchestration.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

from backend.core.errors import AgentRuntimeError, LLMContextWindowExceedError
from backend.core.logger import app_logger as logger
from backend.inference.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

if TYPE_CHECKING:
    from backend.orchestration.session_orchestrator import SessionOrchestrator

# Exceptions that are forwarded to recovery as-is (known LLM errors)
_PASSTHROUGH_EXCEPTIONS = (
    AgentRuntimeError,
    Timeout,
    APIError,
    APIConnectionError,
    BadRequestError,
    NotFoundError,
    InternalServerError,
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    LLMContextWindowExceedError,
)


class ExceptionHandlerService:
    """Classifies step exceptions and delegates to recovery."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self._ctrl = controller

    async def handle_step_exception(self, exc: Exception) -> None:
        """Classify *exc* and pass it through recovery.

        Known LLM exceptions are forwarded verbatim; anything else is
        wrapped in a user-friendly RuntimeError.
        """
        self._ctrl.log(
            'error',
            'Error while running the agent (session %s): %s',
            extra={'exception_type': type(exc).__name__},
        )
        logger.error(
            'Agent step exception traceback (session %s): %s',
            self._ctrl.id,
            traceback.format_exc(),
        )

        reported: Exception
        if isinstance(exc, _PASSTHROUGH_EXCEPTIONS):
            reported = exc
        else:
            reported = RuntimeError(
                f'There was an unexpected error while running the agent: '
                f'{exc.__class__.__name__}. You can refresh the page or '
                f'ask the agent to try again.',
            )

        await self._ctrl.recovery_service.react_to_exception(reported)
