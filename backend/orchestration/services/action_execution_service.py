"""Handles action retrieval and execution steps for SessionOrchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

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
from backend.ledger.observation import ErrorObservation
from backend.orchestration.agent_circuit_breaker import (
    classify_text_editor_error_bucket,
)

if TYPE_CHECKING:
    from backend.ledger.action import Action
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )
    from backend.orchestration.tool_pipeline import ToolInvocationContext


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


def _resolve_operation_pipeline(context):
    context_dict = getattr(context, '__dict__', {})
    pipeline = context_dict.get('operation_pipeline')
    if pipeline is None and not isinstance(context, Mock):
        pipeline = getattr(context, 'operation_pipeline', None)
    if pipeline is not None:
        return pipeline
    pipeline = context_dict.get('tool_pipeline')
    if pipeline is not None:
        return pipeline
    return getattr(context, 'tool_pipeline', None)


def _resolve_llm_step_timeout_seconds(agent) -> float | None:
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

    _MAX_CONSECUTIVE_NULL_ACTIONS = 5
    # How many full rounds of null-action recovery to attempt before pausing.
    # Round 1: inject a directive and keep going.
    # Round 2+: pause for user input (model is truly stuck).
    _MAX_NULL_RECOVERY_ROUNDS = 2

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context
        self._consecutive_null_actions = 0
        self._null_recovery_rounds = 0

    async def get_next_action(self) -> Action | None:
        """Get the next action from the agent, with automatic repair for validation errors."""
        max_repair_attempts = 3
        max_identical_retries = 2

        error_logged = False
        last_error_signature = ''
        identical_error_count = 0
        for attempt in range(max_repair_attempts + 1):
            try:
                confirmation = self._context.confirmation_service
                controller = self._context.get_controller()
                replay_mgr = getattr(controller, '_replay_manager', None)
                # ConfirmationService.get_next_action() uses synchronous agent.step()
                # for live runs, which disables real token streaming (astep/async_execute).
                # Only delegate there during trajectory replay; otherwise prefer astep.
                use_confirmation_replay = (
                    confirmation is not None
                    and replay_mgr is not None
                    and replay_mgr.should_replay() is True
                )
                if use_confirmation_replay:
                    action = confirmation.get_next_action()
                else:
                    # Prefer the async step path (real LLM streaming) when
                    # available; fall back to synchronous step() otherwise.
                    import asyncio as _asyncio

                    agent = self._context.agent
                    astep = getattr(agent, 'astep', None)
                    if astep is not None and _asyncio.iscoroutinefunction(astep):
                        logger.info(
                            'ActionExecutionService.get_next_action: invoking astep '
                            'for agent=%s (attempt=%d)',
                            getattr(agent, 'name', agent.__class__.__name__),
                            attempt,
                        )
                        timeout = _resolve_llm_step_timeout_seconds(agent)
                        if timeout is None:
                            action = await astep(self._context.state)
                        else:
                            # Retry once on timeout before propagating
                            for _timeout_attempt in range(2):
                                try:
                                    action = await _asyncio.wait_for(
                                        astep(self._context.state),
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
                                    model_name = None
                                    try:
                                        llm = getattr(agent, 'llm', None)
                                        model_name = getattr(
                                            getattr(llm, 'config', None), 'model', None
                                        )
                                    except Exception:
                                        pass
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
                    else:
                        action = agent.step(self._context.state)
                action.source = EventSource.AGENT

                logger.info(
                    'ActionExecutionService.get_next_action: obtained action=%s '
                    'from agent=%s',
                    getattr(action, 'action', type(action).__name__),
                    getattr(
                        self._context.agent,
                        'name',
                        self._context.agent.__class__.__name__,
                    ),
                )
                if use_confirmation_replay:
                    return action
                if isinstance(action, NullAction):
                    return await self._handle_consecutive_null_action(action)
                self._reset_consecutive_null_actions()
                self._reset_null_recovery_rounds()
                return action

            except (
                LLMMalformedActionError,
                LLMNoActionError,
                LLMResponseError,
                FunctionCallValidationError,
                FunctionCallNotExistsError,
                CommonFunctionCallValidationError,
                CommonFunctionCallNotExistsError,
            ) as exc:
                self._reset_consecutive_null_actions()
                error_signature = f'{type(exc).__name__}:{str(exc).strip()}'
                if error_signature == last_error_signature:
                    identical_error_count += 1
                else:
                    last_error_signature = error_signature
                    identical_error_count = 1

                # Create detailed error observation
                error_msg = str(exc)
                if isinstance(
                    exc,
                    (FunctionCallValidationError, CommonFunctionCallValidationError),
                ):
                    error_msg = f'Tool validation failed: {exc}\nPlease correct the tool arguments and try again.'
                if isinstance(
                    exc,
                    (FunctionCallNotExistsError, CommonFunctionCallNotExistsError),
                ):
                    error_msg = f'Tool not found: {exc}\nPlease use an existing tool from the provided list.'

                obs = ErrorObservation(content=error_msg)
                if not error_logged:
                    # Add to event stream so it's recorded in history
                    self._context.event_stream.add_event(obs, EventSource.AGENT)
                    error_logged = True

                controller = self._context.get_controller()
                cb_service = getattr(controller, 'circuit_breaker_service', None)
                if cb_service is not None:
                    error_lower = error_signature.lower()
                    if (
                        'text_editor' in error_lower
                        or '[text_editor' in error_lower
                    ):
                        bucket = classify_text_editor_error_bucket(str(exc))
                        cb_service.record_error(exc, tool_name=bucket)

                effective_max_retries = max_identical_retries
                if (
                    '[APPLY_PATCH_CLASS:malformed_patch]' in error_signature
                    or '[APPLY_PATCH_CLASS:context_mismatch]' in error_signature
                ):
                    effective_max_retries = 1

                if identical_error_count > effective_max_retries:
                    logger.error(
                        'get_next_action blocked repeated identical recoverable error after %d attempts: %s',
                        identical_error_count,
                        error_signature,
                    )
                    from backend.core.schemas import AgentState as _AgentState

                    if controller.get_agent_state() == _AgentState.RUNNING:
                        await controller.set_agent_state_to(_AgentState.ERROR)
                    return None

                # If we have retries left, continue loop to let agent see error and try again
                if attempt < max_repair_attempts:
                    # We need to ensure the state is updated with this new observation
                    # before the next step. The state tracker updates via event subscription,
                    # but we can also manually ensure it's in the current view if needed.
                    # Typically, event_stream.add_event triggers the subscribers.
                    # We yield control briefly to allow state update to propagate if async.
                    import asyncio

                    await asyncio.sleep(0.01)
                    continue

                # If out of retries, transition to ERROR so the agent doesn't
                # stay stuck in RUNNING state indefinitely.
                from backend.core.schemas import AgentState as _AgentState

                controller = self._context.get_controller()
                if controller.get_agent_state() == _AgentState.RUNNING:
                    logger.error(
                        'get_next_action exhausted %d repair attempts; '
                        'transitioning to ERROR state',
                        max_repair_attempts,
                    )
                    await controller.set_agent_state_to(_AgentState.ERROR)
                return None

            except (ContextWindowExceededError, BadRequestError, OpenAIError) as exc:
                self._reset_consecutive_null_actions()
                return await self._handle_context_window_error(exc)
            # APIConnectionError, AuthenticationError, RateLimitError, ServiceUnavailableError,
            # APIError, InternalServerError, Timeout: let propagate to caller

        return None

    async def _handle_consecutive_null_action(self, action: Action) -> Action | None:
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
            self._context.event_stream.add_event(
                ErrorObservation(
                    content=(
                        'You have returned no executable action for several consecutive steps.\n\n'
                        'You MUST emit a concrete tool call right now. Do not describe what you '
                        'would do — actually do it. Pick the single most important next step '
                        '(e.g. run a command, read a file, write code) and execute it immediately.'
                    ),
                    error_id='NULL_ACTION_LOOP_RECOVERY',
                ),
                EventSource.AGENT,
            )
            return action  # let the loop continue

        # All recovery rounds exhausted — pause for user input.
        logger.error(
            'Null-action loop: all %d recovery rounds exhausted, pausing',
            self._MAX_NULL_RECOVERY_ROUNDS,
        )
        self._null_recovery_rounds = 0
        self._context.event_stream.add_event(
            ErrorObservation(
                content=(
                    'The model returned no executable action for multiple consecutive '
                    'steps. Pausing to avoid a no-progress loop that burns model calls.'
                ),
                error_id='NULL_ACTION_LOOP',
            ),
            EventSource.AGENT,
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
        extra = getattr(state, 'extra_data', None)
        if not isinstance(extra, dict):
            return None
        requirement = extra.get(_VERIFICATION_REQUIRED_KEY)
        if isinstance(requirement, dict) and requirement:
            return requirement
        return None

    def _clear_verification_requirement(self) -> None:
        state = getattr(self._context, 'state', None)
        if state is None:
            return
        extra = getattr(state, 'extra_data', None)
        if not isinstance(extra, dict):
            state.extra_data = {}
            extra = state.extra_data
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
        extra = getattr(state, 'extra_data', None)
        if not isinstance(extra, dict):
            state.extra_data = {}
            extra = state.extra_data
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
        arguments = getattr(action, 'arguments', None)
        if not isinstance(arguments, dict):
            arguments = {}

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
        raw_paths = requirement.get('paths') or []
        if isinstance(raw_paths, list):
            paths = ', '.join(str(path) for path in raw_paths if str(path).strip())
        else:
            paths = ''
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

            return StepGuardService._build_verification_requirement_from_history(history)
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
                await self._context.iteration_service.apply_dynamic_iterations(ctx)
        await self._context.run_action(action, ctx)

    async def _handle_context_window_error(self, exc: Exception) -> Action | None:
        error_str = str(exc).lower()
        if _looks_like_bad_json_request(exc, error_str):
            return self._handle_malformed_request_error(exc)
        if not is_context_window_error(error_str, exc):
            raise exc
        if not self._context.agent.config.enable_history_truncation:
            raise LLMContextWindowExceedError from exc
        self._context.event_stream.add_event(
            CondensationRequestAction(), EventSource.AGENT
        )
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
        self._context.event_stream.add_event(think, EventSource.AGENT)
        return None
