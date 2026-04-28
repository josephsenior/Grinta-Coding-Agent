"""Handles action retrieval and execution steps for SessionOrchestrator."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

from backend.core.constants import (
    DEFAULT_AGENT_APPLY_PATCH_MAX_RETRIES,
    DEFAULT_AGENT_MAX_CONSECUTIVE_NULL_ACTIONS,
    DEFAULT_AGENT_MAX_IDENTICAL_RETRIES,
    DEFAULT_AGENT_MAX_NULL_RECOVERY_ROUNDS,
    DEFAULT_AGENT_MAX_REPAIR_ATTEMPTS,
)
from backend.core.errors import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
    LLMContextWindowExceedError,
    LLMMalformedActionError,
    LLMNoActionError,
    LLMResponseError,
)
from backend.core.logger import app_logger as logger
from backend.engine.common import (
    FunctionCallNotExistsError as CommonFunctionCallNotExistsError,
)
from backend.engine.common import (
    FunctionCallValidationError as CommonFunctionCallValidationError,
)
from backend.inference.exceptions import (
    BadRequestError,
    ContextWindowExceededError,
    OpenAIError,
    Timeout,
    is_context_window_error,
)
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    LspQueryAction,
    MCPAction,
    NullAction,
    PlaybookFinishAction,
    RecallAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.action.agent import CondensationRequestAction
from backend.ledger.action.empty import NullActionReason
from backend.ledger.observation import ErrorObservation
from backend.orchestration.agent_circuit_breaker import (
    classify_text_editor_error_bucket,
)

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )
    from backend.orchestration.tool_pipeline import (
        ToolInvocationContext,
        ToolInvocationPipeline,
    )


# Substrings that appear in ``BadRequestError`` messages when the API
# rejects our request body because the tool-call ``arguments`` string isn't
# valid JSON. We treat these as recoverable so the agent isn't killed by a
# single malformed LLM emission; the ``_convert_tool_calls`` safety net in
# ``backend/context/action_processors.py`` repairs on the next build.
_MALFORMED_JSON_MARKERS: tuple[str, ...] = (
    'invalid \\escape',
    'invalid escape',
    'expecting property name',
    'expecting value',
    'unterminated string',
    'control character',
    'json parse error',
    'invalid json',
)

_VERIFICATION_REQUIRED_KEY = '__step_guard_verification_required'
_GROUNDING_MCP_TOOL_NAMES = frozenset(
    {
        'copilot_getnotebooksummary',
        'execution_subagent',
        'fetch_webpage',
        'file_search',
        'get_changed_files',
        'get_errors',
        'get_terminal_output',
        'github_repo',
        'github_text_search',
        'grep_search',
        'read_file',
        'read_notebook_cell_output',
        'run_in_terminal',
        'run_task',
        'semantic_search',
        'view_image',
        'vscode_listcodeusages',
    }
)
_MUTATING_MCP_TOOL_NAMES = frozenset(
    {
        'apply_patch',
        'create_directory',
        'create_file',
        'create_new_jupyter_notebook',
        'create_new_workspace',
        'edit_notebook_file',
        'memory.create',
        'memory.delete',
        'memory.insert',
        'memory.rename',
        'memory.str_replace',
        'vscode_renamesymbol',
    }
)


def _looks_like_bad_json_request(exc: Exception, error_str_lower: str) -> bool:
    """Return ``True`` when ``exc`` is a BadRequestError caused by malformed JSON."""
    if not isinstance(exc, BadRequestError):
        return False
    return any(marker in error_str_lower for marker in _MALFORMED_JSON_MARKERS)


def _resolve_operation_pipeline(
    context: object,
) -> ToolInvocationPipeline | None:
    from backend.orchestration.tool_pipeline import ToolInvocationPipeline

    def _is_pipeline_like(value: object) -> bool:
        return callable(getattr(value, 'create_context', None))

    raw_context_dict = getattr(context, '__dict__', None)
    context_dict = raw_context_dict if isinstance(raw_context_dict, dict) else {}
    pipeline = context_dict.get('operation_pipeline')
    if _is_pipeline_like(pipeline):
        return cast(ToolInvocationPipeline, pipeline)
    if pipeline is None and not isinstance(context, Mock):
        candidate = getattr(context, 'operation_pipeline', None)
        if _is_pipeline_like(candidate):
            return cast(ToolInvocationPipeline, candidate)
    pipeline = context_dict.get('tool_pipeline')
    if _is_pipeline_like(pipeline):
        return cast(ToolInvocationPipeline, pipeline)
    candidate = getattr(context, 'tool_pipeline', None)
    if _is_pipeline_like(candidate):
        return cast(ToolInvocationPipeline, candidate)
    return None


def _resolve_llm_step_timeout_seconds(agent: object) -> float | None:
    """Per-LLM-step cap for ``astep`` only.

    ``None`` means no ``asyncio.wait_for`` limit (model may stream as long as needed).
    Set ``agent.config.llm_step_timeout_seconds`` to a positive number, or
    ``APP_LLM_STEP_TIMEOUT_SECONDS`` to a positive value, to enforce a cap.
    Zero, negative, or empty/unset env leaves the step uncapped.
    """
    from backend.core.llm_step_timeout import llm_step_timeout_seconds_from_env

    cfg = getattr(agent, 'config', None)
    if cfg is not None:
        v = getattr(cfg, 'llm_step_timeout_seconds', None)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f = float(v)
            return None if f <= 0 else f
    return llm_step_timeout_seconds_from_env()


class ActionExecutionService:
    """Encapsulates action acquisition, planning, and execution orchestration."""

    # Centralized in backend.core.constants — see DEFAULT_AGENT_* knobs.
    _MAX_CONSECUTIVE_NULL_ACTIONS = DEFAULT_AGENT_MAX_CONSECUTIVE_NULL_ACTIONS
    _MAX_NULL_RECOVERY_ROUNDS = DEFAULT_AGENT_MAX_NULL_RECOVERY_ROUNDS
    _MAX_REPAIR_ATTEMPTS = DEFAULT_AGENT_MAX_REPAIR_ATTEMPTS
    _MAX_IDENTICAL_RETRIES = DEFAULT_AGENT_MAX_IDENTICAL_RETRIES
    _APPLY_PATCH_MAX_RETRIES = DEFAULT_AGENT_APPLY_PATCH_MAX_RETRIES

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context
        self._consecutive_null_actions = 0
        self._null_recovery_rounds = 0

    def _publish_agent_event(self, event: object) -> None:
        event_stream = self._context.event_stream
        if event_stream is None:
            logger.warning(
                'ActionExecutionService could not publish %s because event_stream is unavailable',
                type(event).__name__,
            )
            return
        event_stream.add_event(event, EventSource.AGENT)

    @staticmethod
    def _agent_name(agent: object) -> str:
        return str(getattr(agent, 'name', agent.__class__.__name__))

    @staticmethod
    def _agent_model_name(agent: object) -> object | None:
        llm = getattr(agent, 'llm', None)
        llm_config = getattr(llm, 'config', None) if llm is not None else None
        return getattr(llm_config, 'model', None)

    def _should_use_confirmation_replay(self, controller: object) -> bool:
        confirmation = self._context.confirmation_service
        replay_mgr = getattr(controller, '_replay_manager', None)
        return (
            confirmation is not None
            and replay_mgr is not None
            and replay_mgr.should_replay() is True
        )

    def _get_confirmation_action(self) -> Action | None:
        confirmation = self._context.confirmation_service
        get_next_action = (
            getattr(confirmation, 'get_next_action', None)
            if confirmation is not None
            else None
        )
        if callable(get_next_action):
            return cast(Callable[[], Action], get_next_action)()
        logger.error(
            'ActionExecutionService.get_next_action: confirmation replay '
            'was requested but ConfirmationService.get_next_action is unavailable'
        )
        return None

    async def _get_agent_step_action(self, attempt: int) -> Action | None:
        agent = cast(object | None, self._context.agent)
        if agent is None:
            logger.error(
                'ActionExecutionService.get_next_action: context agent is unavailable'
            )
            return None

        astep = getattr(agent, 'astep', None)
        if callable(astep) and inspect.iscoroutinefunction(astep):
            async_step = cast(Callable[[object], Awaitable[Action]], astep)
            return await self._run_async_step(agent, async_step, attempt)

        step = getattr(agent, 'step', None)
        if not callable(step):
            logger.error(
                'ActionExecutionService.get_next_action: agent=%s has no callable step()',
                self._agent_name(agent),
            )
            return None
        return cast(Callable[[object], Action], step)(self._context.state)

    async def _run_async_step(
        self,
        agent: object,
        async_step: Callable[[object], Awaitable[Action]],
        attempt: int,
    ) -> Action:
        logger.info(
            'ActionExecutionService.get_next_action: invoking astep '
            'for agent=%s (attempt=%d)',
            self._agent_name(agent),
            attempt,
        )
        timeout = _resolve_llm_step_timeout_seconds(agent)
        if timeout is None:
            return await async_step(self._context.state)
        return await self._run_async_step_with_timeout(agent, async_step, timeout)

    async def _run_async_step_with_timeout(
        self,
        agent: object,
        async_step: Callable[[object], Awaitable[Action]],
        timeout: float,
    ) -> Action:
        import asyncio as _asyncio

        result: Action | None = None
        for _timeout_attempt in range(2):
            try:
                result = await _asyncio.wait_for(
                    async_step(self._context.state),
                    timeout=timeout,
                )
                break  # success
            except _asyncio.TimeoutError as exc:
                if _timeout_attempt == 0:
                    logger.warning(
                        'ActionExecutionService.get_next_action: '
                        'astep timed out after %s seconds, retrying once',
                        timeout,
                    )
                    continue
                model_name = self._agent_model_name(agent)
                logger.error(
                    'ActionExecutionService.get_next_action: astep timed out '
                    'after %s seconds for model=%s (after retry)',
                    timeout,
                    model_name,
                )
                raise Timeout(
                    f'LLM step timed out after {timeout} seconds',
                    model=model_name,
                ) from exc

        if result is None:
            raise RuntimeError('unreachable async-step timeout state')
        return result

    async def _acquire_next_action(self, attempt: int) -> tuple[Action | None, bool]:
        controller = self._context.get_controller()
        use_confirmation_replay = self._should_use_confirmation_replay(controller)
        if use_confirmation_replay:
            return self._get_confirmation_action(), True
        return await self._get_agent_step_action(attempt), False

    def _log_missing_action(self, attempt: int) -> None:
        logger.error(
            'ActionExecutionService.get_next_action: agent produced no action object '
            'on attempt=%d',
            attempt,
        )

    def _log_obtained_action(self, action: Action) -> None:
        agent = self._context.agent
        logger.info(
            'ActionExecutionService.get_next_action: obtained action=%s '
            'from agent=%s',
            getattr(action, 'action', type(action).__name__),
            self._agent_name(agent),
        )

    async def _finalize_acquired_action(
        self,
        action: Action | None,
        *,
        attempt: int,
        use_confirmation_replay: bool,
    ) -> Action | None:
        if action is None:
            self._log_missing_action(attempt)
            return None

        action.source = EventSource.AGENT
        self._log_obtained_action(action)
        if use_confirmation_replay:
            return action
        if isinstance(action, NullAction):
            return await self._handle_consecutive_null_action(action)
        self._reset_consecutive_null_actions()
        return action

    @staticmethod
    def _next_error_retry_state(
        exc: Exception,
        last_error_signature: str,
        identical_error_count: int,
    ) -> tuple[str, int]:
        error_signature = f'{type(exc).__name__}:{str(exc).strip()}'
        if error_signature == last_error_signature:
            return error_signature, identical_error_count + 1
        return error_signature, 1

    @staticmethod
    def _format_repair_error_message(exc: Exception) -> str:
        if isinstance(
            exc,
            (FunctionCallValidationError, CommonFunctionCallValidationError),
        ):
            return (
                f'Tool validation failed: {exc}\n'
                'Please correct the tool arguments and try again.'
            )
        if isinstance(
            exc,
            (FunctionCallNotExistsError, CommonFunctionCallNotExistsError),
        ):
            return (
                f'Tool not found: {exc}\n'
                'Please use an existing tool from the provided list.'
            )
        return str(exc)

    def _publish_repair_error_observation(
        self,
        exc: Exception,
        error_logged: bool,
    ) -> bool:
        if error_logged:
            return True
        self._publish_agent_event(
            ErrorObservation(content=self._format_repair_error_message(exc))
        )
        return True

    def _record_repair_error_for_circuit_breaker(
        self,
        controller: object,
        exc: Exception,
        error_signature: str,
    ) -> None:
        cb_service = getattr(controller, 'circuit_breaker_service', None)
        if cb_service is None:
            return
        error_lower = error_signature.lower()
        if 'text_editor' in error_lower or '[text_editor' in error_lower:
            bucket = classify_text_editor_error_bucket(str(exc))
            cb_service.record_error(exc, tool_name=bucket)

    def _effective_retry_limit(
        self,
        error_signature: str,
        max_identical_retries: int,
    ) -> int:
        if (
            '[APPLY_PATCH_CLASS:malformed_patch]' in error_signature
            or '[APPLY_PATCH_CLASS:context_mismatch]' in error_signature
        ):
            return self._APPLY_PATCH_MAX_RETRIES
        return max_identical_retries

    @staticmethod
    async def _yield_for_repair_retry() -> None:
        import asyncio

        await asyncio.sleep(0.01)

    @staticmethod
    async def _set_controller_error_if_running(controller: object) -> None:
        from backend.core.schemas import AgentState as _AgentState

        if controller.get_agent_state() == _AgentState.RUNNING:
            await controller.set_agent_state_to(_AgentState.ERROR)

    async def _handle_repairable_action_error(
        self,
        exc: Exception,
        *,
        attempt: int,
        max_repair_attempts: int,
        max_identical_retries: int,
        error_logged: bool,
        last_error_signature: str,
        identical_error_count: int,
    ) -> tuple[bool, bool, str, int]:
        self._reset_consecutive_null_actions()
        error_signature, identical_error_count = self._next_error_retry_state(
            exc,
            last_error_signature,
            identical_error_count,
        )
        error_logged = self._publish_repair_error_observation(exc, error_logged)

        controller = self._context.get_controller()
        self._record_repair_error_for_circuit_breaker(
            controller,
            exc,
            error_signature,
        )

        effective_max_retries = self._effective_retry_limit(
            error_signature,
            max_identical_retries,
        )
        if identical_error_count > effective_max_retries:
            logger.error(
                'get_next_action blocked repeated identical recoverable error after %d attempts: %s',
                identical_error_count,
                error_signature,
            )
            await self._set_controller_error_if_running(controller)
            return False, error_logged, error_signature, identical_error_count

        if attempt < max_repair_attempts:
            await self._yield_for_repair_retry()
            return True, error_logged, error_signature, identical_error_count

        logger.error(
            'get_next_action exhausted %d repair attempts; transitioning to ERROR state',
            max_repair_attempts,
        )
        await self._set_controller_error_if_running(controller)
        return False, error_logged, error_signature, identical_error_count

    async def get_next_action(self) -> Action | None:
        """Get the next action from the agent, with automatic repair for validation errors."""
        max_repair_attempts = self._MAX_REPAIR_ATTEMPTS
        max_identical_retries = self._MAX_IDENTICAL_RETRIES

        error_logged = False
        last_error_signature = ''
        identical_error_count = 0
        for attempt in range(max_repair_attempts + 1):
            try:
                action, use_confirmation_replay = await self._acquire_next_action(
                    attempt
                )
                if use_confirmation_replay and action is None:
                    return None
                return await self._finalize_acquired_action(
                    action,
                    attempt=attempt,
                    use_confirmation_replay=use_confirmation_replay,
                )

            except (
                LLMMalformedActionError,
                LLMNoActionError,
                LLMResponseError,
                FunctionCallValidationError,
                FunctionCallNotExistsError,
                CommonFunctionCallValidationError,
                CommonFunctionCallNotExistsError,
            ) as exc:
                should_continue, error_logged, last_error_signature, identical_error_count = (
                    await self._handle_repairable_action_error(
                        exc,
                        attempt=attempt,
                        max_repair_attempts=max_repair_attempts,
                        max_identical_retries=max_identical_retries,
                        error_logged=error_logged,
                        last_error_signature=last_error_signature,
                        identical_error_count=identical_error_count,
                    )
                )
                if should_continue:
                    continue
                return None

            except (ContextWindowExceededError, BadRequestError, OpenAIError) as exc:
                self._reset_consecutive_null_actions()
                return await self._handle_context_window_error(exc)
            # APIConnectionError, AuthenticationError, RateLimitError, ServiceUnavailableError,
            # APIError, InternalServerError, Timeout: let propagate to caller

        return None

    async def _handle_consecutive_null_action(self, action: Action) -> Action | None:
        # Sentinel NullActions (bootstrap init, orphaned-observation pairing) are
        # legitimate no-ops and must never contribute to the consecutive-null counter.
        if getattr(action, 'reason', '') == NullActionReason.SENTINEL:
            return action

        self._consecutive_null_actions += 1
        logger.warning(
            'ActionExecutionService.get_next_action: consecutive NullAction %d/%d '
            'from agent=%s',
            self._consecutive_null_actions,
            self._MAX_CONSECUTIVE_NULL_ACTIONS,
            getattr(
                self._context.agent,
                'name',
                self._context.agent.__class__.__name__,
            ),
        )

        if self._consecutive_null_actions < self._MAX_CONSECUTIVE_NULL_ACTIONS:
            return action

        self._reset_consecutive_null_actions()
        self._null_recovery_rounds += 1

        if self._null_recovery_rounds < self._MAX_NULL_RECOVERY_ROUNDS:
            # Round 1: inject a strong directive and keep the loop running.
            # The model is confused but not fatally stuck — give it one more
            # turn with an explicit instruction rather than pausing immediately.
            logger.warning(
                'Null-action loop: recovery round %d/%d — injecting directive',
                self._null_recovery_rounds,
                self._MAX_NULL_RECOVERY_ROUNDS,
            )
            self._publish_agent_event(
                ErrorObservation(
                    content=(
                        'You have returned no executable action for several consecutive steps.\n\n'
                        'You MUST emit a concrete tool call right now. Do not describe what you '
                        'would do — actually do it. Pick the single most important next step '
                        '(e.g. run a command, read a file, write code) and execute it immediately.'
                    ),
                    error_id='NULL_ACTION_LOOP_RECOVERY',
                )
            )
            return action  # let the loop continue

        # All recovery rounds exhausted — pause for user input.
        logger.error(
            'Null-action loop: all %d recovery rounds exhausted, pausing',
            self._MAX_NULL_RECOVERY_ROUNDS,
        )
        self._null_recovery_rounds = 0
        self._publish_agent_event(
            ErrorObservation(
                content=(
                    'The model returned no executable action for multiple consecutive '
                    'steps. Pausing to avoid a no-progress loop that burns model calls.'
                ),
                error_id='NULL_ACTION_LOOP',
            )
        )

        # Set AWAITING_USER_INPUT directly on the controller instead of returning a
        # MessageAction. Returning a MessageAction caused a race: the runtime would
        # process the action, emit a NullObservation, and trigger_post_resolution_step
        # would resume the loop before the event router could set AWAITING_USER_INPUT.
        from backend.core.schemas import AgentState as _AgentState

        controller = self._context.get_controller()
        if controller.get_agent_state() == _AgentState.RUNNING:
            await controller.set_agent_state_to(_AgentState.AWAITING_USER_INPUT)
        return None

    def _reset_consecutive_null_actions(self) -> None:
        self._consecutive_null_actions = 0

    def _reset_null_recovery_rounds(self) -> None:
        self._null_recovery_rounds = 0

    def _get_verification_requirement(self) -> dict[str, object] | None:
        state = getattr(self._context, 'state', None)
        if state is None:
            return None
        extra_value = getattr(state, 'extra_data', None)
        if not isinstance(extra_value, dict):
            return None
        extra = cast(dict[str, object], extra_value)
        requirement = extra.get(_VERIFICATION_REQUIRED_KEY)
        if isinstance(requirement, dict) and requirement:
            return cast(dict[str, object], requirement)
        return None

    def _clear_verification_requirement(self) -> None:
        state = getattr(self._context, 'state', None)
        if state is None:
            return
        extra_value = getattr(state, 'extra_data', None)
        if not isinstance(extra_value, dict):
            state.extra_data = {}
            extra = cast(dict[str, object], state.extra_data)
        else:
            extra = cast(dict[str, object], extra_value)
        extra[_VERIFICATION_REQUIRED_KEY] = None
        if hasattr(state, 'set_extra'):
            state.set_extra(
                _VERIFICATION_REQUIRED_KEY,
                None,
                source='ActionExecutionService',
            )

    def _set_verification_requirement(self, requirement: dict[str, object]) -> None:
        state = getattr(self._context, 'state', None)
        if state is None:
            return
        extra_value = getattr(state, 'extra_data', None)
        if not isinstance(extra_value, dict):
            state.extra_data = {}
            extra = cast(dict[str, object], state.extra_data)
        else:
            extra = cast(dict[str, object], extra_value)
        extra[_VERIFICATION_REQUIRED_KEY] = requirement
        if hasattr(state, 'set_extra'):
            state.set_extra(
                _VERIFICATION_REQUIRED_KEY,
                requirement,
                source='ActionExecutionService',
            )

    @staticmethod
    def _normalize_mcp_tool_name(action: MCPAction) -> str:
        name = str(getattr(action, 'name', '') or '').strip().lower()
        arguments_value = getattr(action, 'arguments', None)
        arguments = (
            cast(dict[str, object], arguments_value)
            if isinstance(arguments_value, dict)
            else {}
        )

        if name in {'call_mcp_tool', 'execute_mcp_tool'}:
            inner = arguments.get('tool_name') or arguments.get('name')
            if isinstance(inner, str) and inner.strip():
                name = inner.strip().lower()

        if name == 'memory':
            command = arguments.get('command')
            if isinstance(command, str) and command.strip():
                return f'memory.{command.strip().lower()}'

        return name

    def _action_satisfies_verification_requirement(self, action: Action) -> bool:
        if isinstance(action, (CmdRunAction, FileReadAction, LspQueryAction)):
            return True
        if isinstance(action, (RecallAction, TerminalReadAction, TerminalRunAction)):
            return True
        if isinstance(action, FileEditAction):
            command = str(getattr(action, 'command', '') or '').strip().lower()
            return command == 'read_file'
        if isinstance(action, MCPAction):
            return self._normalize_mcp_tool_name(action) in _GROUNDING_MCP_TOOL_NAMES
        return False

    def _action_blocked_by_verification_requirement(self, action: Action) -> bool:
        if isinstance(action, (FileWriteAction, PlaybookFinishAction)):
            return True
        if isinstance(action, FileEditAction):
            command = str(getattr(action, 'command', '') or '').strip().lower()
            return command != 'read_file'
        if isinstance(action, MCPAction):
            return self._normalize_mcp_tool_name(action) in _MUTATING_MCP_TOOL_NAMES
        return False

    def _format_verification_required_content(
        self, requirement: dict[str, object]
    ) -> str:
        raw_paths_value = requirement.get('paths')
        raw_paths: list[object] = raw_paths_value if isinstance(raw_paths_value, list) else []
        paths = ', '.join(
            str(path_value) for path_value in raw_paths if str(path_value).strip()
        )
        failure = str(
            requirement.get('observed_failure')
            or 'Recent failing feedback still contradicts the last edit attempt.'
        ).strip()
        lines = [
            'VERIFICATION REQUIRED BEFORE CONTINUING',
            '',
            'Recent edits were followed by failing feedback, so blind retries are blocked for one grounding step.',
        ]
        if paths:
            lines.append(f'Files to reconcile: {paths}')
        if failure:
            lines.append(f'Latest failing feedback: {failure}')
        lines.extend(
            [
                'Allowed next moves: read the affected file, inspect terminal output, or rerun a focused check.',
                'After one fresh grounding action, edits and finish are allowed again.',
            ]
        )
        return '\n'.join(lines)

    def _proactive_churn_check(self, action: Action) -> dict[str, object] | None:
        """Proactively scan history for edit+failure churn even before stuck detection fires.

        Returns a verification requirement dict if the pattern is detected,
        otherwise None.  Only called when no gate is already set.
        """
        if not self._action_blocked_by_verification_requirement(action):
            return None
        state = getattr(self._context, 'state', None)
        if state is None:
            return None
        history = getattr(state, 'history', [])
        if not history:
            return None
        try:
            from backend.orchestration.services.step_guard_service import (
                StepGuardService,
            )

            step_guard_service_cls = cast(Any, StepGuardService)
            requirement = step_guard_service_cls._build_verification_requirement_from_history(
                history
            )
            if isinstance(requirement, dict):
                return cast(dict[str, object], requirement)
            return None
        except Exception:
            return None

    def _enforce_verification_requirement(self, action: Action) -> bool:
        requirement = self._get_verification_requirement()
        if requirement is None:
            # Proactive path: check history even when stuck detection hasn't fired yet.
            requirement = self._proactive_churn_check(action)
            if requirement is not None:
                # Persist so the gate stays set until a grounding action clears it.
                self._set_verification_requirement(requirement)

        if requirement is None:
            return False

        if self._action_satisfies_verification_requirement(action):
            self._clear_verification_requirement()
            return False

        if not self._action_blocked_by_verification_requirement(action):
            return False

        from backend.ledger.event import Event as _Event
        _cause = action if getattr(action, 'id', _Event.INVALID_ID) != _Event.INVALID_ID else None
        from backend.orchestration.services.guard_bus import VERIFICATION, GuardBus
        GuardBus.emit(
            self._context,
            VERIFICATION,
            'VERIFICATION_REQUIRED',
            self._format_verification_required_content(requirement),
            'VERIFICATION REQUIRED: before more edits or finish, get one fresh file read, terminal read, or focused command result from the actual workspace state.',
            cause=_cause,
            cause_context='ActionExecutionService.verification_gate',
        )
        return True

    async def execute_action(self, action: Action) -> None:
        # Plugin hook: action_pre
        try:
            from backend.core.plugin import get_plugin_registry

            action = await get_plugin_registry().dispatch_action_pre(action)
        except Exception as exc:
            logger.warning(
                'ActionExecutionService action_pre hook failed for %s: %s',
                type(action).__name__,
                exc,
                exc_info=True,
            )

        if self._enforce_verification_requirement(action):
            return

        ctx: ToolInvocationContext | None = None
        pipeline = _resolve_operation_pipeline(self._context)
        if action.runnable and pipeline:
            ctx = pipeline.create_context(action, self._context.state)
            if ctx is not None:
                self._context.register_action_context(action, ctx)
                iteration_service = self._context.iteration_service
                if iteration_service is not None:
                    await iteration_service.apply_dynamic_iterations(ctx)
        try:
            await self._context.run_action(action, ctx)
        except Exception:
            # If run_action raises before _bind_action_context moves the entry
            # from the object-keyed dict to the event-id-keyed dict, the
            # object-keyed entry would leak until the next _reset().  Clean up
            # eagerly so there is no dangling reference.
            if ctx is not None:
                self._context.cleanup_action_context(ctx, action=action)
            raise

    async def _handle_context_window_error(self, exc: Exception) -> Action | None:
        error_str = str(exc).lower()
        if _looks_like_bad_json_request(exc, error_str):
            return self._handle_malformed_request_error(exc)
        if not is_context_window_error(error_str, exc):
            raise exc
        agent = cast(object | None, self._context.agent)
        agent_config = getattr(agent, 'config', None) if agent is not None else None
        if not getattr(agent_config, 'enable_history_truncation', False):
            raise LLMContextWindowExceedError from exc
        self._publish_agent_event(CondensationRequestAction())
        return None

    def _handle_malformed_request_error(self, exc: Exception) -> Action | None:
        r"""Recover from ``BadRequestError: Invalid \\escape``-style failures.

        The API rejected our request body because the ``tool_calls`` we
        replayed contain malformed JSON in ``function.arguments``. Fix #1
        should prevent new occurrences, but legacy ledger events may still
        carry the bug. We emit an error observation so the model sees the
        failure next turn, then return ``None`` to let the outer loop
        re-attempt (the ``_convert_tool_calls`` safety net will repair the
        arguments on the next build).
        """
        logger.warning(
            'BadRequestError with JSON-parse wording detected; treating as '
            'recoverable: %s',
            exc,
        )
        from backend.ledger.action import AgentThinkAction

        think = AgentThinkAction(
            thought=(
                '[API_REJECTED_MALFORMED_ARGS] Your previous tool call '
                'contained invalid JSON escape sequences and was rejected '
                'by the API. Emit the same call again with strict JSON: use '
                'a single backslash for newlines inside strings (not "\\\\n"), '
                'escape embedded double quotes as \\", and avoid raw control '
                'characters in string values.'
            )
        )
        think.source = EventSource.AGENT
        self._publish_agent_event(think)
        return None
